"""
CampusLens - Production security middleware and rate limiting.

Deliberate design choices:
- Thread-safe sliding-window rate limiting with per-route bucket limits.
- Sensitive endpoint abuse protection (complaint creation + AI analysis, auth, public feed).
- Authenticated user requests are bucketed by hashed token; unauthenticated by client IP.
- Request body size limits prevent denial-of-service from oversized or chunked payloads.
- Essential production security headers (CSP, HSTS, X-Frame-Options, X-Content-Type-Options).
- Cache-Control: no-store on private/authenticated API routes.
- Never prints, logs or echoes secrets, tokens, or credentials.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import defaultdict
from typing import Any, Optional, Tuple

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from . import config

logger = logging.getLogger("campuslens.security")

# Modern security headers for all responses
BASE_SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"geolocation=(), camera=(), microphone=()"),
]

# Sensitive API routes must never be cached by browsers or intermediate proxies
NO_CACHE_HEADERS: list[tuple[bytes, bytes]] = [
    (b"cache-control", b"no-store, no-cache, must-revalidate, private"),
    (b"pragma", b"no-cache"),
]


class RequestSizeExceeded(Exception):
    """Raised when an incoming request exceeds allowed body size limits."""


class RateLimiter:
    """Thread-safe in-memory sliding-window rate limiter."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        submit_limit: int = 15,
        auth_limit: int = 60,
        public_limit: int = 60,
        general_limit: int = 120,
        window_seconds: int = 60,
    ) -> None:
        self.enabled = enabled
        self.submit_limit = submit_limit
        self.auth_limit = auth_limit
        self.public_limit = public_limit
        self.general_limit = general_limit
        self.window_seconds = window_seconds

        self._lock = threading.Lock()
        self._history: dict[str, list[float]] = defaultdict(list)
        self._last_cleanup = time.monotonic()

    def get_bucket_limit(self, method: str, path: str) -> Optional[Tuple[str, int]]:
        """Return (bucket_name, limit_per_window) or None if exempt."""
        normalized = path.rstrip("/") or "/"
        # Exempt routes: health probes and root metadata
        if normalized in {"/", "/health", "/api/health"}:
            return None
        if method == "OPTIONS":
            return None

        # 1. Complaint creation (triggers file upload + expensive Gemini AI analysis)
        if method == "POST" and normalized == "/api/complaints":
            return ("submit", self.submit_limit)

        # 2. Auth identity / profile verification
        if normalized == "/api/me":
            return ("auth", self.auth_limit)

        # 3. Public feeds (unauthenticated/community)
        if normalized in {"/api/public/complaints", "/api/community/campus"}:
            return ("public", self.public_limit)

        # 4. All other API endpoints
        if normalized.startswith("/api/"):
            return ("general", self.general_limit)

        return None

    def check(
        self, key: str, bucket: str, limit: int
    ) -> Tuple[bool, int, int, int, int]:
        """Check if request is allowed under the sliding window.

        Returns (allowed, limit, remaining, reset_epoch, retry_after).
        """
        if not self.enabled:
            now = int(time.time())
            return (True, limit, limit, now + self.window_seconds, 0)

        now = time.time()
        bucket_key = f"{bucket}:{key}"
        cutoff = now - self.window_seconds

        with self._lock:
            # Periodic cleanup every 5 minutes or when table grows
            now_mono = time.monotonic()
            if now_mono - self._last_cleanup > 300 or len(self._history) > 5000:
                self._cleanup(cutoff)
                self._last_cleanup = now_mono

            timestamps = [t for t in self._history[bucket_key] if t > cutoff]
            if len(timestamps) >= limit:
                # Rate limited
                oldest = timestamps[0]
                retry_after = max(1, int(oldest + self.window_seconds - now) + 1)
                reset_epoch = int(oldest + self.window_seconds)
                self._history[bucket_key] = timestamps
                return (False, limit, 0, reset_epoch, retry_after)

            timestamps.append(now)
            self._history[bucket_key] = timestamps
            remaining = max(0, limit - len(timestamps))
            reset_epoch = int(now + self.window_seconds)
            return (True, limit, remaining, reset_epoch, 0)

    def _cleanup(self, cutoff: float) -> None:
        """Prune expired entries to prevent unbounded memory growth."""
        keys_to_delete = []
        for k, ts_list in self._history.items():
            valid = [t for t in ts_list if t > cutoff]
            if not valid:
                keys_to_delete.append(k)
            else:
                self._history[k] = valid
        for k in keys_to_delete:
            del self._history[k]

    def reset(self) -> None:
        """Clear all rate limiting history (used by tests)."""
        with self._lock:
            self._history.clear()


def extract_client_key(
    headers: Headers, client_host: Optional[str], bucket: str = "general"
) -> str:
    """Derive rate-limit key prioritizing authenticated token hash over IP.

    Public endpoints (e.g. /api/public/complaints) are strictly keyed by IP,
    preventing scrapers from bypassing quotas by cycling arbitrary dummy Bearer
    tokens on unauthenticated routes. Authenticated routes key by token hash,
    which ensures students sharing a hostel NAT/Wi-Fi IP do not share quotas.
    """
    if bucket != "public":
        auth_header = headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
            if token:
                # Hash token so we don't store or echo credentials in memory or logs
                token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
                return f"tok:{token_hash}"

    # Fallback to client IP
    forwarded = headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
        # Strip port if present in IPv4 (e.g. 1.2.3.4:5678)
        if ":" in client_ip and not client_ip.startswith("[") and client_ip.count(":") == 1:
            client_ip = client_ip.split(":")[0]
        if client_ip:
            return f"ip:{client_ip[:64]}"

    return f"ip:{client_host or '127.0.0.1'}"


