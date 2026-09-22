"""Config-driven knowledge retrieval over Azure AI Search.

The point of this module is that nothing here decides *what* the assistant is
allowed to draw on. That decision lives in Azure App Configuration under the
knowledge:* keys, exactly as the wording decisions live under experience:*.

  knowledge:enabled         whether answers are grounded at all
  knowledge:index           which knowledge set is live
  knowledge:filter          an OData filter, for example status eq 'approved'
  knowledge:top_k           how many documents to retrieve
  knowledge:query_mode      simple (keyword) or semantic
  knowledge:citation_style  inline, footnote, or none

Changing any of these changes what the assistant knows, with no code release and
no reindexing.

How the application consumes this module:
  1. config.load_knowledge() reads App Configuration and removes the knowledge:
     prefix. The UI or ConfiguredResponseRuntime passes that dict to
     settings_from_profile() to fill in defaults.
  2. experience_runtime.run_grounded() calls search(question, scope, persona).
     search() obtains an SDK client with _client() and queries Search in _run().
  3. run_grounded() uses format_context(found["documents"], citation_style) as
     the prompt's context input. The separate prompt module calls Azure OpenAI;
     this module only retrieves and formats grounding material.
  4. a2a_agent._safe_result() uses citation_list() to expose source summaries
     without putting the retrieved document bodies in the A2A metadata.

Configuration filters narrow retrieval; they do not replace Azure authorization.
Underscore-prefixed functions are internal helpers, not application entry points.
"""

import os
import re
from functools import lru_cache

from azure.core.exceptions import ClientAuthenticationError, HttpResponseError
from azure.search.documents import SearchClient

import rbac
from config import AccessDenied, CredentialError, validate_knowledge_value
from search_settings import DEFAULTS, normalize_settings

KNOWLEDGE_PREFIX = "knowledge:"
ENDPOINT_ENV = "AZURE_SEARCH_ENDPOINT"
SEMANTIC_CONFIG = "kb-semantic"

# Pin the REST API contract rather than inheriting the installed SDK's default.
# The configured index can be an alias such as kb-current; its target must expose
# SELECT_FIELDS and, for semantic mode, SEMANTIC_CONFIG. Constructing the client
# does not validate that the alias, index, schema, or permissions are available.
SEARCH_API_VERSION = "2026-04-01"

# Fields the index exposes. Kept explicit so a schema change is visible here.
SELECT_FIELDS = [
    "title",
    "content",
    "url",
    "industry",
    "audience",
    "status",
    "effective_date",
]

# A guard against one oversized document consuming the whole prompt budget.
MAX_CHARS_PER_DOCUMENT = 2500

FIELD_DEFAULTS = {
    "title": "title",
    "content": "content",
    "url": "url",
    "industry": "industry",
    "audience": "audience",
    "status": "status",
    "effective_date": "effective_date",
    "state": "",
    "source": "",
}


def field_mapping(settings: dict) -> dict:
    mapping = {}
    for name, default in FIELD_DEFAULTS.items():
        value = str(settings.get(f"{name}_field", default)).strip()
        if value and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(/[A-Za-z][A-Za-z0-9_]*)*", value):
            raise ValueError(f"knowledge:{name}_field must be a Search field name or empty.")
        if name in {"title", "content"} and not value:
            raise ValueError(f"knowledge:{name}_field is required.")
        mapping[name] = value
    return mapping


def _field_value(item: dict, path: str):
    value = item
    for part in path.split("/"):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def endpoint() -> str:
    """Return the Search service URL from the process environment, or "" if unset.

    Used by configured() and _client(). Application startup loads environment
    settings before retrieval; this accessor does not load a .env file, contact
    Azure, or validate the URL. The index name is supplied separately to _client().
    """
    return os.environ.get(ENDPOINT_ENV, "")


