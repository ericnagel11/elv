"""Streamlit app for the regional and multilingual experience proof of concept.

Proof of concept 001 showed that an assistant's voice and knowledge can be
configuration rather than code. This one adds the second axis. Four things are
demonstrated, and each is a control that a customer would ask about:

1. A market is a set of sparse configuration overrides, and every resolved value
   reports which layer supplied it. Inheritance is visible, not assumed.
2. Content answers in a market only when the human assurance behind its text
   meets what that market requires. The gate is configuration, and moving it is
   an approved, audited act.
3. Required notices reach the customer verbatim, because they are appended after
   generation and never pass through the model.
4. Azure cannot scope a data-plane role to a label, so it cannot enforce "may
   change only the German market". The governance tab says so and names the
   compensating control rather than implying otherwise.
"""

import os
import logging

import streamlit as st
from hosting import load_environment, vm_mode

import assets
import audit
import config as cfg
import drift
import knowledge
import language
import market
import rbac
from config import AccessDenied, CredentialError, endpoints_summary
from prompt import generate_response

# A denied request returns an error body that is not JSON, which makes the Azure
# SDK log a noisy "failsafe deserialization" warning with a traceback. The SDK
# ignores it and still raises HttpResponseError with the status code, so the
# denials this demo relies on are unaffected. Errors are still shown.
logging.getLogger("azure.appconfiguration").setLevel(logging.ERROR)

# Hosted settings are authoritative; VM mode never reads a checkout's .env.
load_environment()

st.set_page_config(page_title="Regional and Multilingual Experience PoC", layout="wide")

