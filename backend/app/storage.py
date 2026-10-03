"""
CampusLens - Supabase Storage client (private bucket, server-side only).

What it does
------------
* Uploads complaint images to the private bucket configured on
  ``config.Settings`` at a caller-chosen object path
  (``uploads/<uuid>.<ext>`` - identical to the legacy local layout).
* Creates short-lived signed URLs (``SIGN_URL_TTL_SECONDS``) so a browser
  can view a private object; the URL is meant for an immediate redirect and
  is never persisted.

Security rules this module obeys
--------------------------------
* Settings are the ONLY source of configuration: ``.env`` files are never
  opened or parsed, and secrets never come from anywhere else.
* The bucket stays private. Only two Storage REST endpoints are used
  (``POST /storage/v1/object/{bucket}/{path}`` and
  ``POST /storage/v1/object/sign/{bucket}/{path}``); no public-bucket,
  policy or ACL API is ever called.
* The service-role key travels exclusively in the ``Authorization`` and
  ``apikey`` headers of requests addressed to the configured project URL.
  It never appears in
  a URL, a log line, or an exception message: every failure goes through
  :func:`_redact` and reports only a status code or error class.
* Uses plain ``httpx`` (already present via Starlette's TestClient) rather
  than the heavier official ``supabase`` SDK.

All failures raise :class:`StorageError`; routers map that to a generic
HTTP 502 without echoing the message back to API clients.
"""

from __future__ import annotations

import re
from typing import Optional

import httpx

from . import config

# Decision (approved): signed URLs live for exactly 5 minutes.
SIGN_URL_TTL_SECONDS = 300

# Uploads/signing are tiny; fail fast rather than hang a submission.
REQUEST_TIMEOUT_SECONDS = 30.0

# One path segment of a bucket name or object key: plain, URL-safe text.
_SEGMENT = re.compile(r"[A-Za-z0-9._-]+")


class StorageError(Exception):
    """A Supabase Storage operation failed. Never carries the service key."""


def _redact(message: str, secret: Optional[str]) -> str:
    """Belt-and-braces: scrub the key should it ever reach a message."""
    if secret and secret in message:
        message = message.replace(secret, "[redacted]")
    return message


def _require(settings: config.Settings) -> tuple[str, str, str]:
    """Return ``(base_url, service_key, bucket)`` or raise StorageError."""
    base = (settings.supabase_url or "").strip().rstrip("/")
    key = (settings.supabase_service_role_key or "").strip()
    bucket = (settings.supabase_bucket or "").strip()
    if not base or not key:
        raise StorageError("Supabase Storage is not configured.")
    if not _SEGMENT.fullmatch(bucket):
        raise StorageError("Invalid storage bucket name.")
    return base, key, bucket


def _validate_object_path(object_path: str) -> str:
    """Refuse anything that is not a plain relative path inside the bucket."""
    if not isinstance(object_path, str) or not object_path:
        raise StorageError("Invalid storage object path.")
    if object_path.startswith("/") or "\\" in object_path or ".." in object_path:
        raise StorageError("Invalid storage object path.")
    if any(not _SEGMENT.fullmatch(segment) for segment in object_path.split("/")):
        raise StorageError("Invalid storage object path.")
    return object_path


def upload(
    settings: config.Settings,
    data: bytes,
    *,
    content_type: str,
    object_path: str,
) -> str:
    """Store ``data`` in the private bucket at ``object_path``.

    Returns ``object_path`` unchanged so the caller persists exactly the
    key it asked for. Raises StorageError on any failure; the temporary
    local file (if any) is left untouched for the caller to decide about.
    """
    base, key, bucket = _require(settings)
    path = _validate_object_path(object_path)
    url = f"{base}/storage/v1/object/{bucket}/{path}"
    headers = {
        "Authorization": f"Bearer {key}",
        # Supabase authenticates project credentials through the ``apikey``
        # header; sending it alongside Authorization is what makes this work
        # for both a legacy service_role JWT and a newer sb_secret_ key.
        "apikey": key,
        "Content-Type": content_type,
        "x-upsert": "false",  # a uuid object name must never overwrite
    }
    try:
        response = httpx.post(
            url, content=data, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
        )
    except httpx.HTTPError as exc:
        raise StorageError(
            _redact(f"Supabase Storage is unreachable ({type(exc).__name__}).", key)
        ) from exc
    if not 200 <= response.status_code < 300:
        # Only the status code is reported - never the response body.
        raise StorageError(
            _redact(
                f"Supabase Storage rejected the upload (HTTP {response.status_code}).",
                key,
            )
        )
    return path


def signed_url(
    settings: config.Settings,
    object_path: str,
    *,
    expires_in: int = SIGN_URL_TTL_SECONDS,
) -> str:
    """Create a short-lived signed URL for a private object.

    The URL goes straight to the browser as a redirect target and must
    never be stored: Supabase only honours it for ``expires_in`` seconds.
    """
    base, key, bucket = _require(settings)
    path = _validate_object_path(object_path)
    url = f"{base}/storage/v1/object/sign/{bucket}/{path}"
    headers = {"Authorization": f"Bearer {key}", "apikey": key}
    try:
        response = httpx.post(
            url,
            json={"expiresIn": int(expires_in)},
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise StorageError(
            _redact(f"Supabase Storage is unreachable ({type(exc).__name__}).", key)
        ) from exc
    if not 200 <= response.status_code < 300:
        raise StorageError(
            _redact(
                f"Supabase Storage could not sign the object "
                f"(HTTP {response.status_code}).",
                key,
            )
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise StorageError(
            "Supabase Storage returned an unreadable response."
        ) from exc
    signed_path = payload.get("signedURL") if isinstance(payload, dict) else None
    if not isinstance(signed_path, str) or not signed_path:
        raise StorageError("Supabase Storage returned no signed URL.")
    if signed_path.startswith(("http://", "https://")):
        return signed_path
    if not signed_path.startswith("/"):
        signed_path = "/" + signed_path
    return f"{base}{signed_path}"