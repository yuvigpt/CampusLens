"""
CampusLens - Supabase Storage client (private bucket, server-side only).

What it does
------------
* Uploads a complaint image to the private bucket at the agreed object path
  ``<student_id>/<uuid>.<ext>`` - the first path segment is the owning
  student's Supabase Auth user id, exactly as migration 009's storage policies
  expect.
* Creates short-lived signed URLs so an authorised browser can view a private
  object. Signed URLs are never persisted and never returned to a caller who
  is not entitled to the underlying complaint.

Security rules this module obeys
--------------------------------
* The bucket stays private. Only two Storage REST endpoints are used (object
  upload and object sign); no public-bucket, policy or ACL API is ever called,
  so this module can never widen access.
* The service-role key travels exclusively in the ``Authorization`` and
  ``apikey`` headers of requests addressed to the configured project URL. It
  never appears in a URL, a log line, or an exception message.
* The client's filename is never used as a path. The extension comes from the
  sniffed content type and the object name is a fresh uuid4.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Optional
from urllib.parse import quote

import httpx

from . import config

logger = logging.getLogger("campuslens.storage")

SIGN_URL_TTL_SECONDS = 300
REQUEST_TIMEOUT_SECONDS = 30.0

_SECRET_LIKE = re.compile(r"eyJ[A-Za-z0-9._-]+")
_URL_LIKE = re.compile(r"https?://\S+", re.IGNORECASE)
_MAX_MESSAGE_CHARS = 200

# Canonical extension for each sniffed MIME type. Only these three are stored.
MIME_TO_EXTENSION: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

# Magic bytes. The client's Content-Type header is NOT trusted.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)


class StorageError(RuntimeError):
    """A Supabase Storage operation failed. Never carries the service key."""


class InvalidImage(ValueError):
    """The uploaded bytes are not an accepted image."""


def _scrub(text: str, *secrets: Optional[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return _URL_LIKE.sub("[redacted]", _SECRET_LIKE.sub("[redacted]", text))


def sniff_image_type(data: bytes) -> str:
    """Return the MIME type proven by the bytes themselves.

    Raises InvalidImage when the content is not one of the three accepted
    image formats. This is what makes a spoofed Content-Type useless.
    """
    if not data:
        raise InvalidImage("The uploaded image is empty.")

    for prefix, mime in _MAGIC:
        if data.startswith(prefix):
            return mime

    # RIFF....WEBP - the format tag sits at offset 8.
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"

    raise InvalidImage(
        "Unsupported image format. Allowed: image/jpeg, image/png, image/webp."
    )
def _headers(settings: config.Settings) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "apikey": settings.supabase_service_role_key,
    }


def delete_image(settings: config.Settings, object_path: str) -> None:
    """Best-effort removal of one object (used when a complaint is deleted).

    A failure is logged, never raised: the row is already gone, and an orphaned
    image must not resurrect the complaint or block the deletion.
    """
    url = (
        f"{settings.supabase_url.rstrip('/')}/storage/v1/object/"
        f"{settings.bucket}/{quote(object_path, safe='/')}"
    )
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = client.delete(url, headers=_headers(settings))
    except Exception as exc:  # noqa: BLE001 - transport; log type only
        logger.warning("storage delete transport failure (%s)", type(exc).__name__)
        return
    # 404 means the object is already gone - the desired end state.
    if response.status_code >= 300 and response.status_code != 404:
        detail = _scrub(
            response.text or "", settings.supabase_service_role_key, object_path
        )[:_MAX_MESSAGE_CHARS]
        logger.warning(
            "storage delete rejected (http=%s) %s", response.status_code, detail
        )


def upload_image(
    settings: config.Settings, *, object_path: str, data: bytes, mime: str
) -> str:
    """Upload one image and return its object path.

    Raises StorageError on any failure so the caller can report a generic 502
    without leaking the project URL, the bucket or the key.
    """
    url = (
        f"{settings.supabase_url.rstrip('/')}/storage/v1/object/"
        f"{settings.bucket}/{quote(object_path, safe='/')}"
    )
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = client.put(
                url, content=data, headers={**_headers(settings), "Content-Type": mime}
            )
    except Exception as exc:
        logger.error("storage upload transport failure (%s)", type(exc).__name__)
        raise StorageError("Image storage unavailable.") from None

    if response.status_code >= 300:
        detail = _scrub(
            response.text or "", settings.supabase_service_role_key, object_path
        )[:_MAX_MESSAGE_CHARS]
        logger.error("storage upload rejected (http=%s) %s", response.status_code, detail)
        raise StorageError("Image storage unavailable.")

    return object_path


def create_signed_url(settings: config.Settings, *, object_path: str) -> str:
    """Short-lived signed URL for an authorised viewer."""
    url = (
        f"{settings.supabase_url.rstrip('/')}/storage/v1/object/sign/"
        f"{settings.bucket}/{quote(object_path, safe='/')}"
    )
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = client.post(
                url,
                json={"expiresIn": str(SIGN_URL_TTL_SECONDS)},
                headers={**_headers(settings), "Content-Type": "application/json"},
            )
    except Exception as exc:
        logger.error("storage sign transport failure (%s)", type(exc).__name__)
        raise StorageError("Image storage unavailable.") from None

    if response.status_code >= 300:
        logger.error("storage sign rejected (http=%s)", response.status_code)
        raise StorageError("Image storage unavailable.")

    try:
        signed_path = response.json().get("signedURL")
    except ValueError:
        raise StorageError("Image storage unavailable.") from None

    if not signed_path:
        raise StorageError("Image storage unavailable.")

    # Supabase Storage returns paths like "/object/sign/..." omitting the
    # "/storage/v1" prefix. Ensure the canonical /storage/v1 prefix is present.
    if not signed_path.startswith("/storage/v1"):
        if not signed_path.startswith("/"):
            signed_path = "/" + signed_path
        signed_path = f"/storage/v1{signed_path}"

    return f"{settings.supabase_url.rstrip('/')}{signed_path}"


def build_object_path(student_id: str, data: bytes) -> tuple[str, str]:
    """Return (object_path, mime) using the agreed <student_id>/<uuid>.<ext>.

    The student id is the verified caller's own Auth user id, so the first path
    segment always matches the prefix migration 009 requires.
    """
    mime = sniff_image_type(data)
    extension = MIME_TO_EXTENSION[mime]
    object_path = f"{student_id}/{uuid.uuid4().hex}.{extension}"
    return object_path, mime