REQUIRED_ENV = ["AZURE_APPCONFIG_ENDPOINT", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"]

# The grounded asset. Configuration names a behavior version and never a locale,
# because locale is a resolution step handled in prompt.py.
GROUNDED_ASSET = "response:v3"

QUESTIONS = {
    "de-DE": "Wie lange habe ich Zeit, etwas zurückzugeben?",
    "es-MX": "¿Cuánto tiempo tengo para devolver algo?",
    "en-US": "How long do I have to return something?",
}
COMPARISON_QUESTION = "How long do I have to return something, and who pays for the return?"


@st.cache_data(show_spinner=False)
def cached_layer(label: str, store: str, persona: str, prefix: str) -> dict:
    return cfg.load_profile(label, store, persona, prefix=prefix)


def clear_caches() -> None:
    cached_layer.clear()


def resolve_market(locale: str, store: str, persona: str, with_candidate: bool = False) -> dict:
    """Resolve every layer for a market through the cached single-layer reader.

    The resolution order lives in market.py. This only supplies the reader, so a
    demo does not re-query App Configuration on every Streamlit rerun.
    """
    return market.resolve_all(locale, store, persona, with_candidate, reader=cached_layer)


def split_prefixes(resolved: dict) -> dict:
    """Flat values grouped by prefix, with the prefix stripped."""
    groups = {prefix: {} for prefix in market.PREFIXES}
    for key, entry in resolved.items():
        for prefix in market.PREFIXES:
            if key.startswith(prefix):
                groups[prefix][key[len(prefix):]] = entry["value"]
                break
    return groups


def answer_for_market(locale: str, question: str, persona: str, store: str = "production",
                      with_candidate: bool = False, gate_override: str = "") -> dict:
    """Produce one market's answer end to end.

    The order matters and is the design. Retrieval is scoped before generation,
    so the model never sees another market's policy. The disclosure is resolved
    before generation too, so a missing notice stops the request rather than
    producing an answer that is then found to be non-compliant.
    """
    resolved = resolve_market(locale, store, persona, with_candidate)
    groups = split_prefixes(resolved)
    experience = groups[cfg.EXPERIENCE_PREFIX]
    market_cfg = groups[cfg.MARKET_PREFIX]
    scope = knowledge.settings_from_profile(groups[cfg.KNOWLEDGE_PREFIX])
    if gate_override:
        scope["translation_gate"] = gate_override

    # Resolved before generation on purpose. An answer without a required notice
    # is worse than no answer, so this raises rather than warns.
    disclosure = assets.load_disclosure(market_cfg.get("disclosure_set", ""))
    glossary = assets.load_glossary(market_cfg.get("glossary_asset", ""))

    found = {"documents": [], "notes": [], "index": scope.get("index", ""), "filter": ""}
    if knowledge.is_enabled(scope) and knowledge.configured():
        found = knowledge.search(question, scope, persona)

    inputs = {key: value for key, value in experience.items() if key != "prompt_asset"}
    inputs.update({
        "user_message": question,
        "jurisdiction": market_cfg.get("jurisdiction", ""),
        "citation_style": scope.get("citation_style", "inline"),
        "glossary": glossary,
        "context": knowledge.format_context(found["documents"], scope.get("citation_style")),
    })

    result = generate_response(
        experience.get("prompt_asset", GROUNDED_ASSET),
        inputs,
        locale=locale,
        language=market.language_of(locale),
    )

    verdict = language.check(
        result["text"],
        market_cfg.get("language", market.language_of(locale)),
        language.mode_of(market_cfg),
    )

    if verdict["suppress"]:
        delivered = (
            "This market is configured to withhold an answer that is not in the "
            "expected language. The customer would be handed off to "
            f"`{market_cfg.get('escalation_path', 'the market escalation path')}`."
        )
    else:
        delivered = assets.append_disclosure(result["text"], disclosure)

    return {
        "locale": locale,
        "resolved": resolved,
        "experience": experience,
        "market": market_cfg,
        "scope": scope,
        "found": found,
        "disclosure": disclosure,
        "glossary": glossary,
        "result": result,
        "verdict": verdict,
        "delivered": delivered,
    }


def render_answer(container, bundle: dict, show_provenance: bool = True) -> None:
    locale = bundle["locale"]
    documents = bundle["found"]["documents"]
    loosened = knowledge.below_certified(documents)

    with container:
        st.subheader(market.display(locale))
        st.caption(
            f"`{locale}` | jurisdiction `{bundle['market'].get('jurisdiction', 'n/a')}` | "
            f"gate `{knowledge.gate_of(bundle['scope'])}` | asset `{bundle['result']['asset']}`"
        )

        for note in bundle["found"]["notes"]:
            st.info(note)

        verdict = bundle["verdict"]
        if verdict["status"] == "mismatch":
            st.error(verdict["message"])
        elif verdict["status"] == "match":
            st.success(verdict["message"])
        elif verdict["status"] in ("unavailable", "inconclusive"):
            st.caption(verdict["message"])

        if loosened:
            st.warning(
                f"{len(loosened)} document(s) below the certified level reached this "
                "answer: "
                + ", ".join(sorted({f"{d['title']} ({d['translation_status']})" for d in loosened}))
                + ". That is the consequence of this market's configured gate."
            )

        st.markdown(bundle["delivered"])

        if bundle["disclosure"]["text"]:
            with st.expander(f"Required notice, delivered verbatim ({bundle['disclosure']['path']})"):
                st.caption(
                    "Appended after generation. The model never saw this text, which "
                    "is what guarantees it arrived exactly as legal approved it."
                )
                st.code(bundle["disclosure"]["text"], language="markdown")
        else:
            st.caption("No notice is required in this jurisdiction.")

        with st.expander(f"Sources retrieved ({len(documents)})"):
            if documents:
                st.table([
                    {
                        "n": str(position),
                        "document": item["title"],
                        "language": item["language"] or "n/a",
                        "jurisdiction": item["jurisdiction"] or "n/a",
                        "review level": item["translation_status"] or "n/a",
                        "score": str(round(item["reranker_score"] or item["score"] or 0, 3)),
                    }
                    for position, item in enumerate(documents, start=1)
                ])
            else:
                st.caption("Nothing met this market's scope.")
            st.code(f"filter = {bundle['found'].get('filter') or '(none)'}", language="text")

        with st.expander("Prompt asset resolution"):
            st.caption(
                "Configuration names a behavior version. The locale is resolved here, "
                "most specific first, so a silent fallback to the neutral asset is visible."
            )
            st.table(bundle["result"]["asset_attempts"])

        if show_provenance:
            with st.expander("Resolved configuration, and which layer supplied it"):
                st.table(market.provenance_rows(bundle["resolved"]))


def show_denied(problem, persona: str) -> None:
    """Render an authorization denial or a sign-in failure.

    These look alike in the UI but mean different things. A denial is the demo
    working; a sign-in failure means the identity's secret is stale.
    """
    if isinstance(problem, CredentialError):
        st.error(
            f"Could not sign in as {rbac.PERSONAS[persona]['label']}. This is an "
            "authentication failure, not an RBAC denial."
        )
        with st.expander("Azure response"):
            st.code(problem.detail or "Unauthorized", language="text")
        st.caption(
            "Check the configured identity and its authentication status. In VM mode, "
            "verify managed identity attachment and client IDs; do not reissue secrets "
            "or rerun provisioning scripts against shared resources."
        )
        return

    st.error(
        f"Denied by Azure RBAC. {rbac.PERSONAS[persona]['label']} may not "
        f"{problem.operation} on the {problem.store} store."
    )
    with st.expander("Azure response"):
        st.code(problem.detail or "403 Forbidden", language="text")
    st.caption(
        "Role assignments can take up to 15 minutes to propagate after setup, "
        "so an unexpected denial soon after provisioning may simply be timing."
    )


missing = [key for key in REQUIRED_ENV if not os.environ.get(key)]
if missing:
    st.error(
        "Missing environment variables: "
        + ", ".join(missing)
        + ". Copy .env.example to .env and fill in the endpoints, or run scripts/setup.ps1."
    )
    st.stop()


with st.sidebar:
    st.header("Acting as")
    persona = st.radio(
        "Identity",
        options=list(rbac.PERSONAS.keys()),
        format_func=lambda key: rbac.PERSONAS[key]["label"],
        index=list(rbac.PERSONAS).index(rbac.DEFAULT_PERSONA),
        label_visibility="collapsed",
    )
    st.caption(rbac.PERSONAS[persona]["summary"])
    st.caption(f"Azure identity: {rbac.display_name(persona)}")
    if vm_mode():
        st.info("Presenter-only demo. Persona switching is not user authentication.")
    st.table(rbac.role_rows(persona))
    if rbac.PERSONAS[persona]["scope_note"]:
        st.warning(rbac.PERSONAS[persona]["scope_note"])

    if not rbac.personas_configured():
        st.warning(
            "Service principals are not provisioned, so every action runs as your "
            "own sign-in. Run scripts/setup-governance.ps1 to enforce these roles."
        )
    for problem in rbac.credential_warnings():
        st.error(problem)

    st.divider()
    st.header("Market")
    active_market = st.selectbox(
        "Market",
        options=list(market.MARKETS.keys()),
        format_func=market.display,
        index=list(market.MARKETS).index(market.DEFAULT_MARKET),
        label_visibility="collapsed",
    )
    st.caption(market.MARKETS[active_market]["summary"])

    st.divider()
    if st.button("Refresh configuration from Azure", use_container_width=True):
        clear_caches()
        st.rerun()
    with st.expander("Endpoints"):
        st.table([{"setting": k, "value": v} for k, v in endpoints_summary().items()])


st.title("One assistant, three markets, no code branch")

tab_market, tab_compare, tab_gate, tab_inherit, tab_governance, tab_audit = st.tabs([
    "Market experience",
    "Market comparison",
    "Certification gate",
    "Inheritance",
    "Governance and RBAC",
    "Audit trail",
])


with tab_market:
    st.markdown(
        "A market is a **sparse set of overrides** on top of the global default. "
        "Everything below was resolved from Azure App Configuration at request time: "
        "the register, the retrieval scope, the required notice, and the prompt asset. "
        "Nothing about this market lives in the application."
    )

    question = st.text_area(
        "Customer question",
        value=QUESTIONS.get(active_market, COMPARISON_QUESTION),
        height=80,
    )

    if st.button("Answer for this market", type="primary"):
        try:
            with st.spinner(f"Resolving {active_market} and calling Azure OpenAI..."):
                st.session_state["market_answer"] = answer_for_market(
                    active_market, question, persona
                )
        except (AccessDenied, CredentialError) as denied:
            show_denied(denied, persona)
        except assets.DisclosureMissing as gap:
            st.error(str(gap))
            st.caption(
                "This is the intended behavior. A market that requires a notice and "
                "cannot produce it must not answer."
            )
        except FileNotFoundError as gap:
            st.error(str(gap))

    bundle = st.session_state.get("market_answer")
    if bundle:
        render_answer(st.container(), bundle)


with tab_compare:
    st.markdown(
        "The same question, asked in every market. The answers differ in **language**, "
        "in **register**, and in **substance**, and only the third one matters most. "
        "A German customer is not owed the American answer in German: the statutory "
        "withdrawal right that applies to them is not the commercial return window "
        "that applies in the United States. Translation alone would have carried the "
        "wrong fact across the border in perfect grammar."
    )
    st.caption(
        "Each column resolves its own market layer, retrieves from its own "
        "language index under its own jurisdiction filter, and renders its own "
        "prompt asset. The application code is identical for all three."
    )

    compare_question = st.text_area(
        "Question, asked in every market",
        value=COMPARISON_QUESTION,
        height=70,
        key="compare_question",
    )

    if st.button("Compare all markets", type="primary"):
        answers, failures = {}, {}
        with st.spinner("Resolving three markets..."):
            for locale in market.MARKETS:
                try:
                    answers[locale] = answer_for_market(locale, compare_question, persona)
                except (AccessDenied, CredentialError) as denied:
                    failures[locale] = denied
                except (assets.DisclosureMissing, FileNotFoundError) as gap:
                    failures[locale] = gap
        st.session_state["comparison"] = {"answers": answers, "failures": failures}

    comparison = st.session_state.get("comparison")
    if comparison:
        for locale, problem in comparison["failures"].items():
            if isinstance(problem, (AccessDenied, CredentialError)):
                show_denied(problem, persona)
            else:
                st.error(f"{market.display(locale)}: {problem}")

        answers = comparison["answers"]
        if answers:
            columns = st.columns(len(answers))
            for column, (locale, item) in zip(columns, answers.items()):
                render_answer(column, item, show_provenance=False)

            st.divider()
            st.markdown("**What differed, and where it came from**")
            st.table([
                {
                    "market": locale,
                    "prompt asset": item["result"]["asset"],
                    "formality": item["experience"].get("formality", "(inherited)"),
                    "index": item["scope"].get("index", ""),
                    "gate": knowledge.gate_of(item["scope"]),
                    "notice": item["disclosure"]["path"] or "none required",
                    "sources used": str(len(item["found"]["documents"])),
                }
                for locale, item in answers.items()
            ])


with tab_gate:
    st.markdown(
        "A document answers in a market only when the human assurance behind its "
        "text meets what that market requires. `knowledge:translation_gate` is that "
        "requirement, and it is configuration like any other. This is the same "
        "mechanism proof of concept 001 used for `status eq 'approved'`, with one "
        "more dimension."
    )

    if not knowledge.configured():
        st.info(
            "The knowledge layer is not provisioned. Run "
            "`pwsh scripts/setup-knowledge.ps1 -ProductionStore <your-appcfg-name>`, "
            "re-run `scripts/seed-config.ps1`, then restart the app."
        )
    else:
        st.table([
            {"gate": gate, "admits": ", ".join(levels)}
            for gate, levels in knowledge.GATE_ALLOWS.items()
        ])

        gate_question = st.text_area(
            "Question",
            value=QUESTIONS.get(active_market, COMPARISON_QUESTION),
            height=70,
            key="gate_question",
        )
        loosened_gate = st.selectbox(
            "Compare the market's configured gate against",
            options=list(knowledge.GATE_ALLOWS.keys()),
            index=list(knowledge.GATE_ALLOWS).index("machine_allowed"),
        )

        if st.button("Compare gates", type="primary"):
            try:
                with st.spinner("Retrieving under both gates..."):
                    st.session_state["gate_results"] = {
                        "configured": answer_for_market(active_market, gate_question, persona),
                        "loosened": answer_for_market(
                            active_market, gate_question, persona,
                            gate_override=loosened_gate,
                        ),
                    }
            except (AccessDenied, CredentialError) as denied:
                show_denied(denied, persona)
            except (assets.DisclosureMissing, FileNotFoundError) as gap:
                st.error(str(gap))

        gate_results = st.session_state.get("gate_results")
        if gate_results:
            left, right = st.columns(2)
            render_answer(left, gate_results["configured"], show_provenance=False)
            render_answer(right, gate_results["loosened"], show_provenance=False)
            st.divider()
            st.markdown(
                "Nothing about the content, the index, the prompt asset, or the code "
                "changed between these two columns. One configuration value moved. "
                "This is the class of change the approval gate exists to catch, and it "
                "is why a scope change needs an evaluation set rather than a reading of "
                "the diff: a looser gate produces a fluent, confident, unreviewed answer."
            )

    st.divider()
    st.subheader("Translation drift")
    st.markdown(
        "Localized content has a failure mode that English-only content does not. "
        "When a source document is revised, its certified translations stay "
        "certified. They are certified against a version that no longer exists, and "
        "nothing in their approval state records that. Recording the source and its "
        "version at translation time turns an inspection into a report."
    )
    summary = drift.summary()
    columns = st.columns(len(summary))
    for column, (title, value) in zip(columns, summary.items()):
        column.metric(title, value)
    rows = drift.report()
    if rows:
        st.table(rows)
    else:
        st.caption("No derived documents are registered, so nothing can drift.")
    st.caption(
        "Detecting drift is the easy half. Resourcing the re-certification it "
        "triggers is the real cost, and it scales with every market added."
    )


with tab_inherit:
    st.markdown(
        "Sparse overrides are what keep the cost of a market close to the cost of its "
        "content. They are also how an unreviewed change reaches a regulated market: a "
        "key that a market does not override is a key it inherits, so editing the "
        "global default reaches those customers without a market reviewer seeing it. "
        "That is usually the intent and occasionally a serious problem, which is why "
        "it belongs on screen **before** publishing rather than in a postmortem."
    )

    prefix_choice = st.selectbox(
        "Prefix",
        options=list(market.PREFIXES),
        format_func=lambda value: value.rstrip(":"),
    )
    key_options = {
        cfg.EXPERIENCE_PREFIX: cfg.EDITABLE_KEYS,
        cfg.MARKET_PREFIX: market.EDITABLE_MARKET_KEYS,
        cfg.KNOWLEDGE_PREFIX: cfg.EDITABLE_KNOWLEDGE_KEYS,
    }[prefix_choice]
    key_choice = st.selectbox("Key", options=key_options)

    if st.button("Show blast radius", type="primary"):
        try:
            with st.spinner("Reading every market layer..."):
                blast = market.inheritors(
                    prefix_choice, key_choice, "production", persona, reader=cached_layer
                )
                blast["key"] = f"{prefix_choice}{key_choice}"
                st.session_state["blast"] = blast
        except (AccessDenied, CredentialError) as denied:
            show_denied(denied, persona)

    blast = st.session_state.get("blast")
    if blast:
        st.subheader(f"Changing `{blast['key']}` on the `{market.GLOBAL_LAYER}` layer")
        if blast["inherits"]:
            st.warning(
                f"{len(blast['inherits'])} market(s) inherit this key and would receive "
                "the change without a market review: "
                + ", ".join(f"`{locale}`" for locale in blast["inherits"])
            )
        else:
            st.success(
                "Every market overrides this key, so a change to the global default "
                "would reach no customer."
            )
        if blast["overrides"]:
            st.caption("Markets that override this key, and are therefore unaffected:")
            st.table(blast["overrides"])


with tab_governance:
    st.markdown(
        "Changes flow **draft store to production store**, exactly as in proof of "
        "concept 001. A market owner proposes changes to their market's layer and an "
        "approver publishes that layer, without touching `baseline` or any other market."
    )

    st.subheader("The limit worth stating plainly")
    st.markdown(
        "Because a market **is** a label, the rule an organization actually wants is "
        "*this team may change only the de-DE market*. **Azure cannot express it.** "
        "Role assignment conditions are available for blob storage and queue storage "
        "data actions, not for App Configuration, so a data-plane role cannot be "
        "narrowed to a label. The market owner persona in the sidebar therefore holds "
        "exactly the same permissions as the global designer. Run the permission check "
        "below for one market, then switch markets and run it again: the answers are "
        "identical, which is the limitation made visible rather than described."
    )
    with st.expander("What delivers per-market delegation, since RBAC does not"):
        st.table(rbac.COMPENSATING_CONTROLS)

    if not cfg.draft_configured():
        st.info(
            "The draft store is not provisioned yet. Run "
            "`pwsh scripts/setup-governance.ps1 -ProductionStore <store-name>`."
        )
    else:
        st.divider()
        st.subheader(f"What this identity may do to the `{active_market}` layer")
        st.caption(
            "Each check calls Azure. Write checks rewrite an existing value "
            "unchanged, so they prove permission without altering configuration."
        )
        if st.button("Run permission check", type="primary"):
            with st.spinner("Asking Azure..."):
                st.session_state["probe"] = {
                    "persona": persona,
                    "market": active_market,
                    "results": cfg.probe(persona, active_market),
                }

        probe_state = st.session_state.get("probe")
        if probe_state:
            st.caption(
                f"Result for {rbac.PERSONAS[probe_state['persona']]['label']} "
                f"on the `{probe_state['market']}` layer"
            )
            st.table([
                {"operation": row["operation"], "result": row["outcome"]}
                for row in probe_state["results"]
            ])

        st.divider()
        st.subheader(f"Edit the draft `{active_market}` layer")
        st.caption(
            "Editing a market layer creates an override. Deleting one returns the "
            "market to the global default, which is a governed act in its own right."
        )

        saved = st.session_state.pop("draft_saved", None)
        if saved:
            st.success(
                f"Saved to the draft store: `{saved}`. Customers in this market see "
                "no change until an approver publishes the layer."
            )

        edit_prefix = st.selectbox(
            "Prefix",
            options=list(market.PREFIXES),
            format_func=lambda value: value.rstrip(":"),
            key="edit_prefix",
        )
        edit_keys = {
            cfg.EXPERIENCE_PREFIX: cfg.EDITABLE_KEYS,
            cfg.MARKET_PREFIX: market.EDITABLE_MARKET_KEYS,
            cfg.KNOWLEDGE_PREFIX: cfg.EDITABLE_KNOWLEDGE_KEYS,
        }[edit_prefix]
        edit_key = st.selectbox("Key", options=edit_keys, key="edit_key")

        try:
            draft_layer = cached_layer(active_market, "draft", persona, edit_prefix)
        except (AccessDenied, CredentialError) as denied:
            draft_layer = None
            show_denied(denied, persona)

        if draft_layer is not None:
            current = draft_layer.get(edit_key, "")
            if not current:
                st.caption(
                    "This market does not override this key today, so it inherits the "
                    "global default. Saving a value here creates an override."
                )
            new_value = st.text_input("Value", value=current)
            save_column, delete_column = st.columns(2)
            if save_column.button("Save override to draft", use_container_width=True):
                try:
                    cfg.set_value(edit_key, new_value, label=active_market,
                                  store="draft", persona=persona, prefix=edit_prefix)
                    clear_caches()
                    st.session_state["draft_saved"] = f"{edit_prefix}{edit_key}"
                    st.rerun()
                except (AccessDenied, CredentialError) as denied:
                    show_denied(denied, persona)
            if delete_column.button("Remove override (inherit again)", use_container_width=True):
                try:
                    cfg.delete_value(edit_key, label=active_market, store="draft",
                                     persona=persona, prefix=edit_prefix)
                    clear_caches()
                    st.session_state["draft_saved"] = f"{edit_prefix}{edit_key} (removed)"
                    st.rerun()
                except (AccessDenied, CredentialError) as denied:
                    show_denied(denied, persona)

            try:
                pending = cfg.pending_changes(active_market, persona)
                if pending:
                    st.warning(f"{len(pending)} change(s) not yet published for this market.")
                    st.table(pending)
                else:
                    st.info("The draft and production layers match for this market.")
            except (AccessDenied, CredentialError):
                st.caption("This identity cannot read both stores, so no diff is shown.")

        st.divider()
        st.subheader(f"Publish the `{active_market}` layer to production")
        st.caption(
            "Publishing is per layer because a layer is what a reviewer approves. "
            "Only the release approver holds Data Owner on production."
        )
        if st.button("Publish this market to production"):
            try:
                published = cfg.publish_layer(active_market, persona=persona)
                clear_caches()
                st.success(
                    f"Published {len(published)} settings for {active_market}. "
                    "Regenerate on the Market experience tab to see the change."
                )
            except (AccessDenied, CredentialError) as denied:
                show_denied(denied, persona)
            except RuntimeError as exc:
                st.error(str(exc))


with tab_audit:
    st.markdown(
        "Enforcement answers who may change a market. Auditing answers who did. "
        "Because a market is a label and the certification gate is a key, a change "
        "to what a market may draw on appears in `AACAudit` like any other write."
    )

    if not audit.workspace_configured():
        st.info("Run scripts/setup-governance.ps1 to create the Log Analytics workspace.")
    else:
        st.caption(
            "Queries use the dedicated audit identity and live/draft resource scope."
            if vm_mode() else "Queries run under your own sign-in, not the selected persona."
        )
        col_a, col_b, col_c = st.columns(3)
        if col_a.button("Who changed what", use_container_width=True):
            st.session_state["audit"] = ("Configuration changes", audit.CHANGES_QUERY)
        if col_b.button("Gate and notice changes", use_container_width=True):
            st.session_state["audit"] = (
                "Changes to certification gates and required notices", audit.GATE_QUERY
            )
        if col_c.button("Denied attempts (403)", use_container_width=True):
            st.session_state["audit"] = ("Denied attempts", audit.DENIED_QUERY)

        selection = st.session_state.get("audit")
        if selection:
            title, query = selection
            st.subheader(title)
            with st.expander("KQL"):
                st.code(query.strip(), language="kusto")
            try:
                with st.spinner("Querying Log Analytics..."):
                    columns, rows = audit.run_query(query)
                if rows:
                    # Cast to text so mixed column types render reliably.
                    st.dataframe(
                        [{c: str(v) for c, v in zip(columns, row)} for row in rows],
                        use_container_width=True,
                    )
                else:
                    st.info(
                        "No rows yet. Log ingestion typically lags a few minutes "
                        "behind the activity that produced it."
                    )
            except Exception as exc:
                st.error(f"The query failed: {exc}")
