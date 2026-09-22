"""Offline form tests using a strict Streamlit-1.36-compatible API stub.

The stub deliberately allows invalid submitted widget values to exercise the
validation boundary independently of browser-side widget constraints. No app,
Streamlit server, credentials, SDK client, or network connection is needed.
"""

from contextlib import contextmanager
from copy import deepcopy
import unittest

from config_editor import render_search_form, reset_results
from search_settings import DEFAULTS


IDENTITY = "designer:draft:candidate:revision-1"
PREFIX = f"{IDENTITY}:search"
FIELD_KINDS = {
    "enabled": "toggle", "index": "text_input", "filter": "text_area",
    "top_k": "number_input", "query_mode": "selectbox", "citation_style": "selectbox",
}


class StreamlitStub:
    def __init__(self, *, values=None, submitted=False):
        self.values = dict(values or {})
        self.submitted = submitted
        self.controls = {}
        self.forms = {}
        self.submit_buttons = []
        self.captions = []
        self.warnings = []
        self.errors = []
        self.infos = []
        self.active_form = None

    @contextmanager
    def form(self, key, clear_on_submit=False):
        if key in self.forms or self.active_form is not None:
            raise AssertionError("Duplicate or nested form")
        self.forms[key] = {"clear_on_submit": clear_on_submit}
        self.active_form = key
        try:
            yield self
        finally:
            self.active_form = None

    def _control(self, kind, label, value, key, disabled, **properties):
        if self.active_form is None or key in self.controls:
            raise AssertionError("Control outside form or duplicate widget key")
        self.controls[key] = {
            "kind": kind, "label": label, "initial": value,
            "value": self.values.get(key, value), "disabled": disabled,
            "form": self.active_form, **properties,
        }
        return self.controls[key]["value"]

    def toggle(self, label, *, value=False, key=None, disabled=False):
        return self._control("toggle", label, value, key, disabled)

    def text_input(self, label, *, value="", key=None, disabled=False, help=None):
        return self._control("text_input", label, value, key, disabled, help=help)

    def text_area(self, label, *, value="", height=None, key=None, disabled=False, help=None):
        return self._control("text_area", label, value, key, disabled, height=height, help=help)

    def number_input(self, label, *, min_value, max_value, value, step, key=None, disabled=False):
        return self._control("number_input", label, value, key, disabled,
                             min_value=min_value, max_value=max_value, step=step)

    def selectbox(self, label, options, *, index=0, key=None, disabled=False, help=None):
        return self._control("selectbox", label, options[index] if index is not None else None, key, disabled,
                             options=tuple(options), help=help)

    def checkbox(self, label, *, value=False, key=None, disabled=False):
        return self._control("checkbox", label, value, key, disabled)

    def form_submit_button(self, label, *, disabled=False):
        # No key parameter: it is not part of the Streamlit 1.36 signature.
        if self.active_form is None:
            raise AssertionError("Submit button outside form")
        self.submit_buttons.append({"label": label, "disabled": disabled, "form": self.active_form})
        # Even a spurious submitted=True must be ignored for a disabled form.
        return self.submitted

    def caption(self, body):
        self.captions.append(body)

    def warning(self, body):
        self.warnings.append(body)

    def error(self, body):
        self.errors.append(body)

    def info(self, body):
        self.infos.append(body)


