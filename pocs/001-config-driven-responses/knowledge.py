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
"""

import os
from functools import lru_cache

from azure.core.exceptions import ClientAuthenticationError, HttpResponseError
from azure.search.documents import SearchClient

import rbac
from config import AccessDenied, CredentialError

KNOWLEDGE_PREFIX = "knowledge:"
ENDPOINT_ENV = "AZURE_SEARCH_ENDPOINT"
SEMANTIC_CONFIG = "kb-semantic"

# The newest version the installed SDK knows about is 2025-09-01, and that
# version cannot resolve an index alias: querying kb-current returns 404 while
# querying kb-v1 directly succeeds. The alias is what makes the knowledge set
# swappable without touching configuration, so pin a version that resolves it.
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

DEFAULTS = {
    "enabled": "false",
    "index": "kb-current",
    "filter": "",
    "top_k": "3",
    "query_mode": "simple",
    "citation_style": "inline",
}


def endpoint() -> str:
    return os.environ.get(ENDPOINT_ENV, "")


def configured() -> bool:
    return bool(endpoint())


@lru_cache(maxsize=16)
def _client(index_name: str, persona) -> SearchClient:
    if not endpoint():
        raise RuntimeError(
            "No search endpoint. Run scripts/setup-knowledge.ps1, then restart the app."
        )
    return SearchClient(
        endpoint=endpoint(),
        index_name=index_name,
        credential=rbac.credential_for(persona),
        api_version=SEARCH_API_VERSION,
    )


def settings_from_profile(profile: dict) -> dict:
    """Merge the knowledge:* values already loaded from App Configuration over the
    defaults, so a partially seeded store still behaves predictably."""
    merged = dict(DEFAULTS)
    for key, value in (profile or {}).items():
        if value is not None and str(value).strip() != "":
            merged[key] = str(value).strip()
    return merged


def is_enabled(settings: dict) -> bool:
    return str(settings.get("enabled", "")).strip().lower() in {"true", "1", "yes", "on"}


def _top_k(settings: dict) -> int:
    try:
        return max(1, min(20, int(str(settings.get("top_k", "3")).strip())))
    except ValueError:
        return 3


def _run(client: SearchClient, question: str, settings: dict, semantic: bool):
    kwargs = {
        "search_text": question,
        "top": _top_k(settings),
        "select": SELECT_FIELDS,
    }
    filter_expression = (settings.get("filter") or "").strip()
    if filter_expression:
        kwargs["filter"] = filter_expression
    if semantic:
        kwargs["query_type"] = "semantic"
        kwargs["semantic_configuration_name"] = SEMANTIC_CONFIG
    return list(client.search(**kwargs))


def search(question: str, settings: dict, persona=None) -> dict:
    """Retrieve grounding documents under the configured scope.

    Returns the documents, the filter that produced them, and any notes worth
    showing in the UI. Notes are how a silent fallback becomes visible.
    """
    notes = []
    index_name = settings.get("index") or DEFAULTS["index"]
    wants_semantic = (settings.get("query_mode") or "").strip().lower() == "semantic"

    try:
        client = _client(index_name, persona)
    except RuntimeError as exc:
        return {"documents": [], "notes": [str(exc)], "index": index_name}

    try:
        try:
            raw = _run(client, question, settings, semantic=wants_semantic)
        except HttpResponseError as exc:
            # Semantic ranking needs Basic tier or higher and a semantic
            # configuration on the index. Falling back keeps the demo working on
            # the Free tier, but the fallback is reported rather than hidden.
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
        if exc.status_code == 401:
            raise CredentialError("search", (exc.message or "").strip() or "Unauthorized") from exc
        if exc.status_code == 403:
            raise AccessDenied(
                "query the knowledge index", "search",
                f"HTTP 403: {(exc.message or '').strip() or 'Forbidden'}",
            ) from exc
        if exc.status_code == 404:
            return {
                "documents": [],
                "notes": [f"Index '{index_name}' does not exist on the search service."],
                "index": index_name,
            }
        raise

    documents = []
    for item in raw:
        content = (item.get("content") or "").strip()
        documents.append(
            {
                "title": item.get("title") or "Untitled",
                "content": content[:MAX_CHARS_PER_DOCUMENT],
                "truncated": len(content) > MAX_CHARS_PER_DOCUMENT,
                "url": item.get("url") or "",
                "industry": item.get("industry") or "",
                "audience": item.get("audience") or "",
                "status": item.get("status") or "",
                "effective_date": item.get("effective_date") or "",
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
    """Render retrieved documents as the {{context}} block of the prompt asset."""
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
            )
            if part
        )
        body = document["content"]
        if document.get("truncated"):
            body += "\n(excerpt truncated)"
        blocks.append(f"{header}\n({meta})\n{body}" if meta else f"{header}\n{body}")
    return "\n\n---\n\n".join(blocks)


def citation_list(documents: list) -> list:
    return [
        {"n": position, "title": document["title"], "status": document["status"],
         "score": document.get("reranker_score") or document.get("score")}
        for position, document in enumerate(documents, start=1)
    ]
