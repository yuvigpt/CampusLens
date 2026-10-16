"""Student-scope isolation + the new submission-time estimate behaviour.

A student may only ever read their own complaints; another student's rows are
hidden (404, never 403).  Unscored complaints keep SQL NULL for the score
columns, yet the student view always shows a deterministic initial band
(computed in memory, never persisted), so ``AI_ENABLED=false`` can never yield
``Priority: Not yet rated``.
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Helpers (reconstructed for the restored test suite)
# ---------------------------------------------------------------------------
def _admin(client):
    return {"Authorization": "Bearer " + client.tokens["admin"]}

def _student(client):
    return {"Authorization": "Bearer " + client.tokens["student_a"]}

def _submit(client, text="Broken light in the stairwell", who="student_a"):
    return client.post(
        "/api/complaints",
        data={"description": text, "location": "Science Block"},
        headers={"Authorization": "Bearer " + client.tokens[who]},
    )

# ---------------------------------------------------------------------------
# Student route isolation
# ---------------------------------------------------------------------------


from fastapi import status



# ---------------------------------------------------------------------------
# Student route isolation
# ---------------------------------------------------------------------------

def test_student_can_read_own_complaint(client):
    cid = _submit(client).json()["id"]
    out = client.get(f"/api/complaints/{cid}", headers=_student(client))
    assert out.status_code == status.HTTP_200_OK
    assert out.json()["id"] == cid


def test_student_cannot_read_another_students_complaint(client):
    mine = _submit(client).json()["id"]
    theirs = _submit(client, text="Someone else's report", who="student_b").json()["id"]

    out = client.get(f"/api/complaints/{theirs}", headers=_student(client))
    assert out.status_code == status.HTTP_404_NOT_FOUND

    mine_out = client.get(f"/api/complaints/{mine}", headers=_student(client))
    assert mine_out.status_code == status.HTTP_200_OK
    assert mine_out.json()["id"] == mine


def test_filter_does_not_leak_other_students_rows(client):
    theirs = _submit(client, text="Filtered report", who="student_b").json()["id"]
    mine = _submit(client, text="My own report").json()["id"]

    out = client.get(
        "/api/complaints", headers=_student(client),
        params={"status": "Reported"},
    )
    assert out.status_code == status.HTTP_200_OK
    assert all(r["id"] != theirs for r in out.json())
    assert any(r["id"] == mine for r in out.json())


# ---------------------------------------------------------------------------
# Fresh complaints: NULL score, deterministic initial estimate band
# ---------------------------------------------------------------------------

def test_unscored_persists_null_but_shows_initial_estimate(client):
    """BCIP-1144: the score columns stay NULL (never guessed) while the
    submission-time estimate is computed in memory and shown as a band."""
    cid = _submit(client).json()["id"]

    # Persistence side: the fresh complaint is truly unscored (NULL, not 0).
    assert client.store.complaints[cid]["priority_score"] is None
    assert client.store.complaints[cid]["score_breakdown"] is None
    assert client.store.complaints[cid]["score_computed_at"] is None

    # Student side: a real, deterministic band is shown immediately, never
    # "Not yet rated"/null - the estimate is Low for fresh Low/Low/Low input.
    out = client.get(f"/api/complaints/{cid}", headers=_student(client))
    assert out.status_code == status.HTTP_200_OK
    assert out.json()["priority_band"] == "Low"


def test_submission_returns_no_score_to_student(client):
    """The 201 body is minimal - the student sees an ID, a status and a message.

    The request now also carries the server-side AI analysis (optional
    ``ai_*`` fields), but never a numeric score, a score breakdown or any
    confirmed/admin inputs.
    """
    out = client.post(
        "/api/complaints",
        headers=_student(client),
        data={"description": "A brief report", "location": "Library"},
    )
    body = out.json()
    assert out.status_code == status.HTTP_201_CREATED
    assert set(body) == {
        "id", "status", "message", "analysis_queued",
        "ai_category", "ai_summary", "ai_evidence", "ai_uncertainty",
        "ai_urgency", "ai_impact", "ai_safety",
    }
    assert body["status"] == "Reported"
    # Without a configured provider the analysis never ran: the flags say so
    # and every ai_* value stays null rather than being invented.
    assert body["analysis_queued"] is False
    assert body["ai_summary"] is None


def test_analysis_runs_in_the_request_and_returns_with_the_201(client, monkeypatch):
    """The AI runs synchronously inside POST /api/complaints.

    The finished suggestion arrives in THIS response (analysis_queued=True
    plus the ai_* values) - nothing is queued for later polling - and the
    analysis is auto-scored the instant it is stored: priority_score is
    computed from the suggestion's own levels with no admin confirm call, so
    the complaint leaves the submission already ranked.
    """
    from app import ai as ai_module

    monkeypatch.setattr(ai_module, "is_configured", lambda: True)
    monkeypatch.setattr(
        ai_module,
        "analyse",
        lambda **_kw: {
            "ai_category": "Lighting fault",
            "ai_summary": "Ceiling light flickering since Monday.",
            "ai_evidence": "The report mentions flickering and buzzing.",
            "ai_uncertainty": "No photo was attached.",
            "ai_urgency": "Medium",
            "ai_impact": "Low",
            "ai_safety": "Low",
        },
    )

    out = _submit(client, text="The ceiling light in lab 3 flickers and buzzes.")
    assert out.status_code == status.HTTP_201_CREATED
    body = out.json()

    # The analysis is in this very response - no follow-up request needed.
    assert body["analysis_queued"] is True
    assert body["ai_category"] == "Lighting fault"
    assert body["ai_summary"] == "Ceiling light flickering since Monday."
    assert body["ai_evidence"] == "The report mentions flickering and buzzing."
    assert body["ai_uncertainty"] == "No photo was attached."
    assert (body["ai_urgency"], body["ai_impact"], body["ai_safety"]) == (
        "Medium", "Low", "Low",
    )

    # The suggestion is stored on the row for admin review AND auto-scored:
    # Medium urgency = 15 points, Low impact/safety = 0, so the row is ranked
    # at 15.0. 15 is inside the Low band (0-29), so the band is Low - the
    # score, not the level label, decides the band. No admin confirm was made.
    row = client.store.complaints[body["id"]]
    assert row["ai_summary"] == "Ceiling light flickering since Monday."
    assert row["ai_urgency"] == "Medium"
    assert row["priority_score"] == 15.0
    assert row["score_breakdown"]["band"] == "Low"
    # The human-confirmed columns stay NULL: scoring was automatic, not manual.
    assert row["confirmed_urgency"] is None


def test_student_read_endpoints_expose_the_stored_analysis(client, monkeypatch):
    """Regression: My Complaints showed "Not started" for analysed complaints.

    The list and detail endpoints must carry the stored ai_* suggestion AND a
    derived analysis_status of "succeeded" (analysis_status is not a DB column
    - it is derived from ai_summary/ai_urgency). The numeric score must stay
    admin-only; the student only gets the coarse priority_band.
    """
    from app import ai as ai_module

    monkeypatch.setattr(ai_module, "is_configured", lambda: True)
    monkeypatch.setattr(
        ai_module,
        "analyse",
        lambda **_kw: {
            "ai_category": "Lighting fault",
            "ai_summary": "Ceiling light flickering since Monday.",
            "ai_evidence": "The report mentions flickering and buzzing.",
            "ai_uncertainty": "No photo was attached.",
            "ai_urgency": "Medium",
            "ai_impact": "Low",
            "ai_safety": "Low",
        },
    )

    cid = _submit(client, text="The ceiling light in lab 3 flickers and buzzes.").json()["id"]

    # Detail endpoint: analysis present, status derived as succeeded.
    detail = client.get(f"/api/complaints/{cid}", headers=_student(client))
    assert detail.status_code == status.HTTP_200_OK
    body = detail.json()
    assert body["analysis_status"] == "succeeded"
    assert body["ai_category"] == "Lighting fault"
    assert body["ai_summary"] == "Ceiling light flickering since Monday."
    assert (body["ai_urgency"], body["ai_impact"], body["ai_safety"]) == (
        "Medium", "Low", "Low",
    )
    assert body["priority_band"] == "Low"
    # The numeric score and breakdown must never appear on the student model.
    assert "priority_score" not in body
    assert "score_breakdown" not in body

    # List endpoint: the same fields, since that is what #/mine renders from.
    listing = client.get("/api/complaints", headers=_student(client))
    assert listing.status_code == status.HTTP_200_OK
    match = next(r for r in listing.json() if r["id"] == cid)
    assert match["analysis_status"] == "succeeded"
    assert match["ai_category"] == "Lighting fault"
    assert match["ai_summary"] == "Ceiling light flickering since Monday."
    assert match["priority_band"] == "Low"


def test_unanalysed_complaint_reports_no_analysis_status(client):
    """AI disabled/never ran -> analysis_status null and every ai_* null, so
    the UI can honestly say "Not started" instead of inventing a state."""
    cid = _submit(client, text="No provider configured for this run.").json()["id"]

    body = client.get(f"/api/complaints/{cid}", headers=_student(client)).json()
    assert body["analysis_status"] is None
    assert body["ai_category"] is None
    assert body["ai_summary"] is None
    assert body["ai_urgency"] is None
    # The deterministic estimate band still shows - never "Not yet rated".
    assert body["priority_band"] == "Low"
