"""Admin complaint management: status updates, scoring, and analytics.

Also pins the D7 rule that drives the dashboard: a NULL priority_score is
Unscored, while a stored score of 0 is a REAL score counted inside its band.
"""

import pytest


def _admin(client):
    return {"Authorization": "Bearer " + client.tokens["admin"]}


def _student(client):
    return {"Authorization": "Bearer " + client.tokens["student_a"]}


def _submit(client, who="student_a", text="Broken light in the stairwell"):
    return client.post(
        "/api/complaints",
        data={"description": text, "location": "Science Block"},
        headers={"Authorization": "Bearer " + client.tokens[who]},
    )


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
def test_admin_can_change_status(client):
    cid = _submit(client).json()["id"]
    r = client.patch(f"/api/admin/complaints/{cid}/status",
                     json={"status": "In Progress"}, headers=_admin(client))
    assert r.status_code == 200
    assert r.json()["status"] == "In Progress"
    assert client.store.complaints[cid]["status"] == "In Progress"


def test_resolving_sets_resolved_at(client):
    cid = _submit(client).json()["id"]
    client.patch(f"/api/admin/complaints/{cid}/status",
                 json={"status": "Resolved"}, headers=_admin(client))
    assert client.store.complaints[cid]["status"] == "Resolved"


def test_invalid_status_is_rejected(client):
    cid = _submit(client).json()["id"]
    r = client.patch(f"/api/admin/complaints/{cid}/status",
                     json={"status": "Banished"}, headers=_admin(client))
    assert r.status_code in (422, 404)


def test_student_cannot_change_status(client):
    cid = _submit(client).json()["id"]
    r = client.patch(f"/api/admin/complaints/{cid}/status",
                     json={"status": "Resolved"}, headers=_student(client))
    assert r.status_code == 403
    assert client.store.complaints[cid]["status"] == "Reported"


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def test_confirming_levels_produces_a_score(client):
    cid = _submit(client).json()["id"]
    r = client.patch(
        f"/api/admin/complaints/{cid}/analysis",
        json={"confirmed_urgency": "High", "confirmed_impact": "Medium",
              "confirmed_safety": "Low"},
        headers=_admin(client),
    )
    assert r.status_code == 200
    body = r.json()
    # 30 + 12 + 0 + recurrence 0 (location_code NULL) + age 0 = 42
    assert body["priority_score"] == 42.0
    assert body["score_breakdown"]["band"] == "Medium"


def test_scoring_rejects_an_invalid_level(client):
    cid = _submit(client).json()["id"]
    r = client.patch(
        f"/api/admin/complaints/{cid}/analysis",
        json={"confirmed_urgency": "Severe", "confirmed_impact": "Low",
              "confirmed_safety": "Low"},
        headers=_admin(client),
    )
    assert r.status_code == 422
    assert client.store.complaints[cid]["priority_score"] is None


def test_student_cannot_score(client):
    cid = _submit(client).json()["id"]
    r = client.patch(
        f"/api/admin/complaints/{cid}/analysis",
        json={"confirmed_urgency": "High", "confirmed_impact": "High",
              "confirmed_safety": "High"},
        headers=_student(client),
    )
    assert r.status_code == 403
    assert client.store.complaints[cid]["priority_score"] is None


def test_scoring_does_not_change_status(client):
    cid = _submit(client).json()["id"]
    client.patch(
        f"/api/admin/complaints/{cid}/analysis",
        json={"confirmed_urgency": "High", "confirmed_impact": "Low",
              "confirmed_safety": "Low"},
        headers=_admin(client),
    )
    assert client.store.complaints[cid]["status"] == "Reported"


# ---------------------------------------------------------------------------
# Analytics - the D7 NULL vs 0 distinction
# ---------------------------------------------------------------------------
def _summary(client):
    return client.get("/api/admin/analytics/summary", headers=_admin(client)).json()


def test_student_cannot_read_analytics(client):
    assert client.get("/api/admin/analytics/summary",
                      headers=_student(client)).status_code == 403


def test_unscored_complaint_is_counted_as_unscored(client):
    _submit(client)
    s = _summary(client)
    assert s["total"] == 1
    assert s["unscored"] == 1
    assert sum(s["by_band"].values()) == 0


def test_a_zero_score_is_scored_not_unscored(client):
    """D7: NULL means Unscored; 0 is a real score inside the Low band."""
    cid = _submit(client).json()["id"]
    client.store.complaints[cid]["priority_score"] = 0.0
    s = _summary(client)
    assert s["total"] == 1
    assert s["unscored"] == 0, "a stored 0 must not be reported as Unscored"
    assert s["by_band"]["Low"] == 1, "score 0 belongs in the Low band"


def test_unscored_and_zero_can_coexist(client):
    scored_zero = _submit(client, text="Minor cosmetic issue").json()["id"]
    client.store.complaints[scored_zero]["priority_score"] = 0.0
    _submit(client, text="Awaiting admin review")
    s = _summary(client)
    assert s["total"] == 2
    assert s["unscored"] == 1
    assert s["by_band"]["Low"] == 1


def test_unresolved_excludes_resolved(client):
    a = _submit(client, text="Still open in the stairwell").json()["id"]
    _submit(client, text="Already handled by maintenance")
    client.patch(f"/api/admin/complaints/{a}/status",
                 json={"status": "Resolved"}, headers=_admin(client))
    s = _summary(client)
    assert s["by_status"]["Resolved"] == 1
    assert s["unresolved"] == 1