def configured() -> bool:
    """Tell app.py whether to show the knowledge-scope controls or a setup notice.

    This checks only that AZURE_SEARCH_ENDPOINT is nonempty. It does not verify
    connectivity, credentials, index existence, or whether grounding is enabled;
    is_enabled() handles the separate knowledge:enabled setting.
    """
    return bool(endpoint())


@lru_cache(maxsize=16)
def _client(index_name: str, persona) -> SearchClient:
    """Build/reuse the SDK client that search() needs for an index and persona.

    index_name can be the configured index or alias. rbac.credential_for()
    supplies a token credential: an explicit managed identity in Azure VM mode,
    or a configured service principal/developer credential in development mode.
    Azure Identity and the Search SDK handle tokens; no Search API key is used.
    Query access must already be granted, for example Search Index Data Reader.

    Construction does not run a search; _run() executes the query. The LRU cache
    reuses clients for up to 16 index/persona pairs, not search results. Changing
    the configured index selects a different cache entry. Endpoint
    or identity-configuration changes require cache clearing or a process restart.
    A missing endpoint raises RuntimeError, which search() converts into a note.
    """
    if not endpoint():
        raise RuntimeError(
            "Search grounding is unavailable: AZURE_SEARCH_ENDPOINT is not configured. "
            "No Search request was made."
        )
    return SearchClient(
        endpoint=endpoint(),
        index_name=index_name,
        credential=rbac.credential_for(persona),
        api_version=SEARCH_API_VERSION,
    )


def settings_from_profile(profile: dict) -> dict:
    """Return retrieval settings for the UI, runtime and diagnostic script.

    Call after config.load_knowledge(), which has already fetched configuration
    and removed the key prefix: pass {"index": "kb-current"}, not
    {"knowledge:index": "kb-current"}. Normalize the six shared controls, then
    retain explicit field mappings for existing indexes. Profile is not modified.
    An explicit blank filter means no filter; a missing/None filter uses the
    healthcare sample default. Blank optional mappings omit unavailable fields.
    No Azure request is made here. Pass the result to is_enabled() and search();
    individual helpers interpret values such as enabled and top_k later.
    Editors/publishers can use search_settings.validate_settings() for strict
    local validation, which does not validate OData or contact the service.
    """
    settings = normalize_settings(profile)
    mapping_keys = [f"{name}_field" for name in FIELD_DEFAULTS]
    for key in [*mapping_keys, "search_fields", "semantic_configuration"]:
        value = (profile or {}).get(key)
        if value is not None:
            settings[key] = str(value).strip()
    return settings


def is_enabled(settings: dict) -> bool:
    """Interpret the enabled setting for callers deciding whether to ground.

    ConfiguredResponseRuntime.invoke() uses this predicate to choose grounded
    versus ungrounded generation; app.py also uses it to display a scope warning.
    Only true, 1, yes and on (case-insensitive) enable grounding. run_grounded()
    also enforces this gate for direct previews. search() remains low-level;
    its callers must decide whether retrieval is appropriate before invoking it.
    """
    return str(settings.get("enabled", "")).strip().lower() in {"true", "1", "yes", "on"}


def _top_k(settings: dict) -> int:
    """Convert the configured result limit into the integer passed to SDK top.

    Used only by _run(). Clamp parsed values to 1-20; missing or non-integer
    values use 3. This bounds the requested document count, not document length
    or model tokens; search() separately truncates each document's content.
    """
    try:
        return max(1, min(20, int(str(settings.get("top_k", "3")).strip())))
    except ValueError:
        return 3