class SearchFormTests(unittest.TestCase):
    def render(self, scope=None, *, values=None, submitted=False, editable=True, widget_key=IDENTITY):
        st = StreamlitStub(values=values, submitted=submitted)
        result = render_search_form(st, {} if scope is None else scope,
                                    editable=editable, widget_key=widget_key)
        return st, result

    def assert_all_controls(self, st, *, editable=True, prefix=PREFIX):
        for field, kind in FIELD_KINDS.items():
            control = st.controls[f"{prefix}:{field}"]
            self.assertEqual(control["kind"], kind)
            self.assertEqual(control["disabled"], not editable)
            self.assertEqual(control["form"], f"{prefix}:form")
            self.assertTrue(any(f"knowledge:{field} —" in text for text in st.captions))
        self.assertEqual(st.controls[f"{prefix}:ack_no_filter"]["disabled"], not editable)

    def test_all_six_visible_missing_partial_disabled_and_read_only(self):
        for scope in ({}, {"enabled": "false"}, dict(DEFAULTS)):
            for editable in (True, False):
                with self.subTest(scope=scope, editable=editable):
                    st, result = self.render(scope, editable=editable)
                    self.assertIsNone(result)
                    self.assert_all_controls(st, editable=editable)
                    self.assertEqual(len(st.controls), 7)
                    self.assertEqual(st.forms, {f"{PREFIX}:form": {"clear_on_submit": False}})
                    self.assertEqual(st.submit_buttons, [{
                        "label": "Save Search settings", "disabled": not editable,
                        "form": f"{PREFIX}:form",
                    }])
                    self.assertEqual(bool(st.infos), not editable)
                    for field in DEFAULTS:
                        caption = next(text for text in st.captions if f"knowledge:{field} —" in text)
                        self.assertIn("default", caption)
                        self.assertIn("Stored:" if field in scope else "Not stored", caption)
                    top = st.controls[f"{PREFIX}:top_k"]
                    self.assertEqual((top["min_value"], top["max_value"], top["step"]), (1, 20, 1))
                    self.assertEqual(st.controls[f"{PREFIX}:query_mode"]["options"], ("simple", "semantic"))
                    self.assertEqual(st.controls[f"{PREFIX}:citation_style"]["options"],
                                     ("inline", "footnote", "none"))

    def test_rerender_and_unsaved_edits_return_nothing_and_do_not_mutate(self):
        scope = {**DEFAULTS, "unrelated": {"keep": [1]}}
        original = deepcopy(scope)
        defaults = dict(DEFAULTS)
        for edits in ({}, {f"{PREFIX}:top_k": 15, f"{PREFIX}:filter": ""}):
            for _ in range(2):
                st, result = self.render(scope, values=edits)
                self.assertIsNone(result)
                self.assertEqual(st.errors, [])
                self.assertEqual(scope, original)
                self.assertEqual(DEFAULTS, defaults)

    def test_explicit_submission_returns_only_six_normalized_strings(self):
        expression = " \nname eq 'O''Brien'\n  and title eq 'Member \"A\"' \t"
        scope = {"unrelated": {"keep": [1]}}
        original = deepcopy(scope)
        edits = {
            "enabled": True, "index": " approved-index ", "filter": expression,
            "top_k": 20, "query_mode": "semantic", "citation_style": "footnote",
        }
        st, result = self.render(scope, values={f"{PREFIX}:{key}": value for key, value in edits.items()},
                                 submitted=True)
        self.assertEqual(st.errors, [])
        self.assertEqual(result, {
            "enabled": "true", "index": "approved-index", "filter": expression.strip(),
            "top_k": "20", "query_mode": "semantic", "citation_style": "footnote",
        })
        self.assertEqual(set(result), set(DEFAULTS))
        self.assertTrue(all(isinstance(value, str) for value in result.values()))
        result["index"] = "changed-return-only"
        self.assertEqual(scope, original)
        self.assertEqual(DEFAULTS["index"], "kb-current")

    def test_submitting_missing_scope_uses_defaults_without_mutating_them(self):
        _, result = self.render(submitted=True)
        self.assertEqual(result, DEFAULTS)
        self.assertIsNot(result, DEFAULTS)

    def test_filter_quotes_and_multiline_text_are_not_rewritten_or_parsed(self):
        for expression in (
            " \nname eq 'O''Brien'\n and title eq 'Member \"A\"' \t",
            "search.in(audience, 'member,support')",
            "not valid OData (",
        ):
            with self.subTest(expression=expression):
                st, result = self.render({"filter": expression})
                self.assertIsNone(result)
                self.assertEqual(st.controls[f"{PREFIX}:filter"]["initial"], expression)
                st, result = self.render({"filter": expression}, submitted=True)
                self.assertEqual(st.errors, [])
                self.assertEqual(result["filter"], expression.strip())

    def test_bad_submitted_values_are_rejected_before_a_result_is_returned(self):
        cases = (
            ("enabled", "maybe"), ("index", "Bad Index"), ("index", ""),
            ("filter", None), ("top_k", 0), ("top_k", 21), ("top_k", True),
            ("top_k", 3.0), ("top_k", "3.0"), ("top_k", "9" * 5000),
            ("query_mode", "vector"), ("citation_style", "link"),
        )
        for field, value in cases:
            with self.subTest(field=field, value=str(value)[:30]):
                st, result = self.render(values={f"{PREFIX}:{field}": value}, submitted=True)
                self.assertIsNone(result)
                self.assertTrue(st.errors)
                self.assert_all_controls(st)

    def test_blank_filter_requires_acknowledgement_for_stored_and_new_edits(self):
        for expression in ("", " \n\t "):
            for scope in ({}, {"filter": expression}):
                for acknowledged in (False, True):
                    with self.subTest(expression=expression, scope=scope, acknowledged=acknowledged):
                        st, result = self.render(scope, submitted=True, values={
                            f"{PREFIX}:filter": expression,
                            f"{PREFIX}:ack_no_filter": acknowledged,
                        })
                        if acknowledged:
                            self.assertEqual(result["filter"], "")
                            self.assertEqual(st.errors, [])
                        else:
                            self.assertIsNone(result)
                            self.assertIn("acknowledgement", " ".join(st.errors))

    def test_acknowledgement_is_visible_before_filter_edits_and_never_submits(self):
        st, result = self.render(values={f"{PREFIX}:ack_no_filter": True})
        self.assertIsNone(result)
        self.assertEqual(st.controls[f"{PREFIX}:ack_no_filter"]["kind"], "checkbox")
        self.assertFalse(st.controls[f"{PREFIX}:ack_no_filter"]["initial"])
        self.assertTrue(any("blank filter" in message for message in st.warnings))

    def test_disabled_form_never_returns_a_result_even_if_submission_is_reported(self):
        st, result = self.render(editable=False, submitted=True, values={
            f"{PREFIX}:enabled": True, f"{PREFIX}:filter": "", f"{PREFIX}:ack_no_filter": True,
        })
        self.assertIsNone(result)
        self.assert_all_controls(st, editable=False)
        self.assertTrue(st.submit_buttons[0]["disabled"])
        self.assertEqual(st.errors, [])

    def test_every_invalid_stored_field_is_listed_with_visible_fallbacks(self):
        scope = {"enabled": "maybe", "index": "Bad Index", "filter": None,
                 "top_k": "999", "query_mode": "vector", "citation_style": "link"}
        original = dict(scope)
        for editable in (True, False):
            with self.subTest(editable=editable):
                st, result = self.render(scope, editable=editable)
                self.assertIsNone(result)
                self.assert_all_controls(st, editable=editable)
                warning = next(text for text in st.warnings if "Existing invalid Search settings:" in text)
                for field, value in scope.items():
                    self.assertIn(f"knowledge:{field}", warning)
                    caption = next(text for text in st.captions if f"knowledge:{field} —" in text)
                    self.assertIn(f"Stored: {value!r}", caption)
                    self.assertIn("Invalid stored value:", caption)
                    self.assertIn("shown for correction" if field == "index" else "Widget fallback (not saved)",
                                  caption)
                for field, expected in {"enabled": False, "index": "Bad Index", "filter": DEFAULTS["filter"],
                                        "top_k": 3, "query_mode": "simple", "citation_style": "inline"}.items():
                    self.assertEqual(st.controls[f"{PREFIX}:{field}"]["initial"], expected)
                self.assertEqual(st.errors, [])
                self.assertEqual(scope, original)

    def test_invalid_existing_text_is_not_replaced_and_can_be_corrected(self):
        scope = {"index": "Bad Index", "top_k": "wrong", "query_mode": "unknown"}
        original = dict(scope)
        st, result = self.render(scope, submitted=True)
        self.assertIsNone(result)
        self.assertTrue(st.errors)
        st, result = self.render(scope, submitted=True, values={
            f"{PREFIX}:index": "corrected-index", f"{PREFIX}:top_k": 7,
            f"{PREFIX}:query_mode": "semantic",
        })
        self.assertEqual(result, {**DEFAULTS, "index": "corrected-index", "top_k": "7", "query_mode": "semantic"})
        self.assertEqual(st.errors, [])
        self.assertEqual(scope, original)

    def test_fallbacks_require_explicit_save_and_preserve_invalid_stored_values(self):
        scope = {"enabled": None, "index": None, "filter": None,
                 "top_k": True, "query_mode": "", "citation_style": " "}
        original = dict(scope)
        _, result = self.render(scope)
        self.assertIsNone(result)
        st, result = self.render(scope, submitted=True)
        self.assertEqual(result, DEFAULTS)
        self.assertTrue(any("widget fallbacks" in text for text in st.warnings))
        self.assertEqual(scope, original)

    def test_oversized_invalid_native_integer_has_a_safe_widget_fallback(self):
        scope = {"top_k": 10 ** 5000, "enabled": 10 ** 5000}
        st, result = self.render(scope)
        self.assertIsNone(result)
        self.assertEqual(st.controls[f"{PREFIX}:top_k"]["initial"], 3)
        self.assertFalse(st.controls[f"{PREFIX}:enabled"]["initial"])
        self.assertTrue(any("Existing invalid Search settings:" in text for text in st.warnings))

    def test_captions_distinguish_missing_from_explicit_empty_filter(self):
        missing, _ = self.render()
        empty, _ = self.render({"filter": ""})
        self.assertEqual(missing.controls[f"{PREFIX}:filter"]["initial"], DEFAULTS["filter"])
        self.assertEqual(empty.controls[f"{PREFIX}:filter"]["initial"], "")
        self.assertTrue(any("knowledge:filter — Not stored" in text for text in missing.captions))
        self.assertTrue(any("knowledge:filter — Stored: ''" in text for text in empty.captions))
        self.assertFalse(any("Existing invalid" in text for text in empty.warnings))

    def test_all_keys_include_caller_identity_and_revision_and_do_not_share_acknowledgement(self):
        st = StreamlitStub(values={f"{PREFIX}:ack_no_filter": True}, submitted=True)
        keys = (IDENTITY, "designer:draft:candidate:revision-2", "viewer:production:candidate:revision-1")
        for widget_key in keys:
            result = render_search_form(st, {"filter": ""}, editable=True, widget_key=widget_key)
            if widget_key == IDENTITY:
                self.assertEqual(result["filter"], "")
            else:
                self.assertIsNone(result)
            self.assert_all_controls(st, prefix=f"{widget_key}:search")
        self.assertEqual(set(st.forms), {f"{key}:search:form" for key in keys})
        self.assertEqual(set(st.controls), {
            f"{key}:search:{field}" for key in keys for field in (*DEFAULTS, "ack_no_filter")
        })
        self.assertEqual([button["form"] for button in st.submit_buttons], [f"{key}:search:form" for key in keys])


    def test_vm_form_limits_index_and_modes_without_changing_stored_settings(self):
        scope = {**DEFAULTS, "index": "medical-policies-vector", "filter": ""}
        original = dict(scope)
        st = StreamlitStub()
        result = render_search_form(st, scope, editable=True, widget_key=IDENTITY,
                                    index_options=("medical-policies-vector",), query_modes=("simple",))
        self.assertIsNone(result)
        self.assertEqual(st.controls[f"{PREFIX}:index"]["kind"], "selectbox")
        self.assertEqual(st.controls[f"{PREFIX}:index"]["options"], ("medical-policies-vector",))
        self.assertEqual(st.controls[f"{PREFIX}:query_mode"]["options"], ("simple",))
        self.assertEqual(st.controls[f"{PREFIX}:filter"]["initial"], "")
        self.assertEqual(scope, original)

    def test_vm_form_rejects_submitted_index_or_mode_outside_operator_choices(self):
        scope = {**DEFAULTS, "index": "medical-policies-vector"}
        for key, value in (("index", "other-index"), ("query_mode", "semantic")):
            st = StreamlitStub(values={f"{PREFIX}:{key}": value}, submitted=True)
            result = render_search_form(st, scope, editable=True, widget_key=IDENTITY,
                                        index_options=("medical-policies-vector",), query_modes=("simple",))
            self.assertIsNone(result)
            self.assertTrue(st.errors)

    def test_vm_unapproved_stored_index_requires_explicit_selection(self):
        scope = {**DEFAULTS, "index": "old-index", "query_mode": "semantic"}
        st = StreamlitStub(submitted=True)
        result = render_search_form(st, scope, editable=True, widget_key=IDENTITY,
                                    index_options=("medical-policies-vector",), query_modes=("simple",))
        self.assertIsNone(result)
        self.assertIsNone(st.controls[f"{PREFIX}:index"]["initial"])
        self.assertEqual(st.controls[f"{PREFIX}:query_mode"]["initial"], "simple")
        self.assertTrue(any("query_mode" in warning for warning in st.warnings))


