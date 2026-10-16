"""
CampusLens - response models.

Three separate families, deliberately not subclasses of one another:

    StudentComplaintOut   the student's own complaint. No score, no score
                          breakdown, no AI analysis, no confirmed values, no
                          admin notes, no other student's data.
    AdminComplaintOut     adds the score, the full breakdown and the confirmed
                          inputs. Admin only.
    PublicComplaintOut    the community feed. Reads public_complaints, which
                          has no reporter identity and no score at all.

A field cannot leak by accident because the student's model has no such field
to omit: FastAPI serialises only what the model declares.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from . import scoring


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
class HealthOut(BaseModel):
    """Liveness probe. Contains no paths, configuration or secrets."""

    status: str
    service: str
    version: str


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
class MeOut(BaseModel):
    """The signed-in caller's own profile - GET /api/me.

    Deliberately absent: any score, any AI field, any complaint data, and any
    auth.users column beyond the display email. The role comes from the
    `profiles` table, never from a token claim or anything the client sent.
    """

    id: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------
class StudentComplaintOut(BaseModel):
    """What a student may see about their own complaint.

    `ai_*` fields ARE exposed here: every submitted complaint carries its AI
    analysis (category, summary, evidence, uncertainty, urgency, impact,
    safety). The AI analysis is a SUGGESTION - it never changes the numeric
    score, which stays in the admin view.

    `priority_band` is the ONLY scoring information a student receives: one of
    Low/Medium/High/Critical, or null while the complaint is still unscored.
    The numeric score and the factor breakdown stay admin-only.
    """

    id: str
    description: str
    location: str
    location_code: Optional[str] = None
    status: str
    image_url: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    # Tells the student whether AI analysis is still pending, without exposing
    # the provider, the error text or any analysis result.
    analysis_status: Optional[str] = Field(
        default=None,
        description="pending | succeeded | failed | null when AI is disabled",
    )
    # Synchronous AI suggestion from POST /api/complaints.
    ai_category: Optional[str] = None
    ai_summary: Optional[str] = None
    ai_evidence: Optional[str] = None
    ai_uncertainty: Optional[str] = None
    ai_urgency: Optional[str] = None
    ai_impact: Optional[str] = None
    ai_safety: Optional[str] = None
    # Coarse priority only: "Low" | "Medium" | "High" | "Critical" (or null).
    priority_band: Optional[str] = Field(
        default=None,
        description=(
            "Coarse priority only: Low | Medium | High | Critical. "
            "null while unscored - never a number, breakdown or AI finding."
        ),
    )


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
class AdminComplaintOut(BaseModel):
    """Full administrative view of one complaint."""

    id: str
    student_id: str
    description: str
    location: str
    location_code: Optional[str] = None
    image_path: Optional[str] = None
    image_url: Optional[str] = None
    status: str

    confirmed_urgency: Optional[str] = None
    confirmed_impact: Optional[str] = None
    confirmed_safety: Optional[str] = None
    confirmed_by: Optional[str] = None
    analysis_confirmed_at: Optional[datetime] = None

    priority_score: Optional[float] = None
    score_breakdown: Optional[dict[str, Any]] = None
    score_computed_at: Optional[datetime] = None

    # Coarse band (Low/Medium/High/Critical) derived from `priority_score`, used
    # by the admin UI (mirrors the student's `priority_band`). null while
    # unscored.
    band: Optional[str] = None

    ai_category: Optional[str] = None
    ai_summary: Optional[str] = None
    ai_evidence: Optional[str] = None
    ai_uncertainty: Optional[str] = None
    ai_urgency: Optional[str] = None
    ai_impact: Optional[str] = None
    ai_safety: Optional[str] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None


class AdminAnalyticsOut(BaseModel):
    """Dashboard counts.

    `unscored` counts complaints whose priority_score IS NULL. A stored score of
    0 is a REAL score and is counted inside its band, never as unscored (D7).
    """

    total: int
    by_status: dict[str, int]
    by_band: dict[str, int]
    unscored: int
    unresolved: int


class ComplaintEventOut(BaseModel):
    """One row of the append-only audit trail (complaint_events).

    `actor_email` is resolved through profiles (admin RLS permits the join) and
    is cosmetic: authorisation never depends on it. `to_value` for a
    'note_added' event is always NULL so note content cannot leak into the
    student-readable event history.
    """

    id: int
    actor_role: str
    actor_email: Optional[str] = None
    event_type: str
    from_value: Optional[str] = None
    to_value: Optional[str] = None
    created_at: Optional[datetime] = None


class InvestigationNoteOut(BaseModel):
    """One admin-only investigation note. Students never see these."""

    id: str
    body: str
    author_kind: str
    author_email: Optional[str] = None
    created_at: Optional[datetime] = None


class CommunityComplaintOut(BaseModel):
    """One sanitized campus-wide row (migration 016 community_overview).

    Small info only: where, what kind, current state, coarse band and when.
    No reporter identity, no description text, no numeric score - the columns
    do not exist in the underlying function.
    """

    id: str
    location: str
    status: str
    band: Optional[str] = None
    category: Optional[str] = None
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------
class PublicComplaintOut(BaseModel):
    """One approved, privacy-safe community entry.

    Contains no reporter identity, no score, no free-text description and no
    internal location code - those columns do not exist on the source table.
    """

    id: str
    public_summary: str
    public_category: str
    public_location: str
    status: str
    approved_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------
class StatusUpdateIn(BaseModel):
    """Body for the status change endpoint."""

    status: str = Field(description=f"One of {list(scoring.STATUSES)}")


class AnalysisConfirmIn(BaseModel):
    """Admin-confirmed scoring inputs (D11).

    These are the ONLY values the scorer reads. An AI suggestion may prefill the
    form, but a human must send this request before any score exists.
    """

    confirmed_urgency: str = Field(description="Low | Medium | High")
    confirmed_impact: str = Field(description="Low | Medium | High")
    confirmed_safety: str = Field(description="Low | Medium | High")

    @staticmethod
    def _check(value: str) -> str:
        normalised = str(value).strip().title()
        if normalised not in scoring.LEVELS:
            raise ValueError(f"must be one of {list(scoring.LEVELS)}")
        return normalised

    def normalised(self) -> tuple[str, str, str]:
        return (
            self._check(self.confirmed_urgency),
            self._check(self.confirmed_impact),
            self._check(self.confirmed_safety),
        )


class NoteIn(BaseModel):
    """Body for POST /api/admin/complaints/{id}/notes (internal admin note)."""

    body: str = Field(..., min_length=1, max_length=8000)


class PublicApprovalIn(BaseModel):
    """Sanitized text an admin publishes to the community feed.

    These three fields are supplied by the admin and stored VERBATIM. Nothing is
    copied from the original complaint, so the reporter's own words, their
    identity and the internal location code cannot leak by accident.

    Length bounds mirror the public_complaints CHECK constraints.
    """

    public_summary: str = Field(
        ..., min_length=10, max_length=1000,
        description="Sanitized one-paragraph summary, 10-1000 characters.",
    )
    public_category: str = Field(..., min_length=2, max_length=80)
    public_location: str = Field(
        ..., min_length=2, max_length=160,
        description="Generalised location, e.g. 'Science Block, ground floor'.",
    )


class SubmitOut(BaseModel):
    """201 body for a successful submission.

    Carries the synchronous AI suggestion (`ai_*`) when the provider answered
    inside this request, plus `analysis_queued` (True only when the analysis
    actually ran). Never a numeric score or a score breakdown: scoring starts
    exclusively at the admin confirmation endpoint.
    """

    id: str
    status: str
    message: str
    analysis_queued: bool = False
    ai_category: Optional[str] = None
    ai_summary: Optional[str] = None
    ai_evidence: Optional[str] = None
    ai_uncertainty: Optional[str] = None
    ai_urgency: Optional[str] = None
    ai_impact: Optional[str] = None
    ai_safety: Optional[str] = None