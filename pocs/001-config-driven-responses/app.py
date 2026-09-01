"""Streamlit app for the config-driven responses proof of concept.

Two things are demonstrated:

1. The assistant's wording is controlled entirely by Azure App Configuration and
   versioned Prompty assets, so it changes with no code release.
2. Who may change it is controlled by Azure RBAC. The app acts as one of four
   Microsoft Entra identities, and every allow or deny below is enforced by
   Azure, not by this code.
"""

import os
import csv
import logging
import datetime as dt

import streamlit as st
import textstat
from dotenv import load_dotenv

import audit
import config as cfg
import knowledge
import rbac
from a2a_client import A2AClientError, ConfiguredAgentClient
from config import AccessDenied, CredentialError, endpoints_summary, load_profile
from experience_runtime import GROUNDED_ASSET, run_grounded

# A denied request returns an error body that is not JSON, which makes the Azure
# SDK log a noisy "failsafe deserialization" warning with a traceback. The SDK
# ignores it and still raises HttpResponseError with the status code, so the
# denials this demo relies on are unaffected. Errors are still shown.
logging.getLogger("azure.appconfiguration").setLevel(logging.ERROR)

# utf-8-sig tolerates a UTF-8 BOM (Windows PowerShell 5.1 may add one); override
# lets an edited .env take effect on the next rerun.
load_dotenv(encoding="utf-8-sig", override=True)

st.set_page_config(page_title="Config-Driven Responses PoC", layout="wide")

