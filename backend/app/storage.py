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

import logging
import re
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx

from . import config

# Decision (approved): signed URLs live for exactly 5 minutes.
SIGN_URL_TTL_SECONDS = 300

# Uploads/signing are tiny; fail fast rather than hang a submission.
REQUEST_TIMEOUT_SECONDS = 30.0

# One path segment of a bucket name or object key: plain, URL-safe text.
_SEGMENT = re.compile(r"[A-Za-z0-9._-]+")

# Diagnostics for failed Supabase calls. This module never logs anything about
# the REQUEST (headers, image bytes, URLs), only about the RESPONSE, and only
# after every secret-shaped value has been removed from it.
logger = logging.getLogger("campuslens.storage")
_SECRET_LIKE = re.compile(r"eyJ[A-Za-z0-9._-]+")          # JWT-shaped token
_URL_LIKE = re.compile(r"https?://\S+", re.IGNORECASE)      # any URL
_MAX_MESSAGE_CHARS = 200


class StorageError(Exception):
    """A Supabase Storage operation failed. Never carries the service key."""


def _redact(message: str, secret: Optional[str]) -> str:
    """Belt-and-braces: scrub the key should it ever reach a message."""
    if secret and secret in message:
        message = message.replace(secret, "[redacted]")
    return message


def _scrub(text: str, *secrets: Optional[str]) -> str:
    """Remove the key, the project URL/host, the bucket, the object path,
    every URL and every JWT-shaped token from ``text``."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return _URL_LIKE.sub("[redacted]", _SECRET_LIKE.sub("[redacted]", text))


def _is_safe(text: str, *secrets: Optional[str]) -> bool:
    """True only when no key, host, URL or JWT can still be present."""
    if any(secret and secret in text for secret in secrets):
        return False
    return not (_URL_LIKE.search(text) or _SECRET_LIKE.search(text))


def _diagnostic(
    phase: str,
    response: Any,
    secret: str,
    *,
    base: str = "",
    bucket: str = "",
    object_path: str = "",
) -> None:
    """Log WHY Supabase refused a request - never WHAT we sent.

    Always recorded: phase, HTTP status, Supabase error type, request id. The
    response message is recorded only when it can be proven free of the service
    key, the project URL/host, the bucket name, the object path, JWTs and
    URLs; otherwise it is omitted entirely. Request headers, request bodies,
    image bytes and signed URLs are never read here.
    """
    host = urlsplit(base).netloc if base else ""
    try:
        body = response.json()
    except ValueError:
        body = None

    fields: tuple[Optional[str], ...] = (secret, base, host, bucket, object_path)
    error = "unknown"
    message = ""
    if isinstance(body, dict):
        raw_error = body.get("error") or body.get("statusCode")
        if raw_error is not None:
            error = _scrub(str(raw_error), *fields)[:64] or "unknown"
        raw_message = body.get("message")
        if isinstance(raw_message, str) and raw_message.strip():
            candidate = _scrub(raw_message.strip(), *fields)
            # Final gate: if anything sensitive survived, drop the message.
            if _is_safe(candidate, secret, host):
                message = candidate[:_MAX_MESSAGE_CHARS]

    headers = getattr(response, "headers", None) or {}
    request_id = _scrub(str(headers.get("x-sb-request-id") or ""), secret)[:64] or "-"

    logger.warning(
        "supabase storage %s rejected (http=%s type=%s request_id=%s) message=%s",
        phase,
        response.status_code,
        error,
        request_id,
        message or "omitted",
    )


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
        _diagnostic("upload", response, key, base=base, bucket=bucket, object_path=path)
        # Only the status code is reported to the caller - never the body.
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
        _diagnostic("sign", response, key, base=base, bucket=bucket, object_path=path)
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