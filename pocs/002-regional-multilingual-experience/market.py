"""Market resolution: the second configuration axis.

Proof of concept 001 resolved a profile from one App Configuration label
(`baseline` or `candidate`). Serving several markets adds a second axis, and
because an App Configuration label is a single string the two axes are composed
into a chain of labels that are read in order, most specific last:

    baseline            global defaults, every key
    de-DE               market overrides, only the keys that differ
    de-DE-candidate     experiment overrides, only the keys under test

Two properties follow, and the second is the one that gets missed.

Sparseness is the benefit: a market layer holds only what it changes, so a
global improvement reaches every market that has not deliberately diverged.

Sparseness is also the hazard: a change to a `baseline` key reaches every market
that does not override it, without any market reviewer seeing it. That is
usually the intent and occasionally a serious problem, so this module never
returns a bare value. It returns the value *and the layer that supplied it*, and
it can report which markets inherit a given key before that key is changed.
"""

from functools import lru_cache

import config as cfg

# The demonstration markets. The registry says which markets exist and how to
# label them; everything *about* a market (formality, jurisdiction, retrieval
# scope, disclosures) is governed configuration read from Azure, not from here.
MARKETS = {
    "en-US": {
        "label": "United States (English)",
        "language": "en",
        "summary": "Source market. Its content is the certified content.",
    },
    "es-MX": {
        "label": "Mexico (Spanish)",
        "language": "es",
        "summary": "High volume, moderate risk. Marks formality where English does not.",
    },
    "de-DE": {
        "label": "Germany (German)",
        "language": "de",
        "summary": "Regulated. Consumer law contradicts the United States policy.",
    },
}

DEFAULT_MARKET = "de-DE"

# The global default layer. Named to match proof of concept 001 so the two
# stores and the two demonstrations stay recognisably the same system.
GLOBAL_LAYER = "baseline"

# Suffix appended to a market label to hold an experiment's overrides.
CANDIDATE_SUFFIX = "-candidate"

# The prefixes that make up a resolved market profile. `market:` is new in this
# proof of concept and holds the facts that are neither voice nor retrieval.
PREFIXES = (cfg.EXPERIENCE_PREFIX, cfg.MARKET_PREFIX, cfg.KNOWLEDGE_PREFIX)

EDITABLE_MARKET_KEYS = [
    "locale",
    "language",
    "jurisdiction",
    "disclosure_set",
    "glossary_asset",
    "language_adherence",
    "escalation_path",
]


def candidate_label(locale: str) -> str:
    return f"{locale}{CANDIDATE_SUFFIX}"


def layer_labels(locale: str, with_candidate: bool = False) -> list:
    """The labels to read, in order, least specific first."""
    labels = [GLOBAL_LAYER, locale]
    if with_candidate:
        labels.append(candidate_label(locale))
    return labels


def resolve(locale: str, prefix: str, store: str = "production", persona=None,
            with_candidate: bool = False, reader=None) -> dict:
    """Resolve one prefix for a market across the layer chain.

    Returns `{short_key: {"value": ..., "layer": ...}}` rather than a flat dict,
    because which layer supplied a value is the thing a reviewer needs to see.
    A later layer wins, and a layer that does not mention a key leaves the
    inherited value and its provenance untouched.

    `reader` exists so a caller can supply a cached single-layer read with the
    same signature as cfg.load_profile. The resolution order stays here, in one
    place, rather than being reimplemented wherever caching is wanted.
    """
    read = reader or cfg.load_profile
    resolved = {}
    for label in layer_labels(locale, with_candidate):
        for short_key, value in read(label, store, persona, prefix).items():
            resolved[short_key] = {"value": value, "layer": label}
    return resolved


def resolve_all(locale: str, store: str = "production", persona=None,
                with_candidate: bool = False, reader=None) -> dict:
    """Resolve every prefix for a market. Keys are fully qualified."""
    combined = {}
    for prefix in PREFIXES:
        for short_key, entry in resolve(locale, prefix, store, persona,
                                        with_candidate, reader).items():
            combined[f"{prefix}{short_key}"] = entry
    return combined


def provenance_rows(resolved: dict) -> list:
    """Rows for the UI, ordered so overrides are easy to spot."""
    rows = []
    for key in sorted(resolved):
        entry = resolved[key]
        rows.append({
            "setting": key,
            "value": entry["value"],
            "supplied by": entry["layer"],
            "inherited": "yes" if entry["layer"] == GLOBAL_LAYER else "no",
        })
    return rows


def inheritors(prefix: str, short_key: str, store: str = "production",
               persona=None, reader=None) -> dict:
    """Blast radius: which markets would receive a change to a global default.

    A market appears under "inherits" when it has no override for the key, which
    means a change to `baseline` reaches its customers without a market reviewer
    seeing it. This is the check that turns an invisible default into a reviewed
    decision, and it is why it is worth running before publishing rather than
    after.
    """
    read = reader or cfg.load_profile
    inherits, overrides = [], []
    for locale in MARKETS:
        market_layer = read(locale, store, persona, prefix)
        if short_key in market_layer:
            overrides.append({
                "market": f"{locale} ({display(locale)})",
                "overriding value": market_layer[short_key],
            })
        else:
            inherits.append(locale)
    return {"inherits": inherits, "overrides": overrides}


@lru_cache(maxsize=8)
def language_of(locale: str) -> str:
    """The language subtag, used for asset fallback and retrieval."""
    return MARKETS.get(locale, {}).get("language") or locale.split("-")[0].lower()


def display(locale: str) -> str:
    return MARKETS.get(locale, {}).get("label", locale)
