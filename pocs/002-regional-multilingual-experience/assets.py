"""Versioned text assets that configuration names and the application delivers.

Two kinds of asset live here, and they share one property that makes them worth
separating from the prompt: their wording is approved by someone other than the
person who wrote the prompt, and it must survive contact with the model.

Disclosures are the strong case. A jurisdiction may require specific text to
accompany an automated response. That text is drafted by legal and approved
verbatim, so it must not pass through the model at all. A model asked to include
a required notice may paraphrase it, shorten it, translate it, or fold it into a
sentence, and every one of those outcomes is a compliance defect produced by an
otherwise well-behaved system. Configuration names the asset; this module loads
it; the application concatenates it after generation. The model never sees it.

Glossaries are the weaker case and go the other way. Approved terminology and
the do-not-translate list are injected *into* the prompt, because their job is
to shape what the model writes rather than to appear verbatim.

Both are named by configuration using the same `name:version` convention as
prompt assets, so `eu-ai-disclosure:v1` resolves to
disclosures/eu-ai-disclosure.v1.md.
"""

import os
import re

BASE_DIR = os.path.dirname(__file__)
DISCLOSURES_DIR = os.path.join(BASE_DIR, "disclosures")
GLOSSARIES_DIR = os.path.join(BASE_DIR, "glossaries")

# Every asset opens with an HTML comment naming its owner and its approval path.
# That header is for the reviewer who opens the file, not for the customer, so it
# is removed before delivery. Leaving it in would be invisible in rendered
# Markdown and glaringly present in a plain-text channel, which is the worst of
# both: a defect that passes review and then appears in production.
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def _body(text: str) -> str:
    return _COMMENT_RE.sub("", text).strip()


class DisclosureMissing(Exception):
    """A market requires a notice that could not be resolved.

    This is deliberately fatal to the request. Returning an answer without a
    required notice is worse than returning no answer, so the caller must not
    treat this as a warning and continue.
    """

    def __init__(self, asset_id: str, path: str):
        self.asset_id = asset_id
        self.path = path
        super().__init__(
            f"The disclosure asset '{asset_id}' is configured for this market but "
            f"was not found at {os.path.basename(path)}. No answer is returned, "
            "because an answer without a required notice is a compliance defect."
        )


def _asset_path(directory: str, asset_id: str, extension: str = ".md") -> str:
    # asset_id looks like "eu-ai-disclosure:v1" -> eu-ai-disclosure.v1.md
    name, _, version = asset_id.partition(":")
    filename = f"{name}.{version}{extension}" if version else f"{name}{extension}"
    return os.path.join(directory, filename)


def load_disclosure(asset_id: str) -> dict:
    """Load required notice text exactly as approved.

    Returns the raw text and its path so the UI can show a reviewer precisely
    which artifact reached the customer.
    """
    asset_id = (asset_id or "").strip()
    if not asset_id or asset_id.lower() == "none":
        return {"asset_id": "", "text": "", "path": ""}

    path = _asset_path(DISCLOSURES_DIR, asset_id)
    if not os.path.exists(path):
        raise DisclosureMissing(asset_id, path)
    with open(path, "r", encoding="utf-8") as handle:
        text = _body(handle.read())
    return {"asset_id": asset_id, "text": text, "path": os.path.basename(path)}


def append_disclosure(answer: str, disclosure: dict) -> str:
    """Concatenate the notice after the generated answer.

    Deliberately the least clever function in the application. Concatenation is
    the whole control: it is what guarantees the approved wording arrives
    unaltered, and anything more sophisticated would weaken that guarantee.
    """
    text = (disclosure or {}).get("text", "").strip()
    if not text:
        return answer
    return f"{answer.rstrip()}\n\n---\n\n{text}"


def load_glossary(asset_id: str) -> str:
    """Load approved terminology for injection into the prompt.

    A missing glossary is not fatal. Terminology drift is a quality problem
    rather than a compliance one, so the answer is still produced and the
    absence is reported in the UI.
    """
    asset_id = (asset_id or "").strip()
    if not asset_id or asset_id.lower() == "none":
        return ""
    path = _asset_path(GLOSSARIES_DIR, asset_id)
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as handle:
        return _body(handle.read())


def available(directory: str) -> list:
    if not os.path.isdir(directory):
        return []
    return sorted(name for name in os.listdir(directory) if name.endswith(".md"))
