"""
Focused OFFLINE unit tests for app/gemini.py (Stage 3).

NOTE: this file is NOT the smoke script. That one lives at
backend/test_gemini.py and makes a real API call on purpose. These tests never
touch the network: ``call_gemini`` is always replaced with a stub, so no API
quota is spent. No real API key is needed either - a fake one is passed in.

Run with the project venv, from anywhere:

    backend\\venv\\Scripts\\python.exe backend\\tests\\test_gemini.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Make "from app import ..." work regardless of the current working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import gemini  # noqa: E402

# A deliberately fake secret. If it ever shows up in an error, redaction failed.
FAKE_SECRET = "AQ.FAKE-test-secret-do-not-use-1234567890"

GOOD_ANALYSIS = {
    "category": "Electrical",
    "issue_summary": "Exposed wiring beside a ceiling fan mount.",
    "safety_risk": "High",
    "functional_impact": "Medium",
    "urgency": "High",
    "evidence_from_image": "Bare wires and scorch marks are visible near the fan.",
    "uncertainty_or_missing_information": "Cannot tell whether the breaker is still live.",
}
GOOD_JSON = json.dumps(GOOD_ANALYSIS)


class FailingStubError(RuntimeError):
    """A stand-in for a Gemini/network failure."""


class ImageFixture(unittest.TestCase):
    """Base class providing a temporary directory with a fake (but well-formed) image.

    gemini.load_image only inspects the file name and size, never the pixels -
    and the Gemini call is stubbed anyway - so these bytes never need to be a
    real image.
    """

    FAKE_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n" + b"CampusLens fake image payload " * 20

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="campuslens_gemini_test_"))
        self.image_path = self.tmp_dir / "photo.png"
        self.image_path.write_bytes(self.FAKE_IMAGE_BYTES)

        # SAFETY NET: replace the real network call for every test in this class.
        # Any test that reaches Gemini without its own stub fails loudly here
        # instead of quietly spending API quota. Individual tests override this
        # with their own mock.patch.object(...) inside the test body.
        self._network_guard = mock.patch.object(
            gemini,
            "call_gemini",
            side_effect=AssertionError("a test tried to make a real Gemini call"),
        )
        self._network_guard.start()
        self.addCleanup(self._network_guard.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def analyze(self, **overrides):
        """Call analyze_complaint with a fake key and a stubbed Gemini call."""
        kwargs = {
            "image_path": self.image_path,
            "description": "Broken fan in Block C lab, sparks when switched on",
            "api_key": FAKE_SECRET,
        }
        kwargs.update(overrides)
        return gemini.analyze_complaint(**kwargs)


class ValidResponseTest(ImageFixture):
    """A well-formed response is accepted and normalized."""

    def test_valid_response_is_accepted(self):
        with mock.patch.object(gemini, "call_gemini", return_value=GOOD_JSON) as stub:
            result = self.analyze()

        self.assertTrue(result.ok)
        self.assertIsNone(result.error)
        self.assertIsNone(result.error_kind)
        self.assertEqual(result.analysis, GOOD_ANALYSIS)
        self.assertEqual(set(result.analysis), set(gemini.REQUIRED_FIELDS))
        self.assertEqual(stub.call_count, 1)

    def test_stub_receives_the_expected_arguments(self):
        with mock.patch.object(gemini, "call_gemini", return_value=GOOD_JSON) as stub:
            self.analyze(model="gemini-test-model")

        kwargs = stub.call_args.kwargs
        self.assertEqual(kwargs["api_key"], FAKE_SECRET)
        self.assertEqual(kwargs["model"], "gemini-test-model")
        self.assertEqual(kwargs["mime_type"], "image/png")
        self.assertEqual(kwargs["image_bytes"], self.FAKE_IMAGE_BYTES)
        self.assertIn("Broken fan in Block C lab", kwargs["description"])

    def test_result_records_the_model_and_elapsed_time(self):
        with mock.patch.object(gemini, "call_gemini", return_value=GOOD_JSON):
            result = self.analyze(model="gemini-test-model")

        self.assertEqual(result.model, "gemini-test-model")
        self.assertIsInstance(result.elapsed_seconds, float)
        self.assertGreaterEqual(result.elapsed_seconds, 0.0)


    def test_levels_are_normalized_for_case_and_whitespace(self):
        payload = dict(GOOD_ANALYSIS)
        payload["safety_risk"] = "  HIGH  "
        payload["functional_impact"] = "medium"
        payload["urgency"] = "high"

        with mock.patch.object(gemini, "call_gemini", return_value=json.dumps(payload)):
            result = self.analyze()

        self.assertTrue(result.ok)
        self.assertEqual(result.analysis["safety_risk"], "High")
        self.assertEqual(result.analysis["functional_impact"], "Medium")
        self.assertEqual(result.analysis["urgency"], "High")

    def test_text_fields_are_stripped(self):
        payload = dict(GOOD_ANALYSIS, category="  Electrical  ")

        with mock.patch.object(gemini, "call_gemini", return_value=json.dumps(payload)):
            result = self.analyze()

        self.assertTrue(result.ok)
        self.assertEqual(result.analysis["category"], "Electrical")

    def test_extra_fields_produce_a_warning_but_still_succeed(self):
        payload = dict(GOOD_ANALYSIS, confidence=0.91, model_notes="looks serious")

        with mock.patch.object(gemini, "call_gemini", return_value=json.dumps(payload)):
            result = self.analyze()

        self.assertTrue(result.ok)
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("confidence", result.warnings[0])
        self.assertNotIn("confidence", result.analysis)

    def test_analysis_key_order_matches_the_schema(self):
        with mock.patch.object(gemini, "call_gemini", return_value=GOOD_JSON):
            result = self.analyze()

        self.assertEqual(list(result.analysis), [
            "category", "issue_summary", "safety_risk", "functional_impact",
            "urgency", "evidence_from_image", "uncertainty_or_missing_information",
        ])

    def test_to_dict_is_json_serializable(self):
        with mock.patch.object(gemini, "call_gemini", return_value=GOOD_JSON):
            result = self.analyze()

        payload = result.to_dict()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["analysis"], GOOD_ANALYSIS)
        json.loads(json.dumps(payload))     # must not raise


class InvalidResponseTest(ImageFixture):
    """Malformed responses are rejected as validation errors, never accepted."""

    def test_missing_field_is_rejected(self):
        for field in gemini.REQUIRED_FIELDS:
            payload = dict(GOOD_ANALYSIS)
            del payload[field]
            with self.subTest(missing=field):
                with mock.patch.object(gemini, "call_gemini", return_value=json.dumps(payload)):
                    result = self.analyze()
                self.assertFalse(result.ok)
                self.assertEqual(result.error_kind, gemini.ERROR_VALIDATION)
                self.assertIn(field, result.error)
                self.assertIsNone(result.analysis)

    def test_empty_string_fields_are_rejected(self):
        for field in gemini.TEXT_FIELDS:
            for blank in ("", "   ", "\n"):
                payload = dict(GOOD_ANALYSIS, **{field: blank})
                with self.subTest(field=field, value=repr(blank)):
                    with mock.patch.object(gemini, "call_gemini",
                                           return_value=json.dumps(payload)):
                        result = self.analyze()
                    self.assertFalse(result.ok)
                    self.assertEqual(result.error_kind, gemini.ERROR_VALIDATION)
                    self.assertIn(field, result.error)

    def test_non_string_text_fields_are_rejected(self):
        for field in gemini.TEXT_FIELDS:
            for bad in (None, 123, ["x"], {"a": 1}):
                payload = dict(GOOD_ANALYSIS, **{field: bad})
                with self.subTest(field=field, value=repr(bad)):
                    with mock.patch.object(gemini, "call_gemini",
                                           return_value=json.dumps(payload)):
                        result = self.analyze()
                    self.assertFalse(result.ok)
                    self.assertEqual(result.error_kind, gemini.ERROR_VALIDATION)

    def test_invalid_level_values_are_rejected(self):
        for field in gemini.LEVEL_FIELDS:
            for bad in ("Extreme", "Severe", "Very High", "N/A", "Lo", "", None, 3):
                payload = dict(GOOD_ANALYSIS, **{field: bad})
                with self.subTest(field=field, value=repr(bad)):
                    with mock.patch.object(gemini, "call_gemini",
                                           return_value=json.dumps(payload)):
                        result = self.analyze()
                    self.assertFalse(result.ok)
                    self.assertEqual(result.error_kind, gemini.ERROR_VALIDATION)
                    self.assertIn(field, result.error)
                    self.assertIsNone(result.analysis)

    def test_lowercase_level_is_normalized_not_rejected(self):
        """Documented leniency: case/whitespace is normalized; other words are not."""
        payload = dict(GOOD_ANALYSIS, urgency="low")
        with mock.patch.object(gemini, "call_gemini", return_value=json.dumps(payload)):
            result = self.analyze()
        self.assertTrue(result.ok)
        self.assertEqual(result.analysis["urgency"], "Low")

    def test_malformed_json_is_rejected(self):
        for bad in ("not json at all", "{unclosed", "", "'single'"):
            with self.subTest(value=repr(bad)):
                with mock.patch.object(gemini, "call_gemini", return_value=bad):
                    result = self.analyze()
                self.assertFalse(result.ok)
                self.assertEqual(result.error_kind, gemini.ERROR_VALIDATION)

    def test_non_object_json_is_rejected(self):
        for bad in ("[1, 2, 3]", '"a string"', "42", "null"):
            with self.subTest(value=bad):
                with mock.patch.object(gemini, "call_gemini", return_value=bad):
                    result = self.analyze()
                self.assertFalse(result.ok)
                self.assertEqual(result.error_kind, gemini.ERROR_VALIDATION)

    def test_non_string_return_is_rejected(self):
        for bad in (None, b"bytes", 123):
            with self.subTest(value=repr(bad)):
                with mock.patch.object(gemini, "call_gemini", return_value=bad):
                    result = self.analyze()
                self.assertFalse(result.ok)
                self.assertEqual(result.error_kind, gemini.ERROR_VALIDATION)

    def test_multiple_problems_are_all_reported(self):
        payload = dict(GOOD_ANALYSIS, safety_risk="Extreme", urgency="", category="")
        with mock.patch.object(gemini, "call_gemini", return_value=json.dumps(payload)):
            result = self.analyze()
        self.assertFalse(result.ok)
        for field in ("safety_risk", "urgency", "category"):
            self.assertIn(field, result.error)


class ImageErrorTest(ImageFixture):
    """Image problems are reported clearly as ERROR_IMAGE, never crash."""

    def test_missing_image_is_reported(self):
        result = self.analyze(image_path=self.tmp_dir / "nope.png")
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, gemini.ERROR_IMAGE)
        self.assertIn("not found", result.error.lower())
        self.assertIsNone(result.analysis)

    def test_unsupported_image_type_is_reported(self):
        bad = self.tmp_dir / "notes.txt"
        bad.write_bytes(b"just text")
        result = self.analyze(image_path=bad)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, gemini.ERROR_IMAGE)
        self.assertIn("unsupported image type", result.error.lower())
        self.assertIn("notes.txt", result.error)

    def test_empty_image_is_reported(self):
        empty = self.tmp_dir / "empty.png"
        empty.write_bytes(b"")
        result = self.analyze(image_path=empty)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, gemini.ERROR_IMAGE)
        self.assertIn("empty", result.error.lower())

    def test_oversized_image_is_reported(self):
        with mock.patch.object(gemini, "MAX_IMAGE_BYTES", 10):
            result = self.analyze()
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, gemini.ERROR_IMAGE)
        self.assertIn("too large", result.error.lower())

    def test_none_path_is_reported(self):
        result = self.analyze(image_path=None)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, gemini.ERROR_IMAGE)

    def test_image_errors_do_not_call_gemini(self):
        """Fail fast: a bad image must not spend an API request."""
        with mock.patch.object(gemini, "call_gemini") as stub:
            self.analyze(image_path=self.tmp_dir / "missing.png")
        stub.assert_not_called()

    def test_jpeg_and_webp_are_accepted_mime_types(self):
        for name, expected_mime in (("a.jpg", "image/jpeg"),
                                    ("b.jpeg", "image/jpeg"),
                                    ("c.webp", "image/webp"),
                                    ("d.png", "image/png")):
            path = self.tmp_dir / name
            path.write_bytes(self.FAKE_IMAGE_BYTES)
            with self.subTest(name=name):
                with mock.patch.object(gemini, "call_gemini",
                                       return_value=GOOD_JSON) as stub:
                    result = self.analyze(image_path=path)
                self.assertTrue(result.ok)
                self.assertEqual(stub.call_args.kwargs["mime_type"], expected_mime)

    def test_load_image_returns_bytes_and_mime(self):
        data, mime_type = gemini.load_image(self.image_path)
        self.assertEqual(data, self.FAKE_IMAGE_BYTES)
        self.assertEqual(mime_type, "image/png")


class ApiErrorTest(ImageFixture):
    """Gemini/network/model failures become safe errors instead of exceptions."""

    def test_runtime_error_is_converted(self):
        with mock.patch.object(gemini, "call_gemini",
                               side_effect=FailingStubError("connection reset")):
            result = self.analyze()
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, gemini.ERROR_API)
        self.assertIn("FailingStubError", result.error)
        self.assertIn("connection reset", result.error)
        self.assertIsNone(result.analysis)

    def test_a_range_of_exception_types_never_crash(self):
        exceptions = [
            RuntimeError("boom"),
            TimeoutError("timed out after 90s"),
            ConnectionError("network unreachable"),
            ValueError("model gemini-3.8-flash not found"),
            KeyError("response"),
            TypeError("unexpected kwargs"),
            MemoryError("out of memory"),
            Exception("generic"),
        ]
        for exc in exceptions:
            with self.subTest(exc=type(exc).__name__):
                with mock.patch.object(gemini, "call_gemini", side_effect=exc):
                    result = self.analyze()      # must not raise
                self.assertFalse(result.ok)
                self.assertEqual(result.error_kind, gemini.ERROR_API)
                self.assertTrue(result.error)

    def test_unknown_model_error_is_readable(self):
        with mock.patch.object(
            gemini, "call_gemini",
            side_effect=ValueError("404 model `gemini-nope` not found for API version v1beta"),
        ):
            result = self.analyze()
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, gemini.ERROR_API)
        self.assertIn("gemini-nope", result.error)

    def test_top_level_catch_is_not_limited_to_one_error_type(self):
        """An exception raised from anywhere in the flow is still contained."""
        with mock.patch.object(gemini, "call_gemini", return_value=GOOD_JSON), \
             mock.patch.object(gemini, "validate_analysis",
                               side_effect=RuntimeError("validator exploded")):
            result = self.analyze()
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, gemini.ERROR_API)
        self.assertIn("validator exploded", result.error)


class RedactionTest(ImageFixture):
    """The API key must never appear in any error surfaced to the caller."""

    def test_secret_in_exception_message_is_redacted(self):
        with mock.patch.object(
            gemini, "call_gemini",
            side_effect=RuntimeError(f"401 Unauthorized for api_key={FAKE_SECRET}"),
        ):
            result = self.analyze()

        self.assertFalse(result.ok)
        self.assertNotIn(FAKE_SECRET, result.error)
        self.assertNotIn(FAKE_SECRET, json.dumps(result.to_dict()))
        self.assertIn("REDACTED", result.error)

    def test_secret_in_a_key_query_parameter_is_redacted(self):
        with mock.patch.object(
            gemini, "call_gemini",
            side_effect=ValueError(
                "HTTP 400 for https://generativelanguage.googleapis.com/v1beta/models"
                ":generateContent?key=AQ.Another-Fake-Key-9876543210&alt=json"
            ),
        ):
            result = self.analyze()

        self.assertFalse(result.ok)
        self.assertNotIn("AQ.Another-Fake-Key-9876543210", result.error)
        self.assertIn("key=***REDACTED***", result.error)
        self.assertIn("alt=json", result.error)          # only the key is scrubbed

    def test_successful_result_never_contains_the_key(self):
        with mock.patch.object(gemini, "call_gemini", return_value=GOOD_JSON):
            result = self.analyze()

        self.assertTrue(result.ok)
        self.assertNotIn(FAKE_SECRET, json.dumps(result.to_dict()))

    def test_redact_function(self):
        secret = "AQ.Secret-Value-123456789"
        self.assertEqual(gemini.redact(secret, secret), "***REDACTED***")
        self.assertEqual(
            gemini.redact(f"failed with {secret} here", secret),
            "failed with ***REDACTED*** here",
        )
        self.assertNotIn(secret, gemini.redact(f"x={secret}", secret))

    def test_redact_ignores_short_or_empty_secrets(self):
        """Short strings are left alone so real messages are not mangled."""
        self.assertEqual(gemini.redact("some text", ""), "some text")
        self.assertEqual(gemini.redact("some text", "abc"), "some text")
        self.assertEqual(gemini.redact("some text", None), "some text")

    def test_redact_is_case_insensitive_for_key_parameters(self):
        self.assertIn("KEY=***REDACTED***", gemini.redact("?KEY=abc123secret"))

    def test_config_error_never_echoes_the_key(self):
        result = self.analyze(api_key=FAKE_SECRET, image_path=self.tmp_dir / "gone.png")
        self.assertFalse(result.ok)
        self.assertNotIn(FAKE_SECRET, result.error or "")
        self.assertNotIn(FAKE_SECRET, json.dumps(result.to_dict()))


class ConfigurationTest(ImageFixture):
    """Missing credentials and bad caller input are clear, not crashes."""

    def test_missing_api_key_is_a_config_error(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "   "}):
            result = self.analyze(api_key=None)

        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, gemini.ERROR_CONFIG)
        self.assertIn("GEMINI_API_KEY", result.error)
        self.assertIsNone(result.analysis)

    def test_blank_explicit_key_falls_back_to_the_environment(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "   "}):
            result = self.analyze(api_key="   ")

        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, gemini.ERROR_CONFIG)

    def test_explicit_key_works_without_any_environment(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "   "}), \
             mock.patch.object(gemini, "call_gemini", return_value=GOOD_JSON):
            result = self.analyze(api_key=FAKE_SECRET)

        self.assertTrue(result.ok)

    def test_empty_description_is_an_input_error(self):
        for blank in ("", "   ", "\n", None, 123):
            with self.subTest(value=repr(blank)):
                with mock.patch.object(gemini, "call_gemini", return_value=GOOD_JSON) as stub:
                    result = self.analyze(description=blank)
                self.assertFalse(result.ok)
                self.assertEqual(result.error_kind, gemini.ERROR_INPUT)
                stub.assert_not_called()          # fail fast, no API request

    def test_missing_api_key_does_not_call_gemini(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "   "}), \
             mock.patch.object(gemini, "call_gemini") as stub:
            self.analyze(api_key=None)
        stub.assert_not_called()

    def test_env_path_is_derived_from_the_module_location(self):
        """Portable check: the path comes from the module, not the CWD."""
        self.assertEqual(gemini.ENV_PATH, gemini.BACKEND_DIR / ".env")
        self.assertEqual(gemini.BACKEND_DIR.name, "backend")
        self.assertIsInstance(gemini.load_env_file(), bool)

    def test_config_error_when_env_file_is_absent(self):
        with mock.patch.object(gemini, "ENV_PATH", Path("C:/definitely/not/here/.env")), \
             mock.patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            self.assertFalse(gemini.load_env_file())
            result = self.analyze(api_key=None)

        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, gemini.ERROR_CONFIG)


class ModelResolutionTest(ImageFixture):
    """Model choice: explicit argument, then GEMINI_MODEL, then the default."""

    def test_default_model_constant(self):
        self.assertEqual(gemini.DEFAULT_MODEL, "gemini-3.8-flash")

    def test_explicit_model_wins_over_the_environment(self):
        with mock.patch.dict("os.environ", {"GEMINI_MODEL": "from-env"}), \
             mock.patch.object(gemini, "call_gemini", return_value=GOOD_JSON):
            result = self.analyze(model="explicit-model")
        self.assertEqual(result.model, "explicit-model")

    def test_environment_model_is_used_when_no_explicit_model(self):
        with mock.patch.dict("os.environ", {"GEMINI_MODEL": "from-env"}), \
             mock.patch.object(gemini, "call_gemini", return_value=GOOD_JSON):
            result = self.analyze()
        self.assertEqual(result.model, "from-env")

    def test_default_model_used_when_the_environment_is_blank(self):
        with mock.patch.dict("os.environ", {"GEMINI_MODEL": "   "}), \
             mock.patch.object(gemini, "call_gemini", return_value=GOOD_JSON):
            result = self.analyze()
        self.assertEqual(result.model, gemini.DEFAULT_MODEL)

    def test_blank_explicit_model_falls_through_to_the_environment(self):
        with mock.patch.dict("os.environ", {"GEMINI_MODEL": "from-env"}), \
             mock.patch.object(gemini, "call_gemini", return_value=GOOD_JSON):
            result = self.analyze(model="   ")
        self.assertEqual(result.model, "from-env")

    def test_resolved_model_is_always_reported_even_on_failure(self):
        with mock.patch.dict("os.environ", {"GEMINI_MODEL": "   "}), \
             mock.patch.object(gemini, "call_gemini", side_effect=RuntimeError("nope")):
            result = self.analyze()
        self.assertFalse(result.ok)
        self.assertEqual(result.model, gemini.DEFAULT_MODEL)

    def test_timeout_is_forwarded_to_the_call(self):
        with mock.patch.object(gemini, "call_gemini", return_value=GOOD_JSON) as stub:
            self.analyze(timeout_ms=1234)
        self.assertEqual(stub.call_args.kwargs["timeout_ms"], 1234)

    def test_default_timeout_value(self):
        self.assertEqual(gemini.REQUEST_TIMEOUT_MS, 90_000)


class PromptTest(unittest.TestCase):
    """The conservative prompt rules are preserved, not dropped."""

    def setUp(self):
        self.prompt = gemini.build_prompt("Fan sparks when switched on")

    def test_contains_the_student_description(self):
        self.assertIn("Fan sparks when switched on", self.prompt)

    def test_requires_separating_visible_from_claimed(self):
        lowered = self.prompt.lower()
        self.assertIn("see", lowered)
        self.assertIn("claimed", lowered)

    def test_requires_flagging_contradictions(self):
        self.assertIn("contradict", self.prompt.lower())

    def test_forbids_inventing_evidence(self):
        self.assertIn("do not invent", self.prompt.lower())

    def test_requires_stating_uncertainty(self):
        self.assertIn("uncertainty_or_missing_information", self.prompt)
        self.assertIn("cannot verify", self.prompt.lower())

    def test_restricts_evidence_from_image_to_visible_details(self):
        self.assertIn("evidence_from_image", self.prompt)
        self.assertIn("only", self.prompt.lower())

    def test_asks_for_conservative_severity(self):
        self.assertIn("conservatively", self.prompt.lower())

    def test_names_the_exact_level_vocabulary(self):
        self.assertIn("Low", self.prompt)
        self.assertIn("Medium", self.prompt)
        self.assertIn("High", self.prompt)

    def test_asks_for_json_only(self):
        self.assertIn("JSON only", self.prompt)

    def test_survives_a_hostile_description(self):
        hostile = 'Braces } { and quotes " and a newline\nand """ triples'
        prompt = gemini.build_prompt(hostile)
        self.assertIn("Braces", prompt)
        self.assertIn("contradict", prompt.lower())


