"""Offline Search form and UI-result invalidation; no configuration writes or SDKs.

Pass the raw, short-key scope (not an already defaulted/normalized scope) so the
form can distinguish absent settings from invalid or explicitly blank settings.
The caller owns persistence, authorization, and configuration/cache refresh.
"""

from search_settings import DEFAULTS, validate_settings


_QUERY_MODES = ("simple", "semantic")
_CITATION_STYLES = ("inline", "footnote", "none")
_TEXT_FIELDS = ("index", "filter")


def _initial_values(scope: dict) -> tuple[dict, dict]:
    """Collect every invalid stored field without coercing the supplied scope."""
    values = dict(DEFAULTS)
    invalid = {}
    for key in DEFAULTS:
        if key not in scope:
            continue
        try:
            values[key] = validate_settings({key: scope[key]})[key]
        except ValueError as exc:
            invalid[key] = str(exc)
        # Text widgets can show invalid text for correction. Preserve filter
        # whitespace and quotes in the widget; normalize only on submission.
        if key in _TEXT_FIELDS and isinstance(scope[key], str):
            values[key] = scope[key]
    return values, invalid


def _display(value) -> str:
    """Describe stored values, including integers too large for Python's repr."""
    try:
        return repr(value)
    except (TypeError, ValueError):
        return f"<{type(value).__name__}: not printable>"


def _field_caption(st, scope: dict, key: str, initial: dict, invalid: dict, *, show_default=True) -> None:
    if key not in scope:
        st.caption(
            f"knowledge:{key} — Not stored; configuration default: {DEFAULTS[key]!r}."
            if show_default else f"knowledge:{key} — Not stored; load the selected profile before editing."
        )
        return
    caption = f"knowledge:{key} — Stored: {_display(scope[key])}"
    caption += f"; default if absent: {DEFAULTS[key]!r}." if show_default else "."
    if key in invalid:
        caption += f" Invalid stored value: {invalid[key]}"
        if key in _TEXT_FIELDS and isinstance(scope[key], str):
            caption += " Stored text is shown for correction."
        else:
            caption += f" Widget fallback (not saved): {initial[key]!r}."
    st.caption(caption)


