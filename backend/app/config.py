"""
CampusLens - application settings.

Paths and limits live in one place so the API can be pointed at throwaway
temporary locations during tests.

Nothing here re-implements logic from the other modules: every value is taken
from database.py, priority.py or gemini.py so there is a single source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
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


def default_settings() -> Settings:
    """The real settings used when the app is started normally."""
    return Settings(
        db_path=database.DB_PATH,
        upload_dir=database.BACKEND_DIR / "uploads",
        max_upload_bytes=gemini.MAX_IMAGE_BYTES,
        allowed_mime_types=frozenset(gemini.ALLOWED_IMAGE_TYPES),
        allowed_extensions=ALLOWED_IMAGE_EXTENSIONS,
        cors_origins=DEFAULT_CORS_ORIGINS,
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
    }
    values.update(overrides)
    return Settings(**values)