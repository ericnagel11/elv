"""Offline contract tests; this module needs only the Python standard library."""

from copy import deepcopy
import unittest

from search_settings import DEFAULT_QUESTION, DEFAULTS, normalize_settings, validate_settings


class SearchSettingsTests(unittest.TestCase):
    def test_exact_defaults_and_question(self):
        self.assertEqual(DEFAULT_QUESTION,
            "I received a denial notice for my health insurance claim. How can I appeal it?")
        self.assertEqual(DEFAULTS, {
            "enabled": "false", "index": "kb-current",
            "filter": "industry eq 'healthcare' and status eq 'approved'",
            "top_k": "3", "query_mode": "simple", "citation_style": "inline",
        })
        self.assertEqual(validate_settings({}), DEFAULTS)
        self.assertEqual(normalize_settings(None), DEFAULTS)

    def test_presence_sensitive_filter_and_no_mutation(self):
        before = dict(DEFAULTS)
        for value in ("", "  \n\t"):
            profile = {"filter": value, "unknown": {"nested": 1}, "top_k": 5}
            original = deepcopy(profile)
            result = normalize_settings(profile)
            self.assertEqual(result["filter"], "")
            self.assertEqual(result["top_k"], "5")
            self.assertEqual(set(result), set(DEFAULTS))
            self.assertEqual(profile, original)
            result["index"] = "another-index"
        self.assertEqual(DEFAULTS, before)
        self.assertEqual(normalize_settings({})["filter"], before["filter"])
        self.assertEqual(normalize_settings({"filter": None})["filter"], before["filter"])

    def test_filter_is_text_not_locally_parsed_odata(self):
        for expression in ("", "  industry eq 'healthcare'\n and status eq 'approved'  ",
                           "not valid OData (", "search.in(audience, 'member,support')"):
            with self.subTest(expression=expression):
                self.assertEqual(validate_settings({"filter": expression})["filter"],
                                 expression.strip())
        for invalid in (None, False, 12, [], {}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_settings({"filter": invalid})

    def test_boolean_inputs_are_canonical_strings(self):
        for value in (True, 1, "true", " TRUE ", "Yes", "ON", "1"):
            self.assertEqual(validate_settings({"enabled": value})["enabled"], "true")
        for value in (False, 0, "false", " FALSE ", "No", "OFF", "0"):
            self.assertEqual(validate_settings({"enabled": value})["enabled"], "false")
        for value in ("maybe", "", None, 2, 1.0, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_settings({"enabled": value})

    def test_top_k_integer_range_and_normalization(self):
        for value in (1, 20, " 3 ", "03", "0003"):
            self.assertEqual(validate_settings({"top_k": value})["top_k"], str(int(value)))
        for value in (0, 21, -1, True, False, 3.0, "3.0", "1e1", "", None, "9" * 5000):
            with self.subTest(value=str(value)[:20]), self.assertRaises(ValueError):
                validate_settings({"top_k": value})

    def test_enums(self):
        for key, choices in {"query_mode": ("simple", "semantic"),
                             "citation_style": ("inline", "footnote", "none")}.items():
            for choice in choices:
                self.assertEqual(validate_settings({key: f" {choice.upper()} "})[key], choice)
            for invalid in ("unknown", "", None, True, 1):
                with self.subTest(key=key, invalid=invalid), self.assertRaises(ValueError):
                    validate_settings({key: invalid})

    def test_lexical_index_or_alias_validation_only(self):
        for name in ("kb-current", "medical-policies-vector", "idx_health", "a1", "a" * 128):
            self.assertEqual(validate_settings({"index": f" {name} "})["index"], name)
        for name in ("a", "a" * 129, "Upper", "-idx", "_idx", "idx--v1", "idx__v1",
                     "a/b", "a?key=secret", "a b", "https://example.test", "ümlaut", 12):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_settings({"index": name})

    def test_validation_does_not_mutate_and_never_echoes_values(self):
        profile = {"top_k": " 04 ", "query_mode": " SEMANTIC ", "filter": ""}
        original = dict(profile)
        defaults = dict(DEFAULTS)
        result = validate_settings(profile)
        self.assertEqual(result["top_k"], "4")
        self.assertEqual(profile, original)
        self.assertEqual(DEFAULTS, defaults)
        self.assertEqual(set(result), set(DEFAULTS))
        for key in ("index", "enabled", "top_k", "query_mode", "citation_style"):
            secret = "PRIVATE_INPUT_DO_NOT_ECHO"
            with self.subTest(key=key), self.assertRaises(ValueError) as caught:
                validate_settings({key: secret})
            self.assertNotIn(secret, str(caught.exception))
        for value in ([], "private input", 0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_settings(value)
        for key in ("top_k", "enabled"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "Search"):
                validate_settings({key: 10 ** 5000})

    def test_permissive_reader_does_not_hide_invalid_nonblank_settings(self):
        self.assertEqual(normalize_settings({"top_k": "bad"})["top_k"], "bad")
        self.assertEqual(normalize_settings({"index": " "})["index"], DEFAULTS["index"])
        with self.assertRaises(ValueError):
            validate_settings({"index": " "})


if __name__ == "__main__":
    unittest.main()