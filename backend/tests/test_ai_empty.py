"""Empty AI replies are failures, never successes.

parse_analysis() is strict on purpose: a reply with zero usable fields raises
AnalysisInvalid, so the analyser never stores a partial or guessed suggestion
(see backend/app/ai.py). But a provider can also hand back an empty-but-valid
``{}`` after validation - e.g. every level normalised to None and every text
field blank - and until this fix `_try_analyse` reported that as ``ran=True``.
The student then saw an "analysis complete" panel with nothing in it (or the
confusing "produced nothing usable" copy).

Rule pinned here: ``analysed`` is True only when the suggestion dict is
non-empty AND `_store_suggestion` ran; otherwise the failure is recorded with
kind "empty" and analysis_queued stays False, so the UI shows "Analysis not
available" instead of an empty celebration.
"""
from __future__ import annotations

from unittest.mock import patch

from fastapi import status


def _submit(client, who="student_a", text="Water is leaking from the ceiling"):
    return client.post(
        "/api/complaints",
        data={"description": text, "location": "Library"},
        headers={"Authorization": "Bearer " + client.tokens[who]},
    )


def test_empty_suggestion_is_not_claimed_as_a_success(client):
    """analyse() answered with {} -> 201 with analysis_queued False, failure
    recorded as kind 'empty', row untouched."""
    from app import ai as ai_module
    from app.routers import complaints as complaints_router

    with (
        patch.object(ai_module, "is_configured", lambda: True),
        patch.object(ai_module, "analyse", lambda **_kw: {}),
        patch.object(
            complaints_router, "_store_suggestion"
        ) as store_spy,
        patch.object(
            complaints_router, "_record_failure"
        ) as record_spy,
    ):
        out = _submit(client)

    assert out.status_code == status.HTTP_201_CREATED
    body = out.json()
    assert body["analysis_queued"] is False
    assert body["ai_summary"] is None
    store_spy.assert_not_called()
    record_spy.assert_called_once()
    assert record_spy.call_args.args[2] == "empty"


def test_full_suggestion_still_claims_success_and_stores(client):
    suggestion = {
        "ai_category": "Plumbing",
        "ai_summary": "Water is leaking from the ceiling.",
        "ai_urgency": "High",
        "ai_impact": "Medium",
        "ai_safety": "Low",
    }
    from app import ai as ai_module
    from app.routers import complaints as complaints_router

    with (
        patch.object(ai_module, "is_configured", lambda: True),
        patch.object(ai_module, "analyse", lambda **_kw: dict(suggestion)),
        patch.object(
            complaints_router, "_store_suggestion"
        ) as store_spy,
        patch.object(
            complaints_router, "_record_failure"
        ) as record_spy,
    ):
        out = _submit(client)

    body = out.json()
    assert body["analysis_queued"] is True
    assert body["ai_summary"] == suggestion["ai_summary"]
    store_spy.assert_called_once()
    record_spy.assert_not_called()
