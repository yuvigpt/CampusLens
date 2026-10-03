"""
CampusLens - application settings.

Paths and limits live in one place so the API can be pointed at throwaway
temporary locations during tests.

Nothing here re-implements logic from the other modules: every value is taken
from database.py, priority.py or gemini.py so there is a single source of truth.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import database, gemini

# Image extensions we are willing to store and serve back.
ALLOWED_IMAGE_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".webp"})

# Local Vite dev-server origins. Deliberately NOT "*".
DEFAULT_CORS_ORIGINS: tuple[str, ...] = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)

SERVICE_NAME = "campuslens-api"
SERVICE_VERSION = "1.0.0"

# Private bucket that holds complaint images in Supabase Storage.
DEFAULT_SUPABASE_BUCKET = "imagestorage"


@dataclass(frozen=True)
class Settings:
    """Everything the API needs to know about where things live."""

    db_path: Path
    upload_dir: Path
    max_upload_bytes: int
    allowed_mime_types: frozenset[str]
    allowed_extensions: frozenset[str]
    cors_origins: tuple[str, ...]
    service_name: str = SERVICE_NAME
    service_version: str = SERVICE_VERSION

    # PostgreSQL via DATABASE_URL (deployment). Populated only from the process
    # environment by database_url_from_env(): when it is missing or blank the
    # app keeps using SQLite exactly as before (the local default). repr=False
    # so the URL - which embeds credentials - can never appear in logs,
    # tracebacks or test output.
    database_url: str | None = field(default=None, repr=False)

    # Supabase Storage (private bucket). Populated only from the process
    # environment by supabase_settings_from_env(): when either the URL or
    # the key is missing the whole feature stays off and local behavior is
    # unchanged. The service-role key is repr=False so it can never appear
    # in logs, tracebacks or test output.
    supabase_url: str | None = None
    supabase_service_role_key: str | None = field(default=None, repr=False)
    supabase_bucket: str = DEFAULT_SUPABASE_BUCKET

    @property
    def supabase_enabled(self) -> bool:
        """True only when BOTH a project URL and a service-role key are set.

        With nothing configured (normal local development) every Supabase
        code path is skipped and the app behaves exactly as it always has.
        """
        return bool(
            (self.supabase_url or "").strip()
            and (self.supabase_service_role_key or "").strip()
        )


def parse_cors_origins(raw: str | None) -> tuple[str, ...]:
    """Turn a comma-separated CORS value into a tuple of origins.

    ``None`` (unset), an empty string, or a value made only of separators and
    whitespace all fall back to ``DEFAULT_CORS_ORIGINS`` so local development
    keeps working exactly as before. Every entry is trimmed and empty entries
    are dropped, so ``" a , , b "`` becomes ``("a", "b")``.

    A wildcard is never produced here - callers must not turn this into ``*``.
    """
    if raw is None:
        return DEFAULT_CORS_ORIGINS
    origins = tuple(origin.strip() for origin in raw.split(",") if origin.strip())
    return origins or DEFAULT_CORS_ORIGINS


def cors_origins_from_env() -> tuple[str, ...]:
    """CORS origins from the ``CORS_ORIGINS`` environment variable.

    Read from the process environment only (deployment platforms inject it
    there); ``.env`` files are deliberately not consulted.
    """
    return parse_cors_origins(os.environ.get("CORS_ORIGINS"))


def supabase_settings_from_env() -> tuple[str | None, str | None, str]:
    """Supabase Storage settings from the process environment.

    Reads ``SUPABASE_URL``, ``SUPABASE_SERVICE_ROLE_KEY`` and
    ``SUPABASE_BUCKET`` only - deployment platforms inject them there and
    ``.env`` files are deliberately never opened or parsed. Values are
    stripped; a blank URL or key collapses to ``None`` (feature off) and a
    blank bucket falls back to ``DEFAULT_SUPABASE_BUCKET``. The key itself
    is never logged or included in any error message.
    """
    url = (os.environ.get("SUPABASE_URL") or "").strip() or None
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip() or None
    bucket = (os.environ.get("SUPABASE_BUCKET") or "").strip() or DEFAULT_SUPABASE_BUCKET
    return url, key, bucket


def database_url_from_env() -> str | None:
    """PostgreSQL connection URL from the ``DATABASE_URL`` environment variable.

    Read from the process environment only (deployment platforms inject it
    there); ``.env`` files are deliberately not consulted. Unset or blank
    values collapse to ``None`` -> SQLite, the local default, so behaviour is
    byte-identical whenever the variable is absent. The legacy
    ``postgres://`` spelling is normalized to ``postgresql://``. The value is
    never logged or included in any error message.
    """
    raw = (os.environ.get("DATABASE_URL") or "").strip()
    if not raw:
        return None
    if raw.startswith("postgres://"):
        return "postgresql://" + raw[len("postgres://") :]
    return raw


def default_settings() -> Settings:
    """The real settings used when the app is started normally.

    ``cors_origins`` honours ``CORS_ORIGINS``, the Supabase fields honour
    ``SUPABASE_URL`` / ``SUPABASE_SERVICE_ROLE_KEY`` / ``SUPABASE_BUCKET`` and
    ``database_url`` honours ``DATABASE_URL``; unset or empty values fall back
    to the safe local defaults (localhost origins, Supabase Storage disabled,
    SQLite).
    """
    supabase_url, supabase_service_role_key, supabase_bucket = supabase_settings_from_env()
    return Settings(
        db_path=database.DB_PATH,
        upload_dir=database.BACKEND_DIR / "uploads",
        max_upload_bytes=gemini.MAX_IMAGE_BYTES,
        allowed_mime_types=frozenset(gemini.ALLOWED_IMAGE_TYPES),
        allowed_extensions=ALLOWED_IMAGE_EXTENSIONS,
        cors_origins=cors_origins_from_env(),
        database_url=database_url_from_env(),
        supabase_url=supabase_url,
        supabase_service_role_key=supabase_service_role_key,
        supabase_bucket=supabase_bucket,
    )


def settings_for(db_path, upload_dir, **overrides) -> Settings:
    """Build Settings for a specific database and upload folder (used by tests)."""
    base = default_settings()
    values = {
        "db_path": Path(db_path),
        "upload_dir": Path(upload_dir),
        "max_upload_bytes": base.max_upload_bytes,
        "allowed_mime_types": base.allowed_mime_types,
        "allowed_extensions": base.allowed_extensions,
        "cors_origins": base.cors_origins,
        # Tests always run on SQLite: force None so a developer's
        # DATABASE_URL can never reach the test suite (API test env cleanup
        # strips the variable too). Individual tests may override explicitly.
        "database_url": None,
        "supabase_url": base.supabase_url,
        "supabase_service_role_key": base.supabase_service_role_key,
        "supabase_bucket": base.supabase_bucket,
    }
    values.update(overrides)
    return Settings(**values)