def render_search_form(st, scope: dict, *, editable: bool, widget_key: str,
                       index_options: tuple | None = None,
                       query_modes: tuple = _QUERY_MODES) -> dict | None:
    """Return a fresh, validated six-key string dict only on editable submission.

    ``widget_key`` must include the caller's identity/store/label and config
    revision, preventing stale edits or acknowledgements crossing those scopes.
    Keys are ``{widget_key}:search:form``, ``{widget_key}:search:{setting}`` for
    each of the six short setting names, and ``{widget_key}:search:ack_no_filter``.
    The submit button is scoped by the form (Streamlit 1.36 has no submit key
    argument). No caller state, stored scope, or server context is mutated here.

    Invalid stored values are listed visibly. Bounded widgets use explicitly
    marked defaults; text widgets retain correctable text. Only an explicit
    Save can return those displayed values, and a blank filter also needs its
    acknowledgement. This validates types/ranges, not OData or Search schema.
    Optional index/mode choices restrict a VM form without changing the full demo.
    """
    if not query_modes or any(mode not in _QUERY_MODES for mode in query_modes):
        raise ValueError("Choose supported Search query modes for this form.")
    if index_options is not None and not index_options:
        raise ValueError("At least one approved Search index is required.")
    initial, invalid = _initial_values(scope)
    if initial["query_mode"] not in query_modes:
        invalid["query_mode"] = "This query mode is not enabled for this deployment."
        initial["query_mode"] = query_modes[0]
    prefix = f"{widget_key}:search"
    disabled = not editable
    if disabled:
        st.info("Search settings are read-only; all controls remain visible, but saving is disabled.")
    if invalid:
        st.warning(
            "Existing invalid Search settings: "
            + ", ".join(f"knowledge:{key}" for key in invalid)
            + ". No configuration has been changed. Correct the stored text or review "
            "the indicated widget fallbacks; Save Search settings submits the displayed values."
        )

    with st.form(key=f"{prefix}:form", clear_on_submit=False):
        values = {}
        values["enabled"] = st.toggle(
            "Enable Search grounding", value=initial["enabled"] == "true",
            key=f"{prefix}:enabled", disabled=disabled,
        )
        _field_caption(st, scope, "enabled", initial, invalid)
        if index_options is None:
            values["index"] = st.text_input(
                "Search index or alias", value=initial["index"],
                key=f"{prefix}:index", disabled=disabled,
                help="Existing approved index/alias. Only name syntax is checked, not existence or access.",
            )
        else:
            values["index"] = st.selectbox(
                "Search index or alias", index_options,
                index=index_options.index(initial["index"]) if initial["index"] in index_options else None,
                key=f"{prefix}:index", disabled=disabled,
            )
        _field_caption(st, scope, "index", initial, invalid)
        values["filter"] = st.text_area(
            "OData filter", value=initial["filter"], height=120,
            key=f"{prefix}:filter", disabled=disabled,
            help="Passed unchanged apart from outer whitespace. OData and field names are not validated locally.",
        )
        _field_caption(st, scope, "filter", initial, invalid, show_default=index_options is None)
        if index_options is None:
            st.caption(
                f"OData example: {DEFAULTS['filter']}. Confirm your index schema and approved scope; "
                "broadening a filter may include unapproved content."
            )
        else:
            st.caption(
                "Filter field names are case-sensitive and must be filterable in the selected index. "
                "Field mappings do not rename fields inside an OData filter."
            )
        st.warning(
            "A blank filter applies no OData restriction and may broaden retrieval. "
            "Saving a blank filter requires the acknowledgement below."
        )
        # Always show this: form edits are batched, so a newly blank filter does
        # not trigger a rerender that could reveal a conditional checkbox.
        acknowledge_blank = st.checkbox(
            "I acknowledge that a blank filter applies no filter and may broaden retrieval.",
            value=False, key=f"{prefix}:ack_no_filter", disabled=disabled,
        )
        values["top_k"] = st.number_input(
            "Top documents (top_k)", min_value=1, max_value=20,
            value=int(initial["top_k"]), step=1,
            key=f"{prefix}:top_k", disabled=disabled,
        )
        _field_caption(st, scope, "top_k", initial, invalid)
        values["query_mode"] = st.selectbox(
            "Query mode", query_modes, index=query_modes.index(initial["query_mode"]),
            key=f"{prefix}:query_mode", disabled=disabled,
            help=("Semantic mode requires a compatible index with the kb-semantic semantic configuration."
                  if "semantic" in query_modes else "Keyword retrieval on the approved existing index."),
        )
        _field_caption(st, scope, "query_mode", initial, invalid)
        values["citation_style"] = st.selectbox(
            "Citation style", _CITATION_STYLES,
            index=_CITATION_STYLES.index(initial["citation_style"]),
            key=f"{prefix}:citation_style", disabled=disabled,
        )
        _field_caption(st, scope, "citation_style", initial, invalid)
        submitted = st.form_submit_button("Save Search settings", disabled=disabled)

    if not editable or not submitted:
        return None
    try:
        normalized = validate_settings(values)
    except ValueError as exc:
        st.error(str(exc))
        return None
    if index_options is not None and normalized["index"] not in index_options:
        st.error("The Search index is not approved for this deployment.")
        return None
    if normalized["query_mode"] not in query_modes:
        st.error("The query mode is not enabled for this deployment.")
        return None
    if not normalized["filter"] and not acknowledge_blank:
        st.error("A blank filter applies no filter. Tick the explicit acknowledgement before saving.")
        return None
    return normalized


def reset_results(state, published: bool) -> None:
    """Invalidate only UI results/context IDs; never mutate server-side contexts.

    Draft saves invalidate knowledge previews. Publication (including partial
    publication), or a refresh passed as ``published=True``, also invalidates
    displayed experience results and the two active UI A2A context IDs.
    """
    state.pop("knowledge_results", None)
    if published:
        for key in ("results", "a2a_baseline_context_id", "a2a_candidate_context_id"):
            state.pop(key, None)