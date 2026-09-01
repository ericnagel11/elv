"""Config-driven knowledge retrieval over Azure AI Search, scoped to a market.

Proof of concept 001 established that nothing in this module decides what the
assistant may draw on: that decision lives in Azure App Configuration under the
knowledge:* keys. This proof of concept adds two dimensions to that decision and
keeps the property intact.

  knowledge:filter           an OData filter, now covering language and jurisdiction
  knowledge:translation_gate the minimum review level a document must meet here
  knowledge:index            the per-language alias, for example kb-de-current

The gate is the control that makes the multilingual claim defensible. A document
is answerable in a market only when the human assurance behind its text meets or
exceeds what that market requires. Loosening the gate is a configuration change
that goes through the same draft-to-production approval path and lands in the
same audit trail as a change to tone, which means "who decided machine
translated content could answer German customers, and when" has a query rather
than an inquiry.

Index topology is one index per language behind an alias. The Azure AI Search
`analyzer` property is set on a field and fixed at index creation, so there is
no per-document analyzer; German decompounding and Spanish lemmatization
therefore need either a field per language or an index per language. Market
documents here are independent rather than parallel translations (the German
returns policy is a different policy, not a translation of the American one), so
an index per language is the better fit, and the alias keeps a rebuild of one
market from touching the others.
"""

import os
from functools import lru_cache

from azure.core.exceptions import ClientAuthenticationError, HttpResponseError
from azure.search.documents import SearchClient

import rbac
from config import AccessDenied, CredentialError

ENDPOINT_ENV = "AZURE_SEARCH_ENDPOINT"
SEMANTIC_CONFIG = "kb-semantic"

# The newest version the installed SDK knows about cannot resolve an index
# alias. The alias is what makes a per-language index swappable without touching
# configuration, so pin a version that resolves it.
SEARCH_API_VERSION = "2026-04-01"

# Fields the index exposes. Kept explicit so a schema change is visible here.
# The last five are what regionality added.
SELECT_FIELDS = [
    "title",
    "content",
    "url",
    "status",
    "effective_date",
    "language",
    "jurisdiction",
    "translation_status",
    "source_document",
    "source_version",
]

# A guard against one oversized document consuming the whole prompt budget.
MAX_CHARS_PER_DOCUMENT = 2500

# Review levels, ordered from most to least human assurance. `source` is the
# document in its original language, which is the strongest position a text can
# be in: nothing was translated, so nothing can have been lost.
REVIEW_LEVELS = ["source", "certified", "reviewed", "machine"]

# What each gate admits. A gate names the weakest level it will accept and
# everything stronger comes with it.
GATE_ALLOWS = {
    "certified": ["source", "certified"],
    "reviewed": ["source", "certified", "reviewed"],
    "machine_allowed": ["source", "certified", "reviewed", "machine"],
}

DEFAULT_GATE = "certified"

DEFAULTS = {
    "enabled": "false",
    "index": "kb-en-current",
    "filter": "",
    "top_k": "3",
    "query_mode": "simple",
    "citation_style": "inline",
    "translation_gate": DEFAULT_GATE,
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
    """Merge the knowledge:* values already resolved for a market over the
    defaults, so a partially seeded store still behaves predictably."""
    merged = dict(DEFAULTS)
    for key, value in (profile or {}).items():
        if value is not None and str(value).strip() != "":
            merged[key] = str(value).strip()
    return merged


def is_enabled(settings: dict) -> bool:
    return str(settings.get("enabled", "")).strip().lower() in {"true", "1", "yes", "on"}


def gate_of(settings: dict) -> str:
    gate = str(settings.get("translation_gate", DEFAULT_GATE)).strip().lower()
    return gate if gate in GATE_ALLOWS else DEFAULT_GATE


def gate_allows(settings: dict) -> list:
    return GATE_ALLOWS[gate_of(settings)]


def gate_predicate(settings: dict) -> str:
    """The OData fragment the certification gate contributes to the filter."""
    allowed = ",".join(gate_allows(settings))
    return f"search.in(translation_status, '{allowed}', ',')"


def effective_filter(settings: dict) -> str:
    """Combine the configured filter with the certification gate.

    Kept as two values rather than one so the gate can be moved on its own and
    so the UI can show which half of the scope a change touched. The gate is
    always applied, even when the configured filter is empty, because a market
    with no filter should still not receive unreviewed content.
    """
    configured_filter = (settings.get("filter") or "").strip()
    predicate = gate_predicate(settings)
    if not configured_filter:
        return predicate
    return f"({configured_filter}) and {predicate}"


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
        "filter": effective_filter(settings),
    }
    if semantic:
        kwargs["query_type"] = "semantic"
        kwargs["semantic_configuration_name"] = SEMANTIC_CONFIG
    return list(client.search(**kwargs))


