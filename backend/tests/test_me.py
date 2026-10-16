"""GET /api/me - the caller's own identity.

Covers: student, admin, missing token, invalid token, and a valid token with
no profiles row.
"""

FORBIDDEN = {
    "priority_score", "score_breakdown", "confirmed_urgency", "confirmed_impact",
    "confirmed_safety", "confirmed_by", "ai_summary", "ai_evidence",
    "ai_uncertainty", "ai_urgency", "ai_impact", "ai_safety",
}


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_me_requires_a_token(client):
    assert client.get("/api/me").status_code == 401


def test_me_rejects_a_garbage_token(client):
    assert client.get("/api/me", headers=auth("not-a-jwt")).status_code == 401


def test_me_rejects_an_expired_token(client, rsa_key):
    from tests.conftest import make_token

    expired = make_token(rsa_key, "11111111-1111-4111-8111-111111111111", exp_minutes=-5)
    assert client.get("/api/me", headers=auth(expired)).status_code == 401


def test_student_gets_their_own_profile(client):
    r = client.get("/api/me", headers=auth(client.tokens["student_a"]))
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "11111111-1111-4111-8111-111111111111"
    assert body["role"] == "student"
    assert body["email"]


def test_admin_gets_role_admin(client):
    r = client.get("/api/me", headers=auth(client.tokens["admin"]))
    assert r.status_code == 200
    assert r.json()["role"] == "admin"
    assert r.json()["id"] == "33333333-3333-4333-8333-333333333333"


def test_me_never_exposes_internal_fields(client):
    body = client.get("/api/me", headers=auth(client.tokens["admin"])).text
    for field in FORBIDDEN:
        assert field not in body, f"{field} must not appear in /api/me"


def test_a_token_claiming_admin_cannot_change_the_role(client, rsa_key):
    """The role comes from profiles, so a forged claim is ignored."""
    from tests.conftest import make_token

    forged = make_token(rsa_key, "11111111-1111-4111-8111-111111111111", role="service_role")
    r = client.get("/api/me", headers=auth(forged))
    assert r.status_code == 200
    assert r.json()["role"] == "student", "forged role claim must be ignored"


def test_valid_token_without_a_profile_is_forbidden(client, rsa_key):
    from tests.conftest import make_token

    orphan = make_token(rsa_key, "99999999-9999-4999-8999-999999999999")
    r = client.get("/api/me", headers=auth(orphan))
    assert r.status_code == 403


def test_me_response_has_exactly_the_declared_fields(client):
    body = client.get("/api/me", headers=auth(client.tokens["student_a"])).json()
    assert set(body) == {"id", "email", "full_name", "role", "created_at"}


def test_student_cannot_use_me_to_read_another_profile(client, rsa_key):
    """A user_id in the query string is ignored; the JWT decides."""
    from tests.conftest import make_token

    admin = make_token(rsa_key, "11111111-1111-4111-8111-111111111111")
    r = client.get(
        "/api/me?user_id=33333333-3333-4333-8333-333333333333",
        headers=auth(admin),
    )
    assert r.status_code == 200
    assert r.json()["id"] == "11111111-1111-4111-8111-111111111111"
    assert r.json()["role"] == "student"