class ResetResultsTests(unittest.TestCase):
    def state(self):
        return {"knowledge_results": ["preview"], "results": ["comparison"],
                "a2a_baseline_context_id": "baseline-1", "a2a_candidate_context_id": "candidate-1",
                "server_contexts": {"baseline-1": {"revision": "pinned"}},
                "other": {"keep": True}}

    def test_draft_save_only_discards_knowledge_results(self):
        state = self.state()
        expected = deepcopy(state)
        expected.pop("knowledge_results")
        self.assertIsNone(reset_results(state, published=False))
        self.assertEqual(state, expected)

    def test_publication_discards_results_and_ui_ids_not_server_contexts(self):
        state = self.state()
        server_contexts = state["server_contexts"]
        self.assertIsNone(reset_results(state, published=True))
        self.assertEqual(state, {"server_contexts": {"baseline-1": {"revision": "pinned"}},
                                 "other": {"keep": True}})
        self.assertIs(state["server_contexts"], server_contexts)

    def test_reset_is_idempotent_with_missing_keys(self):
        for published in (False, True):
            for state in ({}, {"other": "keep"}, {"a2a_candidate_context_id": "candidate-1"}):
                reset_results(state, published)
                expected = deepcopy(state)
                reset_results(state, published)
                self.assertEqual(state, expected)


if __name__ == "__main__":
    unittest.main()