def _run(client: SearchClient, question: str, settings: dict, semantic: bool):
    """Execute the read-only Azure AI Search request on behalf of search().

    client is the index/persona-specific SDK client; question becomes search_text.
    Settings supply the result limit and optional OData filter. semantic=True
    enables semantic reranking with the existing kb-semantic configuration;
    otherwise this is a keyword query. No vectors or embeddings are sent here.

    Return a materialized list of SDK search results. Iterating the SDK's paged
    result executes requests (and any paging), so service errors occur inside
    search()'s error-handling block. This helper does not catch those errors.
    SDK transport retries are separate from search()'s semantic fallback.
    """
    mapping = field_mapping(settings)
    kwargs = {
        "search_text": question,
        "top": _top_k(settings),
        "select": list(dict.fromkeys(field for field in mapping.values() if field)),
    }
    search_fields = (settings.get("search_fields") or "").strip()
    if search_fields:
        fields = [field.strip() for field in search_fields.split(",")]
        if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(/[A-Za-z][A-Za-z0-9_]*)*", field) for field in fields):
            raise ValueError("knowledge:search_fields must be comma-separated Search field names.")
        kwargs["search_fields"] = fields
    filter_expression = (settings.get("filter") or "").strip()
    if filter_expression:
        # Pass the configured scope as an OData filter, not as search-text syntax.
        kwargs["filter"] = filter_expression
    if semantic:
        kwargs["query_type"] = "semantic"
        kwargs["semantic_configuration_name"] = settings.get("semantic_configuration") or SEMANTIC_CONFIG
    # This is the SDK query call; consume the lazy response before returning.
    return list(client.search(**kwargs))


def search(question: str, settings: dict, persona=None) -> dict:
    """Retrieve grounding documents for run_grounded() or the diagnostic script.

    Args:
        question: User text to submit to Azure AI Search, not to an LLM here.
        settings: Retrieval scope, normally produced by settings_from_profile().
            The caller owns the enabled check; this function always attempts
            retrieval when called, even if settings["enabled"] is false.
        persona: Credential selector passed to rbac.credential_for(). Azure VM
            mode requires an explicit configured persona; None is not a VM default.

    Returns:
        A dict with documents, notes and index (not a copy of the filter).
        Each document has title, bounded content, a truncated flag, source
        metadata and relevance scores. run_grounded() formats these for the
        prompt; the UI displays notes; the A2A layer derives citation summaries.
        Missing endpoint/index and zero matches return empty documents plus notes.

    Query-time authentication failures become CredentialError and denials become
    AccessDenied for caller handling. Semantic HTTP 400/403 triggers a reported
    keyword retry with the same identity, index and filter; remaining HTTP errors
    propagate except 404, which becomes an index-not-found note. Retrieval can
    contact Azure, but does not modify the index or generate a model response.
    """
    notes = []
    mapping = field_mapping(settings)
    index_name = settings.get("index") or DEFAULTS["index"]
    rbac.require_grounding(index_name, persona)
    if rbac.comparison_mode():
        for key in ("enabled", "index", "top_k", "query_mode", "citation_style"):
            validate_knowledge_value(key, str(settings.get(key, DEFAULTS[key])))
    wants_semantic = (settings.get("query_mode") or "").strip().lower() == "semantic"

    try:
        client = _client(index_name, persona)
    except RuntimeError as exc:
        if rbac.comparison_mode():
            raise ValueError("Configure the approved AZURE_SEARCH_ENDPOINT before requesting grounding.") from None
        return {"documents": [], "notes": [str(exc)], "index": index_name}

    try:
        try:
            raw = _run(client, question, settings, semantic=wants_semantic)
        except HttpResponseError as exc:
            # Preserve the configured scope and credentials on the keyword retry.
            # HTTP 400/403 can have causes other than tier/configuration limits;
            # the fallback is reported, and errors from the retry propagate below.
            if wants_semantic and exc.status_code in (400, 403):
                notes.append(
                    "Semantic ranking was unavailable, so keyword ranking was used. "
                    "Semantic ranking requires the Basic tier or higher."
                )
                raw = _run(client, question, settings, semantic=False)
            else:
                raise
    except ClientAuthenticationError as exc:
        raise CredentialError("search", str(exc)) from exc
    except HttpResponseError as exc:
        if exc.status_code == 400:
            raise ValueError(
                "Azure AI Search rejected the query (HTTP 400). Check knowledge:filter, "
                "search fields and field mappings. Filter field names are case-sensitive "
                "and must exist and be filterable in the selected index. Correct the "
                "profile in Configuration > Knowledge, then save or refresh before retrying. "
                "The configured filter was not removed."
            ) from None
        if exc.status_code == 401:
            raise CredentialError("search", (exc.message or "").strip() or "Unauthorized") from exc
        if exc.status_code == 403:
            raise AccessDenied(
                "query the knowledge index", "search",
                f"HTTP 403: {(exc.message or '').strip() or 'Forbidden'}",
            ) from exc
        if exc.status_code == 404:
            if rbac.comparison_mode():
                raise ValueError("The configured Search index could not be found.") from None
            return {
                "documents": [],
                "notes": [f"Index '{index_name}' does not exist on the search service."],
                "index": index_name,
            }
        raise

    # Normalize SDK results once so prompt, UI and A2A consumers share one shape.
    # Truncation happens after retrieval; it is not a Search response-size limit.
    documents = []
    for item in raw:
        content = _field_value(item, mapping["content"]) or ""
        if not isinstance(content, str):
            raise ValueError("The configured content field must contain text.")
        content = content.strip()
        if not content:
            continue
        values = {
            name: str(_field_value(item, field) or "") if field else ""
            for name, field in mapping.items() if name != "content"
        }
        documents.append(
            {
                **values,
                "title": values["title"] or "Untitled",
                "content": content[:MAX_CHARS_PER_DOCUMENT],
                "truncated": len(content) > MAX_CHARS_PER_DOCUMENT,
                "score": item.get("@search.score"),
                "reranker_score": item.get("@search.reranker_score"),
            }
        )

    if not documents:
        notes.append(
            "No document matched within the configured scope. "
            "The filter is the most likely reason."
        )

    return {"documents": documents, "notes": notes, "index": index_name}


