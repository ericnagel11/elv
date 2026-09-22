"""Pure, six-key Search configuration contract; no SDK imports or network I/O.

Values are returned as strings suitable for App Configuration. Normalization is
permissive for existing readers; validation is the strict boundary for editors
and publishers. Neither function mutates its input or DEFAULTS.
"""

import re
from collections.abc import Mapping

DEFAULT_QUESTION = (
    "I received a denial notice for my health insurance claim. How can I appeal it?"
)

DEFAULTS = {
    "enabled": "false",
    "index": "kb-current",
    "filter": "industry eq 'healthcare' and status eq 'approved'",
    "top_k": "3",
    "query_mode": "simple",
    "citation_style": "inline",
}

_BOOLEANS = {
    "true": "true", "1": "true", "yes": "true", "on": "true",
    "false": "false", "0": "false", "no": "false", "off": "false",
}
_ENUMS = {
    "query_mode": ("simple", "semantic"),
    "citation_style": ("inline", "footnote", "none"),
}
_INDEX_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{1,127}")


def normalize_settings(profile: Mapping | None) -> dict:
    """Resolve short keys to a fresh six-key dict, ignoring unrelated keys.

    Missing/None values and blank non-filter values use defaults, as legacy
    readers do. An explicitly empty (or whitespace-only) filter stays empty:
    this deliberately means no filter. Only outer whitespace is removed from
    expressions. Invalid nonblank values are retained for validate_settings().
    """
    if profile is not None and not isinstance(profile, Mapping):
        raise ValueError("Search settings must be a mapping of setting names to values.")
    source = profile if profile is not None else {}
    normalized = dict(DEFAULTS)
    for key in DEFAULTS:
        value = source.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if key == "filter" or text:
            normalized[key] = text
    for key in ("enabled", "query_mode", "citation_style"):
        normalized[key] = normalized[key].lower()
    normalized["enabled"] = _BOOLEANS.get(
        normalized["enabled"], normalized["enabled"]
    )
    return normalized


def validate_settings(settings: Mapping | None) -> dict:
    """Return normalized string values or a sanitized, user-facing ValueError.

    Missing keys use defaults; explicitly supplied invalid/blank non-filter
    values are rejected rather than silently fixed. top_k is an integer 1..20
    (not a float or bool). Index/alias checking is lexical only; existence,
    permissions, schema and semantic configuration must be checked separately.
    Filter validation only checks text type: this is NOT an OData parser or a
    guarantee that Azure Search accepts the expression or its field names.
    Error messages never echo submitted values.
    """
    if settings is not None and not isinstance(settings, Mapping):
        raise ValueError("Search settings must be a mapping of setting names to values.")
    source = settings if settings is not None else {}
    for key in DEFAULTS:
        if key not in source:
            continue
        value = source[key]
        if key == "filter":
            if not isinstance(value, str):
                raise ValueError("Search filter must be text; use an empty string for no filter.")
        else:
            allowed_types = (str, bool, int) if key == "enabled" else (str,)
            if key == "top_k":
                allowed_types = (str, int)
            if (not isinstance(value, allowed_types)
                    or (isinstance(value, str) and not value.strip())
                    or (key == "top_k" and isinstance(value, bool))):
                raise ValueError(f"Search {key} requires a nonempty value of the expected type.")
            # Check native integers before string conversion (which can itself
            # fail for huge integers on modern Python). Never echo the value.
            if key == "top_k" and isinstance(value, int) and not 1 <= value <= 20:
                raise ValueError("Search top_k must be an integer from 1 to 20.")
            if key == "enabled" and isinstance(value, int) and value not in (0, 1):
                raise ValueError("Search enabled must be true or false (also accepts yes/no, on/off, 1/0).")

    normalized = normalize_settings(settings)
    if normalized["enabled"] not in ("true", "false"):
        raise ValueError("Search enabled must be true or false (also accepts yes/no, on/off, 1/0).")
    name = normalized["index"]
    if not _INDEX_NAME.fullmatch(name) or "--" in name or "__" in name:
        raise ValueError(
            "Search index/alias must have 2-128 lowercase letters, digits, '-' or '_', "
            "start with a letter or digit, and contain no consecutive dashes or underscores."
        )
    # Ignore leading zeroes without converting an unbounded integer string.
    top = normalized["top_k"].lstrip("0")
    if not re.fullmatch(r"[0-9]{1,2}", top) or not 1 <= int(top) <= 20:
        raise ValueError("Search top_k must be an integer from 1 to 20.")
    normalized["top_k"] = str(int(top))
    for key, allowed in _ENUMS.items():
        if normalized[key] not in allowed:
            raise ValueError(f"Search {key} must be one of: {', '.join(allowed)}.")
    return normalized