def search(question: str, settings: dict, persona=None) -> dict:
    """Retrieve grounding documents under the configured scope for a market.

    Returns the documents, the filter that produced them, and any notes worth
    showing in the UI. Notes are how a silent fallback becomes visible.
    """
    notes = []
    index_name = settings.get("index") or DEFAULTS["index"]
    wants_semantic = (settings.get("query_mode") or "").strip().lower() == "semantic"

    try:
        client = _client(index_name, persona)
    except RuntimeError as exc:
        return {"documents": [], "notes": [str(exc)], "index": index_name,
                "filter": effective_filter(settings)}

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
                "notes": [
                    f"Index or alias '{index_name}' does not exist on the search service. "
                    "Each market points at its own alias, so this usually means "
                    "setup-knowledge.ps1 has not run for this language."
                ],
                "index": index_name,
                "filter": effective_filter(settings),
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
                "status": item.get("status") or "",
                "effective_date": item.get("effective_date") or "",
                "language": item.get("language") or "",
                "jurisdiction": item.get("jurisdiction") or "",
                "translation_status": item.get("translation_status") or "",
                "source_document": item.get("source_document") or "",
                "source_version": item.get("source_version") or "",
                "score": item.get("@search.score"),
                "reranker_score": item.get("@search.reranker_score"),
            }
        )

    if not documents:
        notes.append(
            "No document met this market's scope. The certification gate and the "
            "language or jurisdiction filter are the most likely reasons, and the "
            "correct behavior here is to decline rather than to answer from "
            "another market's content."
        )

    return {
        "documents": documents,
        "notes": notes,
        "index": index_name,
        "filter": effective_filter(settings),
    }


def below_certified(documents: list) -> list:
    """Documents that a certified-only market would have refused.

    Used by the UI to make a loosened gate visible. These documents are not
    errors; they are the consequence of a decision someone made and published.
    """
    strict = set(GATE_ALLOWS["certified"])
    return [item for item in documents
            if item["translation_status"] and item["translation_status"] not in strict]


def format_context(documents: list, citation_style: str = "inline") -> str:
    """Render retrieved documents as the {{context}} block of the prompt asset."""
    if not documents:
        return ""
    style = (citation_style or "inline").strip().lower()
    blocks = []
    for position, document in enumerate(documents, start=1):
        marker = f"[{position}] " if style != "none" else ""
        header = f"{marker}{document['title']}"
        meta = ", ".join(
            part for part in (
                f"language: {document['language']}" if document["language"] else "",
                f"jurisdiction: {document['jurisdiction']}" if document["jurisdiction"] else "",
                f"review level: {document['translation_status']}" if document["translation_status"] else "",
                f"effective: {document['effective_date']}" if document["effective_date"] else "",
            ) if part
        )
        body = document["content"]
        if document["truncated"]:
            body += "\n[truncated]"
        blocks.append(f"{header}\n({meta})\n{body}")
    return "\n\n".join(blocks)
