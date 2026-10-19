"""
Tests for production security hardening:
- API rate limiting & headers
- Expensive endpoint protection (/api/complaints, /api/me, /api/public/complaints)
- Request body size limits (413)
- Security headers (CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Cache-Control)
- Token length validation (401)
- Malformed UUID input handling (404 instead of 503)
- CORS headers & preflight
"""

from __future__ import annotations

import httpx
import pytest
from unittest.mock import patch

from app import config, security, storage, database, auth
from app.main import create_app
from fastapi.testclient import TestClient


def _student_headers(client, token_name="student_a"):
    return {"Authorization": f"Bearer {client.tokens[token_name]}"}


def _admin_headers(client):
    return {"Authorization": f"Bearer {client.tokens['admin']}"}


# ---------------------------------------------------------------------------
# Rate Limiting Tests
# ---------------------------------------------------------------------------
def test_complaint_submit_rate_limiting(client, monkeypatch):
    """POST /api/complaints (expensive endpoint) throttles when limit is exceeded."""
    limiter = client.app.state.rate_limiter
    limiter.reset()

    # Configure a small limit for testing: 3 per window
    monkeypatch.setattr(limiter, "submit_limit", 3)

    payload = {"description": "Water leaking from ceiling on third floor", "location": "Library"}

    # Submissions 1, 2, 3 succeed
    for i in range(3):
        res = client.post("/api/complaints", data=payload, headers=_student_headers(client))
        assert res.status_code == 201
        assert "X-RateLimit-Limit" in res.headers
        assert res.headers["X-RateLimit-Limit"] == "3"
        assert int(res.headers["X-RateLimit-Remaining"]) == 2 - i

    # Submission 4 is blocked with 429 Too Many Requests
    blocked = client.post("/api/complaints", data=payload, headers=_student_headers(client))
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "Too many requests. Please try again later."
    assert "Retry-After" in blocked.headers
    assert int(blocked.headers["Retry-After"]) >= 1
    assert blocked.headers["X-RateLimit-Remaining"] == "0"


def test_auth_me_rate_limiting(client, monkeypatch):
    """GET /api/me throttles when request limit is reached."""
    limiter = client.app.state.rate_limiter
    limiter.reset()
    monkeypatch.setattr(limiter, "auth_limit", 3)

    for i in range(3):
        res = client.get("/api/me", headers=_student_headers(client))
        assert res.status_code == 200

    blocked = client.get("/api/me", headers=_student_headers(client))
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


def test_public_feed_rate_limiting(client, monkeypatch):
    """GET /api/public/complaints throttles unauthenticated scrapers."""
    limiter = client.app.state.rate_limiter
    limiter.reset()
    monkeypatch.setattr(limiter, "public_limit", 3)

    for i in range(3):
        res = client.get("/api/public/complaints")
        assert res.status_code == 200

    blocked = client.get("/api/public/complaints")
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


def test_public_feed_cannot_bypass_with_dummy_bearer_tokens(client, monkeypatch):
    """Scrapers cannot bypass public feed rate limits by cycling random dummy Bearer tokens."""
    limiter = client.app.state.rate_limiter
    limiter.reset()
    monkeypatch.setattr(limiter, "public_limit", 2)

    # First 2 requests with different dummy tokens
    assert client.get("/api/public/complaints", headers={"Authorization": "Bearer dummy_token_1"}).status_code == 200
    assert client.get("/api/public/complaints", headers={"Authorization": "Bearer dummy_token_2"}).status_code == 200

    # 3rd request with yet another token is still blocked because public endpoints key by IP
    blocked = client.get("/api/public/complaints", headers={"Authorization": "Bearer dummy_token_3"})
    assert blocked.status_code == 429


def test_rate_limiting_user_isolation(client, monkeypatch):
    """Student A being throttled must not block Student B."""
    limiter = client.app.state.rate_limiter
    limiter.reset()
    monkeypatch.setattr(limiter, "submit_limit", 2)

    payload = {"description": "Broken door latch in room 204", "location": "Hall 1"}

    # Student A uses all quota
    assert client.post("/api/complaints", data=payload, headers=_student_headers(client, "student_a")).status_code == 201
    assert client.post("/api/complaints", data=payload, headers=_student_headers(client, "student_a")).status_code == 201
    assert client.post("/api/complaints", data=payload, headers=_student_headers(client, "student_a")).status_code == 429

    # Student B still has full quota and succeeds
    res_b = client.post("/api/complaints", data=payload, headers=_student_headers(client, "student_b"))
    assert res_b.status_code == 201


def test_exempt_routes_are_not_rate_limited(client, monkeypatch):
    """Health probes, root, and OPTIONS are exempt from rate limiting."""
    limiter = client.app.state.rate_limiter
    limiter.reset()
    monkeypatch.setattr(limiter, "general_limit", 2)

    # Health probes can be queried repeatedly without getting 429
    for _ in range(10):
        assert client.get("/api/health").status_code == 200
        assert client.get("/").status_code == 200


