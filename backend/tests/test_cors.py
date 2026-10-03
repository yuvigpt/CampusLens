"""
Unit tests for CORS origin configuration (Stage 1: CORS_ORIGINS).

Run with the project venv, from the project root:

    python -m unittest discover -s backend/tests -t backend

Covers: the default localhost origins, one configured origin, multiple
comma-separated origins with whitespace, empty entries, empty/unset values,
the CORS_ORIGINS environment variable reaching ``default_settings()``, the
configured origins flowing into the running middleware, and the credential /
method / header behaviour of that middleware staying exactly as it was.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Make "from app import ..." work regardless of the current working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402
from app.main import create_app  # noqa: E402

# Exactly the origins the app served before CORS_ORIGINS existed.
LOCALHOST_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)

CONFIGURED = "https://campuslens.vercel.app"


class ParseCorsOriginsTest(unittest.TestCase):
    """Pure parser behaviour - no environment involved."""

    def test_unset_preserves_the_default_localhost_origins(self):
        self.assertEqual(config.parse_cors_origins(None), LOCALHOST_ORIGINS)

    def test_empty_value_preserves_the_default_localhost_origins(self):
        for raw in ("", "   ", "\t"):
            with self.subTest(raw=raw):
                self.assertEqual(config.parse_cors_origins(raw), LOCALHOST_ORIGINS)

    def test_one_configured_origin(self):
        self.assertEqual(config.parse_cors_origins(CONFIGURED), (CONFIGURED,))

    def test_multiple_origins_with_whitespace_are_trimmed(self):
        self.assertEqual(
            config.parse_cors_origins("  https://a.example ,\thttps://b.example\n"),
            ("https://a.example", "https://b.example"),
        )

    def test_empty_entries_are_ignored(self):
        self.assertEqual(
            config.parse_cors_origins("https://a.example,, , ,https://b.example,"),
            ("https://a.example", "https://b.example"),
        )

    def test_only_separators_falls_back_to_defaults(self):
        self.assertEqual(config.parse_cors_origins(" , ,, "), LOCALHOST_ORIGINS)

    def test_defaults_stay_specific_and_never_wildcarded(self):
        self.assertNotIn("*", config.parse_cors_origins(None))


class CorsOriginsFromEnvTest(unittest.TestCase):
    """The CORS_ORIGINS environment variable, read the way the app reads it."""

    def resolve(self, value=None):
        """``cors_origins_from_env()`` with CORS_ORIGINS pinned (None = unset)."""
        with mock.patch.dict(os.environ):
            if value is None:
                os.environ.pop("CORS_ORIGINS", None)
            else:
                os.environ["CORS_ORIGINS"] = value
            return config.cors_origins_from_env()

    def test_unset_env_gives_the_default_localhost_origins(self):
        self.assertEqual(self.resolve(None), LOCALHOST_ORIGINS)

    def test_empty_env_gives_the_default_localhost_origins(self):
        self.assertEqual(self.resolve(""), LOCALHOST_ORIGINS)

    def test_one_configured_origin(self):
        self.assertEqual(self.resolve(CONFIGURED), (CONFIGURED,))

    def test_multiple_origins_with_whitespace_and_empty_entries(self):
        self.assertEqual(
            self.resolve(" https://app.example.com , ,http://localhost:5173 ,,"),
            ("https://app.example.com", "http://localhost:5173"),
        )

    def test_default_settings_honours_the_env(self):
        with mock.patch.dict(os.environ):
            os.environ["CORS_ORIGINS"] = CONFIGURED
            self.assertEqual(config.default_settings().cors_origins, (CONFIGURED,))
            os.environ.pop("CORS_ORIGINS", None)
            self.assertEqual(config.default_settings().cors_origins, LOCALHOST_ORIGINS)


class CorsAppTest(unittest.TestCase):
    """Configured origins reach the real middleware; behaviour stays put."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="campuslens_cors_test_"))
        self.addCleanup(shutil.rmtree, self.tmp_dir, True)   # runs last
        self.db_path = self.tmp_dir / "test.db"
        self.upload_dir = self.tmp_dir / "uploads"

    def start_client(self, env_value=None):
        """Build the app with CORS_ORIGINS pinned while settings are resolved.

        The client is never entered: a preflight request is answered by
        CORSMiddleware before any route runs, so neither the database nor the
        uploads folder is touched.
        """
        with mock.patch.dict(os.environ):
            if env_value is None:
                os.environ.pop("CORS_ORIGINS", None)
            else:
                os.environ["CORS_ORIGINS"] = env_value
            settings = config.settings_for(self.db_path, self.upload_dir)
        self.app = create_app(settings)
        return TestClient(self.app)

    def preflight(self, client, origin):
        return client.options(
            "/api/complaints",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
            },
        )

    def test_configured_origin_is_allowed(self):
        client = self.start_client(CONFIGURED)
        response = self.preflight(client, CONFIGURED)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("access-control-allow-origin"), CONFIGURED
        )

    def test_any_other_origin_is_refused_when_configured(self):
        client = self.start_client(CONFIGURED)
        response = self.preflight(client, "http://localhost:5173")
        self.assertIsNone(response.headers.get("access-control-allow-origin"))

    def test_default_localhost_origins_apply_when_env_is_unset(self):
        client = self.start_client(None)
        response = self.preflight(client, "http://127.0.0.1:5173")
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "http://127.0.0.1:5173",
        )

    def test_credentials_methods_and_headers_are_unchanged(self):
        client = self.start_client(CONFIGURED)
        response = self.preflight(client, CONFIGURED)
        self.assertIsNone(response.headers.get("access-control-allow-credentials"))
        self.assertEqual(
            response.headers.get("access-control-allow-methods"),
            "GET, POST, PATCH, OPTIONS",
        )
        # The configured header list is still just Content-Type; Starlette
        # itself appends the three CORS-safelisted request headers to every
        # preflight, exactly as it did before CORS_ORIGINS existed.
        self.assertEqual(
            response.headers.get("access-control-allow-headers"),
            "Accept, Accept-Language, Content-Language, Content-Type",
        )


if __name__ == "__main__":
    unittest.main()