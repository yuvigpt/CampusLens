"""
Pydantic models describing what the CampusLens API returns.

These only shape the HTTP layer. All validation of complaint data still happens
in database.py / priority.py / gemini.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from . import database, priority


class HealthOut(BaseModel):
    """Deliberately contains no paths, environment variables or secrets."""

    status: str
    service: str
    version: str


class AnalysisOutcome(BaseModel):
    """What app.gemini reported. `error` is already redacted by gemini.py."""

    ok: bool
    model: str
    elapsed_seconds: float
    error: Optional[str] = None
    error_kind: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


class ComplaintOut(BaseModel):
    """One complaint, exactly as stored plus a few derived fields."""

    id: int
    description: str
    location: str
    image_path: Optional[str] = None
    image_url: Optional[str] = None

    category: Optional[str] = None
    issue_summary: Optional[str] = None
    safety_risk: Optional[str] = None
    functional_impact: Optional[str] = None
    urgency: Optional[str] = None
    evidence_from_image: Optional[str] = None
    uncertainty_or_missing_information: Optional[str] = None

    priority_score: Optional[float] = None
    priority_band: Optional[str] = None
    score_breakdown: Optional[dict[str, Any]] = None

    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    resolved_at: Optional[str] = None

    analysis: Optional[AnalysisOutcome] = None
    warnings: list[str] = Field(default_factory=list)


class StatusUpdateIn(BaseModel):
    """Body for PATCH /api/complaints/{id}/status."""

    status: str = Field(description="One of the statuses in database.ALLOWED_STATUSES")

    @field_validator("status")
    @classmethod
    def _must_be_allowed(cls, value: str) -> str:
        # Reuse the database module's list - never duplicate it here.
        if not isinstance(value, str) or value not in database.ALLOWED_STATUSES:
            raise ValueError(
                f"status must be one of {list(database.ALLOWED_STATUSES)}, got {value!r}"
            )
        return value


class AnalyticsSummaryOut(BaseModel):
    """Counts for the admin dashboard.

    `unscored` is the number of complaints with no priority score at all
    (Gemini failed, or the category was not mapped). They are counted
    separately so the bands always add up to `total`.
    """

    total: int
    by_status: dict[str, int]
    by_priority_band: dict[str, int]
    unscored: int
    unresolved: int
    by_category: dict[str, int]


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def priority_band_for(complaint: dict[str, Any]) -> Optional[str]:
    """Work out a complaint's band from what is stored.

    Prefers the band recorded inside score_breakdown, then falls back to
    recomputing it from priority_score using priority.band_for_score().
    Returns None when the complaint has no score at all - the thresholds
    themselves live only in priority.py.
    """
    breakdown = complaint.get("score_breakdown")
    if isinstance(breakdown, dict):
        band = breakdown.get("band")
        if isinstance(band, str) and band:
            return band

    score = complaint.get("priority_score")
    if score is None:
        return None
    try:
        return priority.band_for_score(score)
    except priority.PriorityValidationError:
        return None          # stored value out of range: never guess


def image_url_for(complaint: dict[str, Any]) -> Optional[str]:
    """Turn the stored relative path into a URL the browser can fetch."""
    stored = complaint.get("image_path")
    if not stored:
        return None
    return f"/uploads/{Path(stored).name}"


def complaint_out(
    complaint: dict[str, Any],
    *,
    analysis: Optional[AnalysisOutcome] = None,
    warnings: tuple[str, ...] | list[str] = (),
) -> ComplaintOut:
    """Map one database row onto the public API shape."""
    return ComplaintOut(
        id=complaint["id"],
        description=complaint["description"],
        location=complaint["location"],
        image_path=complaint.get("image_path"),
        image_url=image_url_for(complaint),
        category=complaint.get("category"),
        issue_summary=complaint.get("issue_summary"),
        safety_risk=complaint.get("safety_risk"),
        functional_impact=complaint.get("functional_impact"),
        urgency=complaint.get("urgency"),
        evidence_from_image=complaint.get("evidence_from_image"),
        uncertainty_or_missing_information=complaint.get(
            "uncertainty_or_missing_information"
        ),
        priority_score=complaint.get("priority_score"),
        priority_band=priority_band_for(complaint),
        score_breakdown=complaint.get("score_breakdown"),
        status=complaint["status"],
        created_at=complaint.get("created_at"),
        updated_at=complaint.get("updated_at"),
        resolved_at=complaint.get("resolved_at"),
        analysis=analysis,
        warnings=list(warnings),
    )


def analysis_outcome(result: Any) -> AnalysisOutcome:
    """Map a gemini.AnalysisResult onto its API shape."""
    return AnalysisOutcome(
        ok=result.ok,
        model=result.model,
        elapsed_seconds=result.elapsed_seconds,
        error=result.error,
        error_kind=result.error_kind,
        warnings=list(result.warnings),
    )