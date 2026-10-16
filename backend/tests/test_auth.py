"""Authentication: missing, malformed and forged credentials."""

import pytest

from app import auth, database

FORBIDDEN_FIELDS = (
    "priority_score", "score_breakdown", "confirmed_urgency", "confirmed_impact",
    "confirmed_safety", "confirmed_by", "ai_summary", "ai_evidence",
    "ai_uncertainty", "ai_urgency", "ai_impact", "ai_safety", "student_id",
    "analysis_confirmed_at",
)


def test_health_needs_no_auth(client):
    assert client.get("/api/health").status_code == 200


def test_public_feed_needs_no_auth(client):
    assert client.get("/api/public/complaints").status_code == 200


def test_list_own_requires_a_token(client):
    assert client.get("/api/complaints").status_code == 401


def test_list_own_rejects_a_garbage_token(client):
    r = client.get("/api/complaints", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def test_submit_requires_a_token(client):
    r = client.post(
        "/api/complaints",
        data={"description": "Broken light in the stairwell", "location": "Science Block"},
    )
    assert r.status_code == 401


def test_student_cannot_reach_admin_routes(client):
    headers = {"Authorization": "Bearer " + client.tokens["student_a"]}
    for path in ("/api/admin/complaints", "/api/admin/analytics/summary"):
        r = client.get(path, headers=headers)
        assert r.status_code == 403, f"{path} should be admin-only"
    for path in ("/api/admin/complaints/abc/status", "/api/admin/complaints/abc/analysis"):
        r = client.patch(path, headers=headers, json={"status": "Resolved"})
        assert r.status_code == 403, f"{path} should be admin-only"


def test_a_token_claiming_admin_grants_nothing(client, settings, rsa_key):
    """The role comes from profiles, never from the token's claims."""
    from tests.conftest import make_token

    forged = make_token(rsa_key, "11111111-1111-4111-8111-111111111111", role="service_role")
    r = client.get("/api/admin/complaints", headers={"Authorization": "Bearer " + forged})
    assert r.status_code == 403


def test_admin_token_is_accepted(client):
    r = client.get("/api/admin/complaints", headers={"Authorization": "Bearer " + client.tokens["admin"]})
    assert r.status_code == 200


def test_verified_user_without_a_profile_is_forbidden(client, rsa_key):
    from tests.conftest import make_token

    orphan = make_token(rsa_key, "99999999-9999-4999-8999-999999999999")
    r = client.get("/api/complaints", headers={"Authorization": "Bearer " + orphan})
    assert r.status_code == 403


def test_expired_token_is_rejected(client, rsa_key):
    from tests.conftest import make_token

    expired = make_token(rsa_key, "11111111-1111-4111-8111-111111111111", exp_minutes=-5)
    r = client.get("/api/complaints", headers={"Authorization": "Bearer " + expired})
    assert r.status_code == 401


def test_only_asymmetric_algorithms_are_accepted(client, settings):
    """A 'none' or HMAC token must never be honoured."""
    import jwt as pyjwt

    header = pyjwt.get_unverified_header(client.tokens["student_a"])
    assert header["alg"] in auth.ALLOWED_ALGS
    assert "none" not in auth.ALLOWED_ALGS
    assert not any(a.startswith("HS") for a in auth.ALLOWED_ALGS)