class ValidateAnalysisTest(unittest.TestCase):
    """Direct unit tests for validate_analysis()."""

    def test_valid_payload_is_cleaned_and_returned(self):
        cleaned, problems, warnings = gemini.validate_analysis(dict(GOOD_ANALYSIS))
        self.assertEqual(cleaned, GOOD_ANALYSIS)
        self.assertEqual(problems, [])
        self.assertEqual(warnings, [])

    def test_problems_are_returned_and_cleaned_is_none(self):
        cleaned, problems, warnings = gemini.validate_analysis({"category": "Electrical"})
        self.assertIsNone(cleaned)
        self.assertEqual(len(problems), 6)          # six missing fields
        self.assertTrue(all("missing field" in p for p in problems))

    def test_non_dict_payload(self):
        for bad in ([1, 2], "string", 42, None):
            with self.subTest(value=repr(bad)):
                cleaned, problems, warnings = gemini.validate_analysis(bad)
                self.assertIsNone(cleaned)
                self.assertEqual(len(problems), 1)

    def test_extra_fields_become_warnings_only(self):
        payload = dict(GOOD_ANALYSIS, extra_one=1, extra_two=2)
        cleaned, problems, warnings = gemini.validate_analysis(payload)
        self.assertEqual(problems, [])
        self.assertEqual(len(warnings), 1)
        self.assertNotIn("extra_one", cleaned)

    def test_validate_analysis_never_raises(self):
        for bad in (None, [], {}, 0, "x", {"a": object()}):
            with self.subTest(value=repr(bad)):
                gemini.validate_analysis(bad)       # must not raise