def test_rate_limiting_can_be_disabled(settings, store, tokens, jwks):
    """Setting rate_limit_enabled=False bypasses throttling entirely."""
    disabled_settings = config.Settings(
        database_url=settings.database_url,
        supabase_url=settings.supabase_url,
        supabase_anon_key=settings.supabase_anon_key,
        supabase_service_role_key=settings.supabase_service_role_key,
        bucket="CLimage",
        rate_limit_enabled=False,
        rate_limit_submit_per_minute=1,
    )
    app = create_app(disabled_settings)
    with TestClient(app) as test_c:
        test_c.tokens = tokens
        # Verify rate limiting is bypassed
        headers = {"Authorization": f"Bearer {tokens['student_a']}"}
        # Calling me endpoint multiple times
        for _ in range(5):
            res = test_c.get("/api/me", headers=headers)
            # Will be 200 or 503 depending on fake session, but crucially NOT 429
            assert res.status_code != 429


# ---------------------------------------------------------------------------
# Security Headers Tests
# ---------------------------------------------------------------------------
def test_production_security_headers_present(client):
    """All responses must contain essential security headers, and HTTPS includes HSTS."""
    res = client.get("/api/health", headers={"X-Forwarded-Proto": "https"})
    assert res.status_code == 200

    headers = res.headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "geolocation=()" in headers["permissions-policy"]
    assert "default-src 'none'" in headers["content-security-policy"]
    assert "max-age=31536000" in headers["strict-transport-security"]


def test_docs_csp_allows_swagger_cdn(client):
    """Interactive /docs route allows CDN resources while API endpoints get default-src 'none'."""
    docs_res = client.get("/docs")
    if docs_res.status_code == 200:
        docs_csp = docs_res.headers.get("content-security-policy", "")
        assert "cdn.jsdelivr.net" in docs_csp

    api_res = client.get("/api/health")
    assert "default-src 'none'" in api_res.headers["content-security-policy"]


def test_sensitive_routes_have_no_cache_headers(client):
    """Authenticated and sensitive endpoints must include Cache-Control: no-store."""
    res = client.get("/api/me", headers=_student_headers(client))
    assert res.status_code == 200

    cache_control = res.headers.get("cache-control", "")
    assert "no-store" in cache_control
    assert "no-cache" in cache_control
    assert res.headers.get("pragma") == "no-cache"


# ---------------------------------------------------------------------------
# CORS Configuration & Exposed Headers
# ---------------------------------------------------------------------------
def test_cors_options_preflight_and_exposed_headers(client):
    """CORS preflight responds cleanly and actual CORS requests expose rate limit headers."""
    # 1. Preflight OPTIONS request
    preflight = client.options(
        "/api/complaints",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:5173"

    # 2. Actual CORS request
    res = client.get(
        "/api/me",
        headers={
            "Origin": "http://localhost:5173",
            **_student_headers(client),
        },
    )
    assert res.status_code == 200
    expose_headers = res.headers.get("access-control-expose-headers", "")
    assert "Retry-After" in expose_headers
    assert "X-RateLimit-Limit" in expose_headers


# ---------------------------------------------------------------------------
# Request Size Limits (413)
# ---------------------------------------------------------------------------
def test_oversized_payload_rejected_with_413(settings, tokens):
    """Requests exceeding size limits are rejected with 413."""
    small_settings = config.Settings(
        database_url=settings.database_url,
        supabase_url=settings.supabase_url,
        supabase_anon_key=settings.supabase_anon_key,
        supabase_service_role_key=settings.supabase_service_role_key,
        bucket="CLimage",
        max_json_body_bytes=50,
    )
    app = create_app(small_settings)
    with TestClient(app) as test_c:
        res = test_c.post(
            "/api/admin/complaints/00000000-0000-4000-8000-000000000001/notes",
            headers={
                "Authorization": f"Bearer {tokens['admin']}",
                "Content-Length": "500",
            },
            json={"body": "A" * 200},
        )
        assert res.status_code == 413
        assert res.json()["detail"] == "Request entity too large."
        assert res.headers["x-content-type-options"] == "nosniff"


# ---------------------------------------------------------------------------
# Authentication & Token Guards
# ---------------------------------------------------------------------------
def test_oversized_token_rejected_with_401(client):
    """Abnormally large token string (token bomb) is rejected with 401."""
    massive_token = "A" * 9000
    res = client.get("/api/me", headers={"Authorization": f"Bearer {massive_token}"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid token."


def test_malformed_uuid_returns_404_not_503(client):
    """Malformed UUID path parameter returns 404 rather than unhandled database error."""
    # Student view
    res = client.get("/api/complaints/not-a-valid-uuid", headers=_student_headers(client))
    assert res.status_code == 404
    assert res.json()["detail"] == "Complaint not found."

    # Admin view
    res_admin = client.get("/api/admin/complaints/123-bad-id", headers=_admin_headers(client))
    assert res_admin.status_code == 404
    assert res_admin.json()["detail"] == "Complaint not found."