def format_context(documents: list, citation_style: str = "inline") -> str:
    """Render search()["documents"] into the prompt's {{context}} text block.

    run_grounded() and the diagnostic script pass this string to prompt generation.
    Empty input returns "". Inline and footnote styles both use numbered source
    labels here; none uses unnumbered labels. Metadata and truncation notices are
    included, with source order preserved to match citation_list(). This is pure
    formatting: it neither queries Search nor calls the model or changes documents.
    """
    if not documents:
        return ""
    style = (citation_style or "inline").strip().lower()
    blocks = []
    for position, document in enumerate(documents, start=1):
        if style == "none":
            header = f"Source: {document['title']}"
        else:
            header = f"[{position}] {document['title']}"
        meta = ", ".join(
            part
            for part in (
                f"industry: {document['industry']}" if document["industry"] else "",
                f"status: {document['status']}" if document["status"] else "",
                f"effective: {document['effective_date']}" if document["effective_date"] else "",
                f"state: {document['state']}" if document.get("state") else "",
            )
            if part
        )
        body = document["content"]
        if document.get("truncated"):
            body += "\n(excerpt truncated)"
        blocks.append(f"{header}\n({meta})\n{body}" if meta else f"{header}\n{body}")
    return "\n\n---\n\n".join(blocks)


def citation_list(documents: list) -> list:
    """Return compact source metadata for a2a_agent._safe_result().

    Consume the normalized documents from search(), preserving their order so
    1-based n values match the labels in format_context(). Each entry contains
    n, title, status and score, but no document body, URL or retrieval filter.
    Score uses a truthy reranker_score, otherwise score, as the expression below
    specifies. Empty input returns []; no Azure request or model call is made.
    """
    return [
        {"n": position, "title": document["title"], "status": document["status"],
         "source": document.get("source", ""), "state": document.get("state", ""),
         "score": document.get("reranker_score") or document.get("score")}
        for position, document in enumerate(documents, start=1)
    ]