class BodySizeGuard:
    """ASGI receive wrapper that guards against oversized streaming payloads."""

    def __init__(self, receive: Receive, max_bytes: int):
        self._receive = receive
        self._max_bytes = max_bytes
        self._read_bytes = 0

    async def __call__(self) -> dict[str, Any]:
        message = await self._receive()
        if message["type"] == "http.request":
            body = message.get("body", b"")
            self._read_bytes += len(body)
            if self._read_bytes > self._max_bytes:
                raise RequestSizeExceeded(
                    f"Request entity too large (exceeded {self._max_bytes} bytes)."
                )
        return message


class SecurityAndRateLimitMiddleware:
    """Pure ASGI middleware enforcing security headers, request size, and rate limits."""

    def __init__(
        self,
        app: ASGIApp,
        settings: config.Settings,
        limiter: RateLimiter,
    ) -> None:
        self.app = app
        self.settings = settings
        self.limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        method = scope.get("method", "GET")
        path = scope.get("path", "")
        client_host = scope.get("client", (None, None))[0] if scope.get("client") else None

        # Determine whether request is over HTTPS (direct or through Render reverse proxy)
        is_https = (
            scope.get("scheme") == "https"
            or headers.get("x-forwarded-proto", "").lower() == "https"
        )

        # 1. Determine request body size limit
        normalized_path = path.rstrip("/") or "/"
        if method == "POST" and normalized_path == "/api/complaints":
            max_body_bytes = self.settings.max_request_body_bytes
        else:
            max_body_bytes = self.settings.max_json_body_bytes

        # Check Content-Length if provided upfront
        content_length_str = headers.get("content-length")
        if content_length_str:
            try:
                content_length = int(content_length_str)
                if content_length > max_body_bytes:
                    response = JSONResponse(
                        status_code=413,
                        content={"detail": "Request entity too large."},
                        headers={
                            "x-content-type-options": "nosniff",
                            "x-frame-options": "DENY",
                        },
                    )
                    await response(scope, receive, send)
                    return
            except ValueError:
                pass

        # 2. Check rate limit
        bucket_info = self.limiter.get_bucket_limit(method, path)
        rate_info: Optional[Tuple[int, int, int]] = None
        if bucket_info is not None:
            bucket_name, limit = bucket_info
            key = extract_client_key(headers, client_host, bucket_name)
            allowed, limit, remaining, reset_epoch, retry_after = self.limiter.check(
                key, bucket_name, limit
            )
            rate_info = (limit, remaining, reset_epoch)

            if not allowed:
                logger.warning(
                    "Rate limit exceeded on '%s %s' (bucket=%s, retry_after=%ss)",
                    method,
                    path,
                    bucket_name,
                    retry_after,
                )
                response = JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Please try again later."},
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(reset_epoch),
                        "x-content-type-options": "nosniff",
                        "x-frame-options": "DENY",
                    },
                )
                await response(scope, receive, send)
                return

        # 3. Intercept response to inject security headers and rate-limit headers
        async def send_with_security_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                existing_headers = list(message.get("headers", []))
                existing_names = {name.lower() for name, _ in existing_headers}

                # Attach base security headers
                for name, value in BASE_SECURITY_HEADERS:
                    if name.lower() not in existing_names:
                        existing_headers.append((name, value))

                # HSTS: RFC 6797 compliant (only on secure connections)
                if is_https and b"strict-transport-security" not in existing_names:
                    existing_headers.append(
                        (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
                    )

                # CSP: API routes get strict 'none'; docs routes allow Swagger UI CDN
                if b"content-security-policy" not in existing_names:
                    if normalized_path in {"/docs", "/redoc", "/openapi.json"}:
                        csp = (
                            b"default-src 'self'; "
                            b"script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                            b"style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                            b"img-src 'self' data: https://fastapi.tiangolo.com; "
                            b"frame-ancestors 'none'"
                        )
                    else:
                        csp = b"default-src 'none'; frame-ancestors 'none'"
                    existing_headers.append((b"content-security-policy", csp))

                # Attach no-cache headers to sensitive API routes
                if path.startswith("/api/") and not path.endswith("/health"):
                    for name, value in NO_CACHE_HEADERS:
                        if name.lower() not in existing_names:
                            existing_headers.append((name, value))

                # Attach rate limit headers
                if rate_info is not None:
                    lim, rem, res = rate_info
                    existing_headers.append((b"x-ratelimit-limit", str(lim).encode("ascii")))
                    existing_headers.append((b"x-ratelimit-remaining", str(rem).encode("ascii")))
                    existing_headers.append((b"x-ratelimit-reset", str(res).encode("ascii")))

                message["headers"] = existing_headers

            await send(message)

        # 4. Stream guard for chunked bodies
        guarded_receive = BodySizeGuard(receive, max_body_bytes)
        try:
            await self.app(scope, guarded_receive, send_with_security_headers)
        except RequestSizeExceeded:
            response = JSONResponse(
                status_code=413,
                content={"detail": "Request entity too large."},
                headers={
                    "x-content-type-options": "nosniff",
                    "x-frame-options": "DENY",
                },
            )
            await response(scope, receive, send)