class IndependenceAndContractTest(ImageFixture):
    """gemini.py stays a focused module and honours its documented contract."""

    def test_module_does_not_import_the_database_or_scorer(self):
        import re
        source = Path(gemini.__file__).read_text(encoding="utf-8")
        forbidden = re.search(
            r"^\s*(?:import|from)\s+(sqlite3|database|priority|fastapi|app)\b",
            source,
            re.MULTILINE,
        )
        found = forbidden.group(0) if forbidden else None
        self.assertIsNone(forbidden, f"gemini.py must not import: {found}")

    def test_module_has_no_category_weight_support(self):
        """Category weights belong to priority.py, not here."""
        self.assertFalse(hasattr(gemini, "CATEGORY_WEIGHT_POINTS"))
        self.assertFalse(hasattr(gemini, "score_complaint"))
        self.assertFalse(hasattr(gemini, "category_weight_class"))

    def test_required_fields_match_the_seven_field_contract(self):
        self.assertEqual(gemini.REQUIRED_FIELDS, (
            "category", "issue_summary", "safety_risk", "functional_impact",
            "urgency", "evidence_from_image", "uncertainty_or_missing_information",
        ))
        self.assertEqual(gemini.TEXT_FIELDS, (
            "category", "issue_summary", "evidence_from_image",
            "uncertainty_or_missing_information",
        ))
        self.assertEqual(gemini.LEVEL_FIELDS,
                         ("safety_risk", "functional_impact", "urgency"))
        self.assertEqual(gemini.ALLOWED_LEVELS, ("Low", "Medium", "High"))

    def test_result_dataclass_is_frozen(self):
        result = self.analyze()
        with self.assertRaises(AttributeError):     # FrozenInstanceError subclasses it
            result.ok = True

    def test_analyze_complaint_never_raises(self):
        """A sweep of hostile calls must always produce an AnalysisResult."""
        hostile = [
            {"image_path": None, "description": None},
            {"image_path": 123, "description": object()},
            {"image_path": b"bytes", "description": ["list"]},
            {"image_path": self.tmp_dir / "gone.png", "description": "valid text"},
            {"image_path": self.image_path, "description": "   "},
        ]
        for kwargs in hostile:
            with self.subTest(kwargs=repr(kwargs)):
                result = gemini.analyze_complaint(**kwargs, api_key=FAKE_SECRET)
                self.assertIsInstance(result, gemini.AnalysisResult)
                self.assertFalse(result.ok)

    def test_analyze_complaint_never_raises_when_gemini_explodes(self):
        with mock.patch.object(gemini, "call_gemini",
                               side_effect=Exception("total meltdown")):
            result = self.analyze()
        self.assertIsInstance(result, gemini.AnalysisResult)
        self.assertFalse(result.ok)

    def test_omitting_required_arguments_is_a_normal_type_error(self):
        """Missing positional args are a caller bug, reported immediately."""
        with self.assertRaises(TypeError):
            gemini.analyze_complaint()
        with self.assertRaises(TypeError):
            gemini.analyze_complaint(image_path=self.image_path)

    def test_result_fields_are_always_populated(self):
        with mock.patch.object(gemini, "call_gemini", return_value=GOOD_JSON):
            ok_result = self.analyze()
        self.assertTrue(ok_result.ok)
        self.assertIsNotNone(ok_result.analysis)
        self.assertIsNone(ok_result.error)
        self.assertIsNone(ok_result.error_kind)
        self.assertTrue(ok_result.model)

        failed = self.analyze(image_path=self.tmp_dir / "absent.png")
        self.assertFalse(failed.ok)
        self.assertIsNone(failed.analysis)
        self.assertIsNotNone(failed.error)
        self.assertIsNotNone(failed.error_kind)
        self.assertTrue(failed.model)


if __name__ == "__main__":
    unittest.main(verbosity=2)