"""
CampusLens - application settings.

Single source of truth for configuration. Secrets are loaded from the process
environment (deployment platforms inject them there) with an optional
``backend/.env`` fallback for local development only.

Every secret field is ``repr=False`` so it cannot leak into a log line, a
traceback, a pytest failure report or an error message.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import scoring, storage

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Private Supabase Storage bucket holding complaint images.
DEFAULT_BUCKET = "CLimage"

# Local Vite dev origins. Deliberately never "*".
DEFAULT_CORS_ORIGINS: tuple[str, ...] = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)

SERVICE_NAME = "campuslens-api"
SERVICE_VERSION = "2.0.0"


class ConfigError(RuntimeError):
    """Raised when the process environment is missing something required."""


def _load_dotenv() -> None:
    """Populate os.environ from backend/.env if present.

    Local development convenience only. Real values always come from the
    environment; existing environment variables are never overwritten.
    """
    path = BACKEND_DIR / ".env"
    if not path.is_file():
        return
    try:
        from dotenv import dotenv_values

        for key, value in dotenv_values(path).items():
            if value is not None:
                os.environ.setdefault(key, value)
    except Exception:
        # A malformed .env must never stop the app from starting.
        pass


@dataclass(frozen=True)
class Settings:
    """Everything the API needs to know about where things live."""

    # repr=False on every secret: never appears in logs or tracebacks.
    database_url: str = field(repr=False)
    supabase_url: str = field(repr=False)
    supabase_anon_key: str = field(repr=False)
    supabase_service_role_key: str = field(repr=False)
    bucket: str = DEFAULT_BUCKET

    max_upload_bytes: int = 5 * 1024 * 1024
    ai_enabled: bool = True
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    service_name: str = SERVICE_NAME
    service_version: str = SERVICE_VERSION

    # Rate limiting & size limits
    rate_limit_enabled: bool = True
    rate_limit_submit_per_minute: int = 15
    rate_limit_auth_per_minute: int = 60
    rate_limit_public_per_minute: int = 60
    rate_limit_general_per_minute: int = 120
    max_request_body_bytes: int = 10 * 1024 * 1024
    max_json_body_bytes: int = 1 * 1024 * 1024

    @property
    def allowed_mime_types(self) -> frozenset[str]:
        return scoring.ALLOWED_IMAGE_MIME

    @property
    def allowed_extensions(self) -> frozenset[str]:
        return scoring.ALLOWED_IMAGE_EXTENSIONS


def _require(name: str) -> str:
    """Read a required variable or explain precisely what is missing.

    The variable NAME is reported; its value never is.
    """
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise ConfigError(
            f"Missing required environment variable {name}. "
            "Copy backend/.env.example to backend/.env and fill it in."
        )
    return value


def settings_from_env(*, require: bool = True) -> Settings:
    """Build Settings from the environment.

    ``require=False`` is used by unit tests that inject their own fakes; it
    fills unset variables with obvious placeholders so importing the module can
    never fail in CI.
    """
    _load_dotenv()

    def get(name: str, placeholder: str) -> str:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
        if require:
            _require(name)
        return placeholder

    def _bool(name: str, default: bool) -> bool:
        raw = (os.environ.get(name) or "").strip().lower()
        if not raw:
            return default
        return raw not in {"0", "false", "no", "off"}

    def _int(name: str, default: int) -> int:
        raw = (os.environ.get(name) or "").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    cors_raw = (os.environ.get("CORS_ORIGINS") or "").strip()
    cors = (
        tuple(o.strip() for o in cors_raw.split(",") if o.strip())
        if cors_raw
        else DEFAULT_CORS_ORIGINS
    )

    ai_raw = (os.environ.get("AI_ENABLED") or "").strip().lower()

    return Settings(
        database_url=get("DATABASE_URL", "postgresql://placeholder/placeholder"),
        supabase_url=get("SUPABASE_URL", "https://placeholder.supabase.co"),
        supabase_anon_key=get("SUPABASE_ANON_KEY", "placeholder-anon-key"),
        supabase_service_role_key=get(
            "SUPABASE_SERVICE_ROLE_KEY", "placeholder-service-key"
        ),
        bucket=(os.environ.get("SUPABASE_BUCKET") or "").strip() or DEFAULT_BUCKET,
        max_upload_bytes=scoring.MAX_UPLOAD_BYTES,
        ai_enabled=ai_raw not in {"0", "false", "no", "off"},
        cors_origins=cors,
        rate_limit_enabled=_bool("RATE_LIMIT_ENABLED", True),
        rate_limit_submit_per_minute=_int("RATE_LIMIT_SUBMIT_PER_MINUTE", 15),
        rate_limit_auth_per_minute=_int("RATE_LIMIT_AUTH_PER_MINUTE", 60),
        rate_limit_public_per_minute=_int("RATE_LIMIT_PUBLIC_PER_MINUTE", 60),
        rate_limit_general_per_minute=_int("RATE_LIMIT_GENERAL_PER_MINUTE", 120),
        max_request_body_bytes=_int("MAX_REQUEST_BODY_BYTES", 10 * 1024 * 1024),
        max_json_body_bytes=_int("MAX_JSON_BODY_BYTES", 1 * 1024 * 1024),
    )


def default_settings() -> Settings:
    """Settings for a normally started app."""
    return settings_from_env(require=True)