FEEDBACK_PATH = os.path.join(os.path.dirname(__file__), "feedback.csv")
REQUIRED_ENV = ["AZURE_APPCONFIG_ENDPOINT", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"]
DEFAULT_MESSAGE = "Where is my order? It was supposed to arrive yesterday and I need it for a gift."

DEFAULT_QUESTION = "How long do I have to return something, and is there a fee?"


@st.cache_data(show_spinner=False)
def cached_profile(label: str, store: str, persona: str) -> dict:
    return load_profile(label, store, persona)


@st.cache_data(show_spinner=False)
def cached_knowledge(label: str, store: str, persona: str) -> dict:
    return cfg.load_knowledge(label, store, persona)


@st.cache_resource(show_spinner=False)
def configured_agent() -> ConfiguredAgentClient:
    return ConfiguredAgentClient()


def text_metrics(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        return {}
    return {
        "Words": textstat.lexicon_count(text, removepunct=True),
        "Sentences": textstat.sentence_count(text),
        "Reading ease (higher = easier)": round(textstat.flesch_reading_ease(text)),
        "Grade level": textstat.text_standard(text, float_output=False),
    }


def record_feedback(message: str, choice: str) -> None:
    is_new = not os.path.exists(FEEDBACK_PATH)
    with open(FEEDBACK_PATH, "a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if is_new:
            writer.writerow(["timestamp", "choice", "message"])
        writer.writerow([dt.datetime.now().isoformat(timespec="seconds"), choice, message])


def render_answer(result: dict) -> None:
    """Render the model's reply, or explain its absence.

    A reasoning model can spend its whole max_completion_tokens budget on hidden
    reasoning and return finish_reason "length" with no content. Rendering that
    as an empty string looks like the request was refused, so say what happened.
    """
    text = (result.get("text") or "").strip()
    if text:
        st.markdown(text)
        if result.get("finish_reason") == "length":
            st.warning(
                "The reply was cut off at the token limit. Raise "
                "`max_completion_tokens` in the prompt asset."
            )
        return

    if result.get("finish_reason") == "length":
        st.warning(
            "The model returned no visible text: it spent the entire "
            f"`max_completion_tokens` budget on reasoning "
            f"({result.get('reasoning_tokens') or result.get('completion_tokens')} "
            "reasoning tokens). This is a token budget limit, not a refusal and "
            "not a content filter. Raise `max_completion_tokens` or lower "
            "`reasoning_effort` in the prompt asset."
        )
    elif result.get("finish_reason") == "content_filter":
        st.error("Azure OpenAI content filtering suppressed the reply.")
    else:
        st.warning(
            "The model returned an empty reply "
            f"(finish_reason: {result.get('finish_reason') or 'unknown'})."
        )


def render_variant(column, title: str, profile: dict, result: dict) -> None:
    with column:
        st.subheader(title)
        provenance = result.get("a2a") or {}
        st.caption(
            f"Prompt asset: {provenance.get('prompt_asset') or profile.get('prompt_asset', 'n/a')}"
        )
        render_answer(result)

        metrics = text_metrics(result["text"])
        latency = result.get("latency_s")
        metrics["Latency (s)"] = round(latency, 2) if latency is not None else "n/a"
        metrics["Prompt tokens"] = result.get("prompt_tokens")
        metrics["Completion tokens"] = result.get("completion_tokens")
        metrics["of which reasoning"] = result.get("reasoning_tokens")
        with st.expander("Response metrics"):
            # Cast to str so the mixed int/str column renders (grade level is text).
            st.table([{"metric": k, "value": str(v)} for k, v in metrics.items()])

        with st.expander("Configuration applied"):
            st.table([{"setting": k, "value": v} for k, v in profile.items()])

        if provenance:
            with st.expander("A2A task provenance"):
                st.table(
                    [
                        {"field": key, "value": value}
                        for key, value in provenance.items()
                    ]
                )

        with st.expander("Rendered prompt (template + configuration)"):
            if result.get("messages"):
                for message in result["messages"]:
                    st.markdown(f"**{message['role']}**")
                    st.code(message["content"], language="markdown")
            else:
                st.caption(
                    "The rendered prompt is private inside the remote A2A agent. "
                    "Only the response artifact and safe provenance cross the boundary."
                )


def render_grounded(column, title: str, scope: dict, bundle: dict) -> None:
    documents = bundle["found"]["documents"]
    unapproved = [item for item in documents if item["status"] and item["status"] != "approved"]

    with column:
        st.subheader(title)
        st.code(f"knowledge:filter = {scope.get('filter') or '(no filter)'}", language="text")

        for note in bundle["found"]["notes"]:
            st.info(note)

        if unapproved:
            st.error(
                f"{len(unapproved)} unapproved document(s) reached the answer: "
                + ", ".join(sorted({item["title"] for item in unapproved}))
            )

        render_answer(bundle["result"])

        with st.expander(f"Sources retrieved ({len(documents)})"):
            if documents:
                st.table(
                    [
                        {
                            "n": str(position),
                            "document": item["title"],
                            "status": item["status"] or "n/a",
                            "industry": item["industry"] or "n/a",
                            "score": str(round(item["reranker_score"] or item["score"] or 0, 3)),
                        }
                        for position, item in enumerate(documents, start=1)
                    ]
                )
            else:
                st.caption("Nothing matched within this scope.")

        with st.expander("Retrieval configuration applied"):
            st.table([{"key": f"knowledge:{k}", "value": v} for k, v in sorted(scope.items())])

        with st.expander("Rendered prompt (template + retrieved context)"):
            for message in bundle["result"]["messages"]:
                st.markdown(f"**{message['role']}**")
                st.code(message["content"], language="markdown")


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
    st.caption(f"Service principal: {rbac.display_name(persona)}")
    st.table(rbac.role_rows(persona))

    if not rbac.personas_configured():
        st.warning(
            "Service principals are not provisioned, so every action runs as your "
            "own sign-in. Run scripts/setup-governance.ps1 to enforce these roles."
        )
    for problem in rbac.credential_warnings():
        st.error(problem)

    st.divider()
    st.header("Configuration control plane")
    if st.button("Refresh configuration from Azure", use_container_width=True):
        cached_profile.clear()
        cached_knowledge.clear()
        st.session_state.pop("a2a_baseline_context_id", None)
        st.session_state.pop("a2a_candidate_context_id", None)
        st.session_state.pop("results", None)
        st.rerun()
    with st.expander("Endpoints"):
        st.table([{"setting": k, "value": v} for k, v in endpoints_summary().items()])


def show_denied(problem) -> None:
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
            "The client secret in roles.local.json is probably stale. Re-run "
            "scripts/setup-governance.ps1 to reissue the credentials."
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


st.title("Configurable agent responses without a code release")

tab_experience, tab_knowledge, tab_governance, tab_audit = st.tabs(
    ["Experience comparison", "Knowledge scope", "Governance and RBAC", "Audit trail"]
)


with tab_experience:
    st.markdown(
        "This is what a customer would receive, read from the **production** store. "
        "Change the assistant's wording by editing **Azure App Configuration**, or "
        "point a profile at a different **prompt asset** (`response:v1` vs "
        "`response:v2`). Select **Refresh configuration from Azure**, then "
        "regenerate. No code change or redeploy is required."
    )
    st.caption(
        "Streamlit invokes the response runtime through A2A 1.0. Configuration, "
        "prompt rendering, Search filters, and model access stay inside the remote agent."
    )
    st.caption(
        "Edits made on the Governance tab go to the draft store and do not appear "
        "here until a release approver publishes them."
    )

    user_message = st.text_area("Customer message", value=DEFAULT_MESSAGE, height=90)

    if st.button("Generate side-by-side comparison", type="primary"):
        try:
            baseline_profile = cached_profile("baseline", "production", persona)
            candidate_profile = cached_profile("candidate", "production", persona)
            if not baseline_profile or not candidate_profile:
                st.error("One or both profiles are empty. Run scripts/seed-config.ps1 first.")
            else:
                with st.spinner("Creating two A2A response tasks..."):
                    client = configured_agent()
                    baseline = client.invoke(
                        user_message,
                        "baseline",
                        context_id=st.session_state.get("a2a_baseline_context_id"),
                    )
                    st.session_state["a2a_baseline_context_id"] = baseline["context_id"]
                    candidate = client.invoke(
                        user_message,
                        "candidate",
                        context_id=st.session_state.get("a2a_candidate_context_id"),
                    )
                    st.session_state["a2a_candidate_context_id"] = candidate["context_id"]
                    baseline_result = dict(baseline["result"])
                    baseline_result["a2a"] = {
                        "task_id": baseline["task_id"],
                        "context_id": baseline["context_id"],
                        "profile_slot": baseline["profile_slot"],
                        "configuration_revision": baseline["configuration_revision"],
                        "prompt_asset": baseline["prompt_asset"],
                    }
                    candidate_result = dict(candidate["result"])
                    candidate_result["a2a"] = {
                        "task_id": candidate["task_id"],
                        "context_id": candidate["context_id"],
                        "profile_slot": candidate["profile_slot"],
                        "configuration_revision": candidate["configuration_revision"],
                        "prompt_asset": candidate["prompt_asset"],
                    }
                    st.session_state["results"] = {
                        "message": user_message,
                        "baseline_profile": baseline_profile,
                        "candidate_profile": candidate_profile,
                        "baseline": baseline_result,
                        "candidate": candidate_result,
                    }
        except (AccessDenied, CredentialError) as denied:
            show_denied(denied)
        except A2AClientError as problem:
            st.error(f"The A2A response agent is unavailable: {problem}")
            st.caption("Start it with `python a2a_server.py`, then try again.")

    results = st.session_state.get("results")
    if results:
        left, right = st.columns(2)
        render_variant(left, "Baseline (current)", results["baseline_profile"], results["baseline"])
        render_variant(right, "Candidate (proposed)", results["candidate_profile"], results["candidate"])

        st.divider()
        st.markdown("**Which response better fits the desired experience?**")
        col_a, col_b, col_c = st.columns(3)
        if col_a.button("Baseline is better", use_container_width=True):
            record_feedback(results["message"], "baseline")
            st.success("Recorded: baseline")
        if col_b.button("About the same", use_container_width=True):
            record_feedback(results["message"], "tie")
            st.success("Recorded: tie")
        if col_c.button("Candidate is better", use_container_width=True):
            record_feedback(results["message"], "candidate")
            st.success("Recorded: candidate")
        st.caption(f"Preferences are appended to {os.path.basename(FEEDBACK_PATH)} as A/B evidence.")


with tab_knowledge:
    st.markdown(
        "What the assistant **knows** is configurable in the same way its wording is. "
        "Content owners publish documents to a governed Blob container, an **Azure AI "
        "Search** indexer keeps the index current with no code, and the `knowledge:*` "
        "keys in **Azure App Configuration** decide which of that content an answer "
        "may draw on."
    )
    st.caption(
        "Both columns use the same question, the same index, and the same prompt asset "
        f"(`{GROUNDED_ASSET}`). The only difference is one configuration value."
    )

    if not knowledge.configured():
        st.info(
            "The knowledge layer is not provisioned. Run "
            "`pwsh scripts/setup-knowledge.ps1 -ProductionStore <your-appcfg-name>`, "
            "re-run `scripts/seed-config.ps1`, then restart the app."
        )
    else:
        question = st.text_area("Customer question", value=DEFAULT_QUESTION, height=80)

        if st.button("Compare retrieval scopes", type="primary"):
            try:
                experience_profile = cached_profile("candidate", "production", persona)
                live_scope = knowledge.settings_from_profile(
                    cached_knowledge(cfg.DRAFT_LABEL, "production", persona)
                )
                proposed_scope = None
                if cfg.draft_configured():
                    proposed_scope = knowledge.settings_from_profile(
                        cached_knowledge(cfg.DRAFT_LABEL, "draft", persona)
                    )

                if not knowledge.is_enabled(live_scope):
                    st.warning(
                        "`knowledge:enabled` is false in the production store, so the "
                        "live answer is ungrounded."
                    )

                with st.spinner("Retrieving and generating..."):
                    st.session_state["knowledge_results"] = {
                        "question": question,
                        "live_scope": live_scope,
                        "live": run_grounded(experience_profile, live_scope, question, persona),
                        "proposed_scope": proposed_scope,
                        "proposed": (
                            run_grounded(experience_profile, proposed_scope, question, persona)
                            if proposed_scope
                            else None
                        ),
                    }
            except (AccessDenied, CredentialError) as denied:
                show_denied(denied)

        knowledge_results = st.session_state.get("knowledge_results")
        if knowledge_results:
            if knowledge_results["proposed"]:
                left, right = st.columns(2)
                render_grounded(
                    left, "Live scope (production)",
                    knowledge_results["live_scope"], knowledge_results["live"],
                )
                render_grounded(
                    right, "Proposed scope (draft, not published)",
                    knowledge_results["proposed_scope"], knowledge_results["proposed"],
                )
                st.divider()
                st.markdown(
                    "The proposed scope widens the filter to admit content marked "
                    "`draft`. Nothing about the content, the index, or the code changed. "
                    "This is the class of change the approval gate exists to catch, and "
                    "it is why a knowledge change needs an evaluation set rather than a "
                    "reading of the diff: a wider scope produces a fluent, confident, "
                    "wrong answer."
                )
            else:
                render_grounded(
                    st.container(), "Live scope (production)",
                    knowledge_results["live_scope"], knowledge_results["live"],
                )

        with st.expander("How freshness works, and the one setting that must be right on day one"):
            st.markdown(
                "- The indexer polls on a schedule. The shortest supported interval is "
                "**five minutes**, so this is near real time, not real time.\n"
                "- Change detection is incremental and automatic for Azure Storage, "
                "using blob `LastModified` timestamps, so a frequent schedule is cheap.\n"
                "- **Deletion detection is not automatic.** Deleting a blob does not "
                "remove it from the index. The soft-delete policy on the `IsDeleted` "
                "metadata flag must exist from the very first indexer run, because it "
                "is not retroactive. Documents deleted before the policy was added stay "
                "in the index permanently, and the only fix is a new index.\n"
                "- `scripts/setup-knowledge.ps1` configures that policy up front, which "
                "is the entire reason it is worth mentioning here."
            )


with tab_governance:
    st.markdown(
        "Messaging changes flow **draft store to production store**. The experience "
        "designer owns the draft, and only the release approver can publish it. "
        "Azure enforces this: separate stores are used because Azure does not "
        "support ABAC role-assignment conditions for App Configuration, so a role "
        "cannot be limited to a single label inside one store."
    )

    if not cfg.draft_configured():
        st.info(
            "The draft store is not provisioned yet. Run "
            "`pwsh scripts/setup-governance.ps1 -ProductionStore <store-name>`."
        )
    else:
        st.subheader("What this identity is actually allowed to do")
        st.caption(
            "Each check calls Azure. Write checks rewrite an existing value "
            "unchanged, so they prove permission without altering configuration."
        )
        if st.button("Run permission check", type="primary"):
            with st.spinner("Asking Azure..."):
                st.session_state["probe"] = {
                    "persona": persona,
                    "results": cfg.probe(persona),
                }

        probe_state = st.session_state.get("probe")
        if probe_state:
            st.caption(f"Result for {rbac.PERSONAS[probe_state['persona']]['label']}")
            st.table([
                {
                    "operation": row["operation"],
                    "result": ("Allowed" if row["allowed"]
                               else "Denied by Azure (403)" if row["allowed"] is False
                               else row["outcome"]),
                }
                for row in probe_state["results"]
            ])

        st.divider()
        st.subheader("Edit the draft configuration")
        st.caption(
            "Both the wording (`experience:*`) and the retrieval scope "
            "(`knowledge:*`) are governed by the same roles and the same gate."
        )

        saved_key = st.session_state.pop("draft_saved", None)
        if saved_key:
            st.success(
                f"Saved to the draft store: `{saved_key}`. This does not "
                "change what customers receive until it is published below."
            )

        try:
            draft_profile = cached_profile(cfg.DRAFT_LABEL, "draft", persona)
            draft_scope = cached_knowledge(cfg.DRAFT_LABEL, "draft", persona)
        except (AccessDenied, CredentialError) as denied:
            draft_profile = None
            draft_scope = {}
            show_denied(denied)

        if draft_profile is not None:
            draft_all = {f"{cfg.EXPERIENCE_PREFIX}{k}": v for k, v in draft_profile.items()}
            draft_all.update({f"{cfg.KNOWLEDGE_PREFIX}{k}": v for k, v in draft_scope.items()})

            if draft_all:
                st.table([{"setting": k, "value": v} for k, v in sorted(draft_all.items())])
            else:
                st.warning("The draft store has no keys. Run scripts/seed-config.ps1.")

            # Show what the draft would change if it were published.
            try:
                live_all = {
                    f"{cfg.EXPERIENCE_PREFIX}{k}": v
                    for k, v in cached_profile(cfg.DRAFT_LABEL, "production", persona).items()
                }
                live_all.update({
                    f"{cfg.KNOWLEDGE_PREFIX}{k}": v
                    for k, v in cached_knowledge(cfg.DRAFT_LABEL, "production", persona).items()
                })
            except (AccessDenied, CredentialError):
                live_all = None
            if live_all is not None and draft_all:
                pending = [
                    {
                        "setting": key,
                        "live in production": live_all.get(key, "(not set)"),
                        "waiting in draft": value,
                    }
                    for key, value in sorted(draft_all.items())
                    if live_all.get(key) != value
                ]
                if pending:
                    st.warning(f"{len(pending)} change(s) not yet published to production.")
                    st.table(pending)
                else:
                    st.info("The draft and production match. Nothing is waiting to be published.")

            editable = (
                [f"{cfg.EXPERIENCE_PREFIX}{k}" for k in cfg.EDITABLE_KEYS]
                + [f"{cfg.KNOWLEDGE_PREFIX}{k}" for k in cfg.EDITABLE_KNOWLEDGE_KEYS]
            )
            edit_key = st.selectbox("Setting", options=editable)
            prefix, _, short_key = edit_key.partition(":")
            prefix = f"{prefix}:"
            new_value = st.text_input("New value", value=draft_all.get(edit_key, ""))
            if st.button("Save to draft"):
                try:
                    cfg.set_value(short_key, new_value, store="draft", persona=persona,
                                  prefix=prefix)
                    cached_profile.clear()
                    cached_knowledge.clear()
                    st.session_state["draft_saved"] = edit_key
                    st.rerun()
                except (AccessDenied, CredentialError) as denied:
                    show_denied(denied)

        st.divider()
        st.subheader("Publish the draft to production")
        st.caption(
            "Copies every draft setting into the production candidate profile, which "
            "is what the Experience comparison tab reads. Only the release approver "
            "holds Data Owner on production."
        )
        if st.button("Publish to production"):
            try:
                published = cfg.publish_draft(persona=persona)
                cached_profile.clear()
                cached_knowledge.clear()
                st.success(
                    f"Published {len(published)} settings to production: {', '.join(published)}. "
                    "Regenerate on the Experience comparison tab to see the new wording."
                )
            except (AccessDenied, CredentialError) as denied:
                show_denied(denied)
            except RuntimeError as exc:
                st.error(str(exc))


with tab_audit:
    st.markdown(
        "Governance needs evidence as well as enforcement. App Configuration "
        "resource logs record data-plane activity in Log Analytics. `AACAudit` "
        "records writes with the caller identity, and `AACHttpRequest` records "
        "reads and writes with a status code, which is where a denied attempt "
        "appears. The Azure activity log covers control-plane operations only and "
        "does not capture key-value changes."
    )

    if not audit.workspace_configured():
        st.info("Run scripts/setup-governance.ps1 to create the Log Analytics workspace.")
    else:
        st.caption("Queries run under your own sign-in, not the selected persona.")
        col_left, col_right = st.columns(2)
        if col_left.button("Who changed what", use_container_width=True):
            st.session_state["audit"] = ("Configuration changes", audit.CHANGES_QUERY)
        if col_right.button("Denied attempts (403)", use_container_width=True):
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
