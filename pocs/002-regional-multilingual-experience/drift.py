"""Translation drift: the failure mode that localized content has and English-only
content does not.

When the English source policy is revised, the certified German translation
stays certified. It is certified against a version of the source that no longer
exists, and nothing in its approval state records that. The document is not
wrong in any way a reviewer can see by reading it; it is wrong because something
else changed.

Two fields make this detectable. A localized document records the source it was
derived from and the version of that source at the time. Comparing that against
the source's current version turns an inspection into a report, and re-certification
becomes something that is scheduled rather than discovered.

The manifest is the content steward's register and is the authority here, so
this module needs no Azure resources and works before the knowledge layer is
provisioned. In production the same comparison would run against the index.
"""

import json
import os

MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "knowledge", "manifest.json")

# The review levels that represent derived text. A source document cannot drift
# from itself, so it is never reported.
DERIVED_LEVELS = {"certified", "reviewed", "machine"}


def load_manifest() -> dict:
    if not os.path.exists(MANIFEST_PATH):
        return {"documents": []}
    with open(MANIFEST_PATH, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _version_number(value) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def report() -> list:
    """One row per derived document, current and stale alike.

    Reporting the current ones too is deliberate. A drift report that lists only
    problems cannot be distinguished from a drift report that failed to run.
    """
    manifest = load_manifest()
    documents = manifest.get("documents", [])
    sources = {
        item.get("file"): _version_number(item.get("version"))
        for item in documents
        if (item.get("translation_status") or "").strip().lower() == "source"
    }

    rows = []
    for item in documents:
        level = (item.get("translation_status") or "").strip().lower()
        source_name = (item.get("source_document") or "").strip()
        # A document that records no source cannot drift from one. A German
        # policy authored in German sits at 'reviewed' because that is the human
        # assurance behind it, not because it was translated from anything.
        if level not in DERIVED_LEVELS or not source_name:
            continue
        derived_from = _version_number(item.get("source_version"))
        current = sources.get(source_name)

        if current is None:
            state, gap = "orphaned", ""
            note = "The source document is not in the register. It may have been withdrawn."
        elif derived_from < current:
            state, gap = "behind", str(current - derived_from)
            note = f"Re-certification needed. Derived from v{derived_from}, source is now v{current}."
        else:
            state, gap = "current", "0"
            note = ""

        rows.append({
            "document": item.get("file", ""),
            "language": item.get("language", ""),
            "review level": level,
            "source": source_name,
            "derived from": f"v{derived_from}" if derived_from else "(unrecorded)",
            "source now": f"v{current}" if current else "(unknown)",
            "state": state,
            "versions behind": gap,
            "note": note,
        })

    order = {"orphaned": 0, "behind": 1, "current": 2}
    return sorted(rows, key=lambda row: (order.get(row["state"], 3), row["document"]))


def summary() -> dict:
    rows = report()
    return {
        "derived documents": len(rows),
        "behind their source": sum(1 for row in rows if row["state"] == "behind"),
        "orphaned": sum(1 for row in rows if row["state"] == "orphaned"),
        "current": sum(1 for row in rows if row["state"] == "current"),
    }
