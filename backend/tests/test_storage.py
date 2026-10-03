"""
Offline tests for the Supabase Storage client and its configuration.

No test makes a real network call: HTTP is mocked at ``httpx.post``, and
every test strips ``SUPABASE_*`` variables from the process environment so
a developer's shell can never change what these tests see. The service key
used here is a deliberately fake value, and assertions prove it never leaks
into exception messages.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app import config, storage  # noqa: E402

FAKE_KEY = "service-role-FAKE-key-do-not-use-98765"
PROJECT = "https://example.supabase.co"
BUCKET = "imagestorage"
GENERATED_NAME = "0123456789abcdef0123456789abcdef.png"


class _EnvIsolatedTestCase(unittest.TestCase):
    """Strips SUPABASE_* from the environment for the duration of each test."""

    def setUp(self):
        self._env = mock.patch.dict(os.environ)
        self._env.start()
        self.addCleanup(self._env.stop)
        for name in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_BUCKET"):
            os.environ.pop(name, None)


class _FakeResponse:
    """Just enough of httpx.Response for the code under test."""

    def __init__(self, status_code=200, payload=None, *, json_error=False, headers=None):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error
        self.headers = dict(headers or {})

    def json(self):
        if self._json_error:
            raise ValueError("simulated invalid JSON")
        return self._payload


def _settings(**overrides):
    """A fully configured Settings; pass overrides to remove/alter fields."""
    values = dict(
        db_path=Path("unused.db"),
        upload_dir=Path("unused_uploads"),
        max_upload_bytes=1024,
        allowed_mime_types=frozenset({"image/png"}),
        allowed_extensions=frozenset({".png"}),
        cors_origins=(),
        supabase_url=PROJECT,
        supabase_service_role_key=FAKE_KEY,
        supabase_bucket=BUCKET,
    )
    values.update(overrides)
    return config.Settings(**values)


class SettingsFromEnvironmentTest(_EnvIsolatedTestCase):
    """Configuration comes from the process environment - never from .env."""

    def test_absent_environment_disables_storage(self):
        settings = config.default_settings()
        self.assertIsNone(settings.supabase_url)
        self.assertIsNone(settings.supabase_service_role_key)
        self.assertEqual(settings.supabase_bucket, config.DEFAULT_SUPABASE_BUCKET)
        self.assertFalse(settings.supabase_enabled)

    def test_blank_values_disable_storage(self):
        os.environ["SUPABASE_URL"] = "   "
        os.environ["SUPABASE_SERVICE_ROLE_KEY"] = ""
        os.environ["SUPABASE_BUCKET"] = "  "
        settings = config.default_settings()
        self.assertFalse(settings.supabase_enabled)
        self.assertEqual(settings.supabase_bucket, config.DEFAULT_SUPABASE_BUCKET)

    def test_url_and_key_enable_storage_values_are_stripped(self):
        os.environ["SUPABASE_URL"] = f"  {PROJECT} "
        os.environ["SUPABASE_SERVICE_ROLE_KEY"] = f"  {FAKE_KEY} "
        settings = config.default_settings()
        self.assertTrue(settings.supabase_enabled)
        self.assertEqual(settings.supabase_url, PROJECT)
        self.assertEqual(settings.supabase_service_role_key, FAKE_KEY)

    def test_url_alone_is_not_enough(self):
        os.environ["SUPABASE_URL"] = PROJECT
        self.assertFalse(config.default_settings().supabase_enabled)

    def test_key_alone_is_not_enough(self):
        os.environ["SUPABASE_SERVICE_ROLE_KEY"] = FAKE_KEY
        self.assertFalse(config.default_settings().supabase_enabled)

    def test_bucket_env_override_does_not_enable_storage(self):
        os.environ["SUPABASE_BUCKET"] = "my-bucket"
        settings = config.default_settings()
        self.assertEqual(settings.supabase_bucket, "my-bucket")
        self.assertFalse(settings.supabase_enabled)

    def test_service_key_never_appears_in_repr_or_str(self):
        os.environ["SUPABASE_URL"] = PROJECT
        os.environ["SUPABASE_SERVICE_ROLE_KEY"] = FAKE_KEY
        settings = config.default_settings()
        self.assertNotIn(FAKE_KEY, repr(settings))
        self.assertNotIn(FAKE_KEY, str(settings))
        self.assertNotIn("supabase_service_role_key", repr(settings))

    def test_settings_for_follows_the_environment(self):
        os.environ["SUPABASE_URL"] = PROJECT
        os.environ["SUPABASE_SERVICE_ROLE_KEY"] = FAKE_KEY
        settings = config.settings_for(Path("x.db"), Path("x_uploads"))
        self.assertTrue(settings.supabase_enabled)
        self.assertEqual(settings.supabase_url, PROJECT)


class UploadTest(_EnvIsolatedTestCase):
    """storage.upload() request shape, errors and redaction."""

    def setUp(self):
        super().setUp()
        self.settings = _settings()

    def test_upload_targets_private_object_endpoint_and_returns_path(self):
        fake = _FakeResponse(200, {"Key": f"{BUCKET}/uploads/{GENERATED_NAME}"})
        with mock.patch.object(storage.httpx, "post", return_value=fake) as post:
            result = storage.upload(
                self.settings,
                b"BYTES",
                content_type="image/png",
                object_path=f"uploads/{GENERATED_NAME}",
            )

        self.assertEqual(result, f"uploads/{GENERATED_NAME}")
        post.assert_called_once()
        called_url = post.call_args.args[0]
        self.assertEqual(
            called_url,
            f"{PROJECT}/storage/v1/object/{BUCKET}/uploads/{GENERATED_NAME}",
        )
        self.assertNotIn("/object/public/", called_url)   # bucket stays private
        self.assertNotIn("/object/sign/", called_url)
        self.assertEqual(post.call_args.kwargs["content"], b"BYTES")
        self.assertEqual(
            post.call_args.kwargs["timeout"], storage.REQUEST_TIMEOUT_SECONDS
        )
        headers = post.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], f"Bearer {FAKE_KEY}")
        self.assertEqual(headers["apikey"], FAKE_KEY)
        self.assertEqual(headers["Content-Type"], "image/png")

    def test_upload_sends_both_auth_headers_and_never_the_key_in_the_url(self):
        """Regression: Supabase authenticates via the apikey header too.

        Sending only Authorization made the Storage API reject the upload with
        HTTP 400 ("Image storage unavailable" surfaced to the student).
        """
        fake = _FakeResponse(200, {"Key": f"{BUCKET}/uploads/{GENERATED_NAME}"})
        with mock.patch.object(storage.httpx, "post", return_value=fake) as post:
            storage.upload(
                self.settings,
                b"BYTES",
                content_type="image/png",
                object_path=f"uploads/{GENERATED_NAME}",
            )

        headers = post.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], f"Bearer {FAKE_KEY}")
        self.assertEqual(headers["apikey"], FAKE_KEY)
        called_url = post.call_args.args[0]
        self.assertNotIn(FAKE_KEY, called_url)   # never in the URL
        self.assertNotIn(headers["apikey"], called_url)

    def test_upload_without_url_or_key_never_makes_a_request(self):
        for overrides in (
            {"supabase_url": None},
            {"supabase_service_role_key": None},
            {"supabase_url": "   "},
            {"supabase_service_role_key": "  "},
        ):
            with self.subTest(overrides=overrides):
                with mock.patch.object(storage.httpx, "post") as post:
                    with self.assertRaises(storage.StorageError):
                        storage.upload(
                            _settings(**overrides),
                            b"x",
                            content_type="image/png",
                            object_path="uploads/a.png",
                        )
                    post.assert_not_called()

    def test_http_error_reports_only_the_status_code(self):
        fake = _FakeResponse(403, {"message": f"forbidden {FAKE_KEY}"})
        with mock.patch.object(storage.httpx, "post", return_value=fake):
            with self.assertRaises(storage.StorageError) as ctx:
                storage.upload(
                    self.settings,
                    b"x",
                    content_type="image/png",
                    object_path="uploads/a.png",
                )
        message = str(ctx.exception)
        self.assertIn("403", message)
        self.assertNotIn(FAKE_KEY, message)
        self.assertNotIn("forbidden", message)  # response bodies are never echoed

    def test_transport_error_is_classified_and_redacted(self):
        request = httpx.Request("POST", f"{PROJECT}/storage/v1/object/x")
        boom = httpx.ConnectError(f"connection failed {FAKE_KEY}", request=request)
        with mock.patch.object(storage.httpx, "post", side_effect=boom):
            with self.assertRaises(storage.StorageError) as ctx:
                storage.upload(
                    self.settings,
                    b"x",
                    content_type="image/png",
                    object_path="uploads/a.png",
                )
        message = str(ctx.exception)
        self.assertIn("ConnectError", message)
        self.assertNotIn(FAKE_KEY, message)

    def test_unsafe_object_paths_are_refused_before_any_request(self):
        for bad in (
            "",
            "/etc/passwd",
            "../escape.png",
            "uploads/../../x.png",
            "uploads\\x.png",
            "uploads//x.png",
            "uploads/a b.png",
        ):
            with self.subTest(path=bad):
                with mock.patch.object(storage.httpx, "post") as post:
                    with self.assertRaises(storage.StorageError):
                        storage.upload(
                            self.settings,
                            b"x",
                            content_type="image/png",
                            object_path=bad,
                        )
                    post.assert_not_called()

    def test_invalid_bucket_is_refused_before_any_request(self):
        with mock.patch.object(storage.httpx, "post") as post:
            with self.assertRaises(storage.StorageError):
                storage.upload(
                    _settings(supabase_bucket="bad bucket"),
                    b"x",
                    content_type="image/png",
                    object_path="uploads/a.png",
                )
            post.assert_not_called()


class SignedUrlTest(_EnvIsolatedTestCase):
    """storage.signed_url(): 300 s TTL, private endpoint, redacted errors."""

    def setUp(self):
        super().setUp()
        self.settings = _settings()
        self.object_path = f"uploads/{GENERATED_NAME}"

    def test_sign_returns_absolute_url_and_uses_300_second_ttl(self):
        signed_path = f"/object/sign/{BUCKET}/{self.object_path}?token=abc.def"
        fake = _FakeResponse(200, {"signedURL": signed_path})
        with mock.patch.object(storage.httpx, "post", return_value=fake) as post:
            url = storage.signed_url(self.settings, self.object_path)

        self.assertEqual(url, PROJECT + signed_path)
        self.assertEqual(
            post.call_args.args[0],
            f"{PROJECT}/storage/v1/object/sign/{BUCKET}/{self.object_path}",
        )
        self.assertEqual(post.call_args.kwargs["json"], {"expiresIn": 300})
        self.assertEqual(storage.SIGN_URL_TTL_SECONDS, 300)
        headers = post.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], f"Bearer {FAKE_KEY}")
        self.assertEqual(headers["apikey"], FAKE_KEY)

    def test_sign_body_uses_the_camel_case_expires_in_field(self):
        """Regression: the Storage API rejects ``expires_in`` with HTTP 400.

        ``POST /storage/v1/object/sign/...`` requires the body property
        ``expiresIn``; the snake_case spelling fails body validation and the
        signed URL request failed with 400.
        """
        signed_path = f"/object/sign/{BUCKET}/{self.object_path}?token=abc.def"
        fake = _FakeResponse(200, {"signedURL": signed_path})
        with mock.patch.object(storage.httpx, "post", return_value=fake) as post:
            storage.signed_url(self.settings, self.object_path)

        body = post.call_args.kwargs["json"]
        self.assertEqual(body, {"expiresIn": 300})
        self.assertNotIn("expires_in", body)          # wrong spelling is gone
        self.assertEqual(list(body), ["expiresIn"])    # no extra properties

    def test_sign_honours_a_custom_ttl_and_both_auth_headers(self):
        signed_path = f"/object/sign/{BUCKET}/{self.object_path}?token=abc.def"
        fake = _FakeResponse(200, {"signedURL": signed_path})
        with mock.patch.object(storage.httpx, "post", return_value=fake) as post:
            storage.signed_url(self.settings, self.object_path, expires_in=60)

        self.assertEqual(post.call_args.kwargs["json"], {"expiresIn": 60})
        headers = post.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], f"Bearer {FAKE_KEY}")
        self.assertEqual(headers["apikey"], FAKE_KEY)
        called_url = post.call_args.args[0]
        self.assertNotIn(FAKE_KEY, called_url)        # key stays out of the URL

    def test_sign_without_configuration_never_makes_a_request(self):
        with mock.patch.object(storage.httpx, "post") as post:
            with self.assertRaises(storage.StorageError):
                storage.signed_url(
                    _settings(supabase_service_role_key=None),
                    self.object_path,
                )
            post.assert_not_called()

    def test_sign_http_error_is_generic_and_scrubbed(self):
        fake = _FakeResponse(503, {"message": f"unavailable {FAKE_KEY}"})
        with mock.patch.object(storage.httpx, "post", return_value=fake):
            with self.assertRaises(storage.StorageError) as ctx:
                storage.signed_url(self.settings, self.object_path)
        message = str(ctx.exception)
        self.assertIn("503", message)
        self.assertNotIn(FAKE_KEY, message)
        self.assertNotIn("unavailable", message)

    def test_sign_invalid_json_is_storage_error(self):
        fake = _FakeResponse(200, json_error=True)
        with mock.patch.object(storage.httpx, "post", return_value=fake):
            with self.assertRaises(storage.StorageError):
                storage.signed_url(self.settings, self.object_path)

    def test_sign_missing_or_empty_url_is_storage_error(self):
        for payload in ({}, {"signedURL": ""}, {"signedURL": 42}, [], None):
            with self.subTest(payload=payload):
                fake = _FakeResponse(200, payload)
                with mock.patch.object(storage.httpx, "post", return_value=fake):
                    with self.assertRaises(storage.StorageError):
                        storage.signed_url(self.settings, self.object_path)

    def test_absolute_signed_url_is_returned_as_is(self):
        absolute = "https://cdn.example.test/object?token=x"
        fake = _FakeResponse(200, {"signedURL": absolute})
        with mock.patch.object(storage.httpx, "post", return_value=fake):
            result = storage.signed_url(self.settings, self.object_path)
        self.assertEqual(result, absolute)


class StorageDiagnosticsTest(_EnvIsolatedTestCase):
    """Failure diagnostics: enough to debug, never enough to leak.

    The logs explain WHY Supabase refused a request (phase, HTTP status,
    error type, request id and a redacted message) while proving that no key,
    JWT, URL, bucket name or object path can appear in them.
    """

    def setUp(self):
        super().setUp()
        self.settings = _settings()
        self.object_path = f"uploads/{GENERATED_NAME}"

    def _fail_upload(self, response):
        with mock.patch.object(storage.httpx, "post", return_value=response):
            with self.assertRaises(storage.StorageError):
                storage.upload(
                    self.settings,
                    b"BYTES",
                    content_type="image/png",
                    object_path=self.object_path,
                )

    def _fail_sign(self, response):
        with mock.patch.object(storage.httpx, "post", return_value=response):
            with self.assertRaises(storage.StorageError):
                storage.signed_url(self.settings, self.object_path)

    def _logged(self, response, fail):
        with self.assertLogs("campuslens.storage", level="WARNING") as logs:
            fail(response)
        return "\n".join(logs.output)

    def test_upload_failure_logs_phase_status_type_and_request_id(self):
        response = _FakeResponse(
            400,
            {"statusCode": "400", "error": "InvalidRequest", "message": "bad body"},
            headers={"x-sb-request-id": "req-upload-1"},
        )
        line = self._logged(response, self._fail_upload)

        self.assertIn("supabase storage upload rejected", line)
        self.assertIn("http=400", line)
        self.assertIn("type=InvalidRequest", line)
        self.assertIn("request_id=req-upload-1", line)
        self.assertIn("message=bad body", line)

    def test_sign_failure_logs_phase_status_type_and_request_id(self):
        response = _FakeResponse(
            400,
            {"statusCode": "400", "error": "InvalidRequest", "message": "missing field"},
            headers={"x-sb-request-id": "req-sign-1"},
        )
        line = self._logged(response, self._fail_sign)

        self.assertIn("supabase storage sign rejected", line)
        self.assertIn("http=400", line)
        self.assertIn("type=InvalidRequest", line)
        self.assertIn("request_id=req-sign-1", line)

    def test_diagnostics_never_leak_key_urls_jwt_bucket_or_path(self):
        """A hostile error message is scrubbed of every sensitive value."""
        hostile = (
            f"Invalid JWT {FAKE_KEY} for {PROJECT}/storage/v1/object/{BUCKET}/"
            f"{self.object_path} (eyJhbGciOiJIUzI1NiJ9.payload.signature)"
        )
        response = _FakeResponse(
            400,
            {"statusCode": "400", "error": "InvalidRequest", "message": hostile},
            headers={"x-sb-request-id": "req-leak"},
        )
        line = self._logged(response, self._fail_upload)

        for forbidden in (
            FAKE_KEY,
            PROJECT,
            "example.supabase.co",
            BUCKET,
            GENERATED_NAME,
            self.object_path,
            "eyJhbGciOiJIUzI1NiJ9",
            "https://",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, line)
        self.assertIn("[redacted]", line)
        self.assertIn("request_id=req-leak", line)

    def test_message_is_omitted_when_it_cannot_be_proven_safe(self):
        """A malformed (non-dict) error body logs only the safe fields."""
        for payload, as_json in ((["not", "a", "dict"], False), (None, True)):
            with self.subTest(payload=payload):
                response = _FakeResponse(
                    502, payload, json_error=as_json,
                    headers={"x-sb-request-id": "req-malformed"},
                )
                line = self._logged(response, self._fail_sign)

                self.assertIn("supabase storage sign rejected", line)
                self.assertIn("http=502", line)
                self.assertIn("type=unknown", line)
                self.assertIn("request_id=req-malformed", line)
                self.assertIn("message=omitted", line)

    def test_long_error_message_is_truncated(self):
        response = _FakeResponse(
            400, {"error": "InvalidRequest", "message": "x" * 5000}
        )
        line = self._logged(response, self._fail_upload)

        self.assertIn("message=" + "x" * storage._MAX_MESSAGE_CHARS, line)
        self.assertNotIn("x" * (storage._MAX_MESSAGE_CHARS + 1), line)

    def test_successful_calls_log_nothing(self):
        """No diagnostics on the happy path - and no signed URL either."""
        signed = f"/object/sign/{BUCKET}/{self.object_path}?token=abc.def"
        with mock.patch.object(
            storage.httpx, "post", return_value=_FakeResponse(200, {"signedURL": signed})
        ):
            with mock.patch.object(storage.logger, "warning") as warning:
                storage.signed_url(self.settings, self.object_path)
                storage.upload(
                    self.settings, b"BYTES", content_type="image/png",
                    object_path=self.object_path,
                )
        warning.assert_not_called()

    def test_failure_message_and_exception_behaviour_are_unchanged(self):
        """Diagnostics are additive: the caller still gets status-code-only."""
        response = _FakeResponse(
            400,
            {
                "statusCode": "400",
                "error": "InvalidRequest",
                "message": f"nope {FAKE_KEY}",
            },
        )
        with mock.patch.object(storage.httpx, "post", return_value=response):
            with self.assertRaises(storage.StorageError) as ctx:
                storage.upload(
                    self.settings, b"x", content_type="image/png",
                    object_path=self.object_path,
                )
        message = str(ctx.exception)
        self.assertIn("400", message)
        self.assertIn("rejected the upload", message)
        self.assertNotIn(FAKE_KEY, message)
        self.assertNotIn("nope", message)          # body still never echoed