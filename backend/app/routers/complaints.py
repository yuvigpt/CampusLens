"""
CampusLens - HTTP layer for the three audiences.

Route groups:
  /api/complaints/*   the caller's own complaints
  /api/admin/*        every complaint, scores, confirmations  (admin only)
  /api/public/*       approved sanitized feed              (no auth)
  /api/health         liveness                              (no auth)

Authorisation notes
-------------------
* Identity always comes from ``auth.current_identity`` / ``auth.current_admin``,
  which verify the JWT and read the role from the database. No route trusts a
  role, student id or admin flag supplied by the client.
* RLS is enforced in PostgreSQL. Where a student must be confined to their own
  rows the query is additionally filtered by the verified user id, so
  authorisation does not rest on the policy alone.
* A complaint the caller may not see returns 404, not 403: the existence of
  another student's complaint is not disclosed.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    Response,
    status,
)

from .. import ai, config, database, scoring, storage
from ..auth import current_admin, current_identity
from ..schemas import (
    AdminAnalyticsOut,
    AdminComplaintOut,
    AnalysisConfirmIn,
    CommunityComplaintOut,
    ComplaintEventOut,
    HealthOut,
    InvestigationNoteOut,
    MeOut,
    NoteIn,
    PublicApprovalIn,
    PublicComplaintOut,
    StatusUpdateIn,
    StudentComplaintOut,
    SubmitOut,
)

logger = logging.getLogger("campuslens.api")

router = APIRouter(prefix="/api", tags=["campuslens"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _settings(request: Request) -> config.Settings:
    return request.app.state.settings


def _sid(value: object) -> str:
    return str(value)


def _initial_band(row: dict) -> Optional[str]:
    """Deterministic submission-time ESTIMATE band, computed in memory only.

    No external call, no AI, no confirmed inputs: urgency/impact/safety all
    baseline to Low, recurrence is 0 while structured campus reference data is
    unavailable, and age comes from the row's own created_at via the same
    authoritative `scoring` helpers. A fresh complaint therefore has age_days
    0 and age_points 0.

    This function MUST never consult `priority_score`: callers check the
    persisted score first and only fall back here when it is NULL.
    """
    try:
        created = row.get("created_at")
        age_days = scoring.age_days_between(created) if created else 0
        result = scoring.estimate_score_complaint(
            urgency="Low",
            impact="Low",
            safety="Low",
            age_days=age_days,
            recurrence_count=0,
            recurrence_not_applicable=True,
        )
    except (scoring.ScoringError, TypeError, ValueError):
        return None
    return result.band


def _student_band(row: dict) -> Optional[str]:
    """Coarse priority band for the student view.

    An admin-confirmed persisted score takes precedence: its number is reduced
    to one of four labels, never exposed. When `priority_score` is NULL, the
    deterministic initial estimate is computed in memory instead of returning
    None, so `AI_ENABLED=false` can never produce "Not yet rated". A stored 0
    is a REAL admin-confirmed score and bands as Low (D7); the NULL-vs-0
    distinction lives in the persistence layer, not here.
    """
    score = row.get("priority_score")
    if score is not None:
        try:
            return scoring.band_for_score(float(score))
        except (scoring.ScoringError, TypeError, ValueError):
            return None
    return _initial_band(row)


def _student_out(
    row: dict, image_url: Optional[str], analysis_status: Optional[str]
) -> StudentComplaintOut:
    """Map a database row onto the STUDENT model.

    Only fields declared by StudentComplaintOut are read, so the numeric score
    cannot leak even though the row carries one. `priority_band` is derived by
    _student_band(), which reduces the number to one of four labels.
    """
    return StudentComplaintOut(
        id=_sid(row["id"]),
        description=row["description"],
        location=row["location_raw"],
        location_code=row.get("location_code"),
        status=row["status"],
        image_url=image_url,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        resolved_at=row.get("resolved_at"),
        analysis_status=analysis_status,
        # Synchronous AI suggestion from POST /api/complaints.
        ai_category=row.get("ai_category"),
        ai_summary=row.get("ai_summary"),
        ai_evidence=row.get("ai_evidence"),
        ai_uncertainty=row.get("ai_uncertainty"),
        ai_urgency=row.get("ai_urgency"),
        ai_impact=row.get("ai_impact"),
        ai_safety=row.get("ai_safety"),
        priority_band=_student_band(row),
    )


def _admin_out(row: dict, image_url: Optional[str]) -> AdminComplaintOut:
    """Map a database row onto the ADMIN model (scores included)."""
    return AdminComplaintOut(
        id=_sid(row["id"]),
        student_id=_sid(row["student_id"]),
        description=row["description"],
        location=row["location_raw"],
        location_code=row.get("location_code"),
        image_path=row.get("image_path"),
        image_url=image_url,
        status=row["status"],
        confirmed_urgency=row.get("confirmed_urgency"),
        confirmed_impact=row.get("confirmed_impact"),
        confirmed_safety=row.get("confirmed_safety"),
        confirmed_by=_sid(row["confirmed_by"]) if row.get("confirmed_by") else None,
        analysis_confirmed_at=row.get("analysis_confirmed_at"),
        priority_score=row.get("priority_score"),
        score_breakdown=row.get("score_breakdown"),
        score_computed_at=row.get("score_computed_at"),
        band=scoring.band_for_score(float(row["priority_score"]))
        if row.get("priority_score") is not None
        else None,
        ai_category=row.get("ai_category"),
        ai_summary=row.get("ai_summary"),
        ai_evidence=row.get("ai_evidence"),
        ai_uncertainty=row.get("ai_uncertainty"),
        ai_urgency=row.get("ai_urgency"),
        ai_impact=row.get("ai_impact"),
        ai_safety=row.get("ai_safety"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        resolved_at=row.get("resolved_at"),
    )


def _analysis_status(row: dict) -> Optional[str]:
    """Coarse AI state for the student view - never the provider or its error."""
    if row.get("ai_summary") or row.get("ai_urgency"):
        return "succeeded"
    return None


async def _signed_image(
    settings: config.Settings, row: dict, identity: database.Identity
) -> Optional[str]:
    """Signed URL only when the caller is entitled to this complaint."""
    path = row.get("image_path")
    if not path:
        return None
    if not identity.is_admin and str(row.get("student_id")) != identity.user_id:
        return None
    try:
        return storage.create_signed_url(settings, object_path=path)
    except storage.StorageError:
        return None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@router.get("/health", response_model=HealthOut, tags=["meta"])
def health(request: Request) -> HealthOut:
    settings = _settings(request)
    return HealthOut(
        status="ok", service=settings.service_name, version=settings.service_version
    )


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
@router.get("/me", response_model=MeOut, tags=["identity"])
async def me(
    request: Request,
    identity: database.Identity = Depends(current_identity),
) -> MeOut:
    """The caller's own profile.

    The user id comes from the VERIFIED JWT (auth.current_identity), and the
    role is read from the `profiles` table. Nothing the client sends - no
    `user_id` parameter, no role claim, no token field - can influence the
    result, which is what lets the frontend decide whether to show admin UI.

    Requires a profiles row. current_identity already answers 403 when one is
    missing, so a valid token with no profile never reaches this handler.
    """
    settings = _settings(request)
    try:
        with database.session(settings.database_url, identity) as conn:
            row = database.load_profile(conn, identity.user_id)
    except database.DatabaseError:
        raise HTTPException(503, "Could not load your profile.") from None

    if row is None:
        # current_identity should have caught this first; keep the guard so a
        # future change cannot turn it into a silent 500.
        raise HTTPException(
            403, "No profile is associated with this account."
        )

    return MeOut(
        id=_sid(row["id"]),
        email=row.get("email"),
        full_name=row.get("full_name"),
        role=row["role"],
        created_at=row.get("created_at"),
    )


# ---------------------------------------------------------------------------
# AI helpers - never able to fail a submission
# ---------------------------------------------------------------------------
def _record_failure(settings: config.Settings, complaint_id: str, kind: str) -> None:
    """Record an AI failure. The complaint itself is never touched."""
    try:
        with database.session(
            settings.database_url, database.Identity(complaint_id, "system")
        ) as conn:
            database.record_job_failure(conn, complaint_id, kind, attempts=1)
    except Exception:
        logger.warning("could not record AI failure", exc_info=True)


def _store_suggestion(
    settings: config.Settings, complaint_id: str, suggestion: dict
) -> None:
    """Write the suggestion to ai_* only. Scores are never touched here.

    The write goes through migration 014's SECURITY DEFINER function: this
    session's identity (sub = complaint id, role = system) matches no UPDATE
    policy on complaints, so a raw UPDATE would be silently filtered to zero
    rows and the admin card would keep showing "Not provided".

    Scoring then happens automatically: migration 015's store_auto_score reads
    the ai_* levels this call just stored and produces the priority score with
    the same deterministic scorer, so the admin no longer confirms levels by
    hand. Both steps are best-effort and independent - if either fails the
    complaint is still saved, it is just unscored.
    """
    try:
        # 1. Persist the suggestion FIRST, in its own committed transaction.
        #    This is the write the student's card reads, so it must be durable
        #    before anything else runs.
        with database.session(
            settings.database_url, database.Identity(complaint_id, "system")
        ) as conn:
            database.store_ai_suggestion(conn, complaint_id, suggestion)
    except Exception:
        logger.warning(
            "could not store AI suggestion for %s", complaint_id, exc_info=True
        )
        # Nothing to score if the suggestion did not persist.
        return

    try:
        # 2. Auto-score in a SEPARATE transaction. PostgreSQL poisons a whole
        #    transaction the moment any statement errors; if scoring shared the
        #    transaction above and raised outside its own handler, the commit
        #    would fail and silently roll back the suggestion we just wrote -
        #    the exact bug that left freshly-analysed rows showing "not started".
        #    actor_id=None: the 'scored' audit row records actor_role 'system'
        #    (migration 015 hardcodes that), and complaint_events.actor_id is a
        #    nullable FK to profiles(id) - a complaint id is not a profile, so
        #    NULL is the only honest value for this automated, non-human actor.
        with database.session(
            settings.database_url, database.Identity(complaint_id, "system")
        ) as conn:
            database.store_auto_score(conn, complaint_id, actor_id=None)
    except Exception:
        logger.warning("could not auto-score %s", complaint_id, exc_info=True)



def _try_analyse(
    settings: config.Settings,
    complaint_id: str,
    description: str,
    image_bytes: Optional[bytes],
    image_mime: Optional[str],
) -> tuple[bool, dict[str, Any]]:
    """Best-effort AI. Never raises, never rolls back the complaint.

    Runs the provider synchronously inside the submission request, so the
    caller receives the analysis immediately instead of being told it was
    queued and having to poll later.

    Returns ``(ran, suggestion)`` where ``ran`` is True when the AI was
    enabled and the provider answered, and ``suggestion`` is the parsed
    suggestion (an empty dict when nothing was produced).
    """
    if not settings.ai_enabled or not ai.is_configured():
        return False, {}
    try:
        suggestion = ai.analyse(
            description=description, image_bytes=image_bytes, image_mime=image_mime
        )
    except ai.AnalysisUnavailable as exc:
        logger.info("AI unavailable (%s); complaint kept", exc.kind)
        _record_failure(settings, complaint_id, exc.kind)
        return False, {}
    except Exception:
        logger.warning("AI call raised unexpectedly; complaint kept", exc_info=True)
        return False, {}
    if not suggestion:
        # A reply with zero usable fields is not a success: claiming it ran
        # would show the student an empty "analysis complete" panel.
        logger.info("AI returned an empty suggestion; complaint kept")
        _record_failure(settings, complaint_id, "empty")
        return False, {}
    _store_suggestion(settings, complaint_id, suggestion)
    return True, suggestion


# ---------------------------------------------------------------------------
# Student-facing complaints
# ---------------------------------------------------------------------------
@router.post(
    "/complaints",
    response_model=SubmitOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a complaint with a photo",
)
async def submit_complaint(
    request: Request,
    identity: database.Identity = Depends(current_identity),
    description: str = Form(..., description="What is wrong."),
    location: str = Form(..., description="Where on campus."),
    image: Optional[UploadFile] = File(None, description="jpg, png or webp."),
) -> SubmitOut:
    """Save a complaint FIRST; only then consider AI.

    No AI call happens on the persistence path. If the provider returns 503,
    times out or is simply absent, the complaint is still stored and the
    response is still 201.
    """
    settings = _settings(request)

    description = (description or "").strip()
    location = (location or "").strip()
    if len(description) < 10 or len(description) > 4000:
        raise HTTPException(422, "Description must be 10-4000 characters.")
    if not 2 <= len(location) <= 200:
        raise HTTPException(422, "Location must be 2-200 characters.")

    image_bytes: Optional[bytes] = None
    image_mime: Optional[str] = None
    object_path: Optional[str] = None

    if image is not None and image.filename:
        image_bytes = await image.read(settings.max_upload_bytes + 1)
        if not image_bytes:
            raise HTTPException(422, "The uploaded image is empty.")
        if len(image_bytes) > settings.max_upload_bytes:
            raise HTTPException(413, "Image is larger than the 5 MB limit.")
        try:
            # The Content-Type header is ignored; the bytes decide the type.
            object_path, image_mime = storage.build_object_path(
                identity.user_id, image_bytes
            )
        except storage.InvalidImage as exc:
            raise HTTPException(422, str(exc)) from None

    if object_path:
        try:
            storage.upload_image(
                settings, object_path=object_path, data=image_bytes, mime=image_mime
            )
        except storage.StorageError:
            # Nothing is written: a row pointing at a missing object would lie.
            raise HTTPException(502, "Image storage unavailable.") from None

    try:
        with database.session(settings.database_url, identity) as conn:
            row = database.create_complaint(
                conn,
                student_id=identity.user_id,
                description=description,
                location_raw=location,
                location_code=None,
                image_path=object_path,
            )
            database.record_created_event(conn, row["id"], identity.user_id, "student")

            # Submission NEVER scores: priority_score stays NULL ("Unscored")
            # until an admin confirms the levels on the analysis endpoint - the
            # only route that may produce a score. What a student sees instead
            # is the deterministic in-memory estimate from _student_band().
    except database.DatabaseError:
        raise HTTPException(503, "Could not save your complaint. Please retry.") from None

    # AI is attempted only AFTER the complaint is committed, and it runs
    # synchronously inside this request so the analysis is available in the
    # 201 body the moment the request completes.
    analysed, suggestion = _try_analyse(
        settings, row["id"], description, image_bytes, image_mime
    )

    return SubmitOut(
        id=_sid(row["id"]),
        status=row["status"],
        message="Complaint received.",
        analysis_queued=analysed,
        ai_category=suggestion.get("ai_category"),
        ai_summary=suggestion.get("ai_summary"),
        ai_evidence=suggestion.get("ai_evidence"),
        ai_uncertainty=suggestion.get("ai_uncertainty"),
        ai_urgency=suggestion.get("ai_urgency"),
        ai_impact=suggestion.get("ai_impact"),
        ai_safety=suggestion.get("ai_safety"),
    )


@router.get(
    "/complaints",
    response_model=list[StudentComplaintOut],
    summary="List the caller's own complaints",
)
async def list_own_complaints(
    request: Request,
    identity: database.Identity = Depends(current_identity),
    status_filter: Optional[str] = Query(
        None, alias="status", description="Reported | In Progress | Resolved"
    ),
    sort: str = Query("newest", description="newest | oldest"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: Optional[str] = Query(
        None, max_length=200, description="Search description, location or id"
    ),
) -> list[StudentComplaintOut]:
    """Always scoped to identity.user_id from the verified token.

    The student id is never taken from a query parameter, so one student cannot
    read another's complaints by changing the request. The `q` search only
    searches WITHIN the caller's own rows.
    """
    settings = _settings(request)
    if sort not in {"newest", "oldest"}:
        raise HTTPException(422, "sort must be newest or oldest")

    try:
        with database.session(settings.database_url, identity) as conn:
            rows = database.list_complaints(
                conn,
                student_id=identity.user_id,
                status=status_filter,
                sort=sort,
                limit=limit,
                offset=offset,
                q=q,
            )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except database.DatabaseError:
        raise HTTPException(503, "Could not load complaints.") from None

    out = []
    for row in rows:
        image_url = await _signed_image(settings, row, identity)
        out.append(_student_out(row, image_url, _analysis_status(row)))
    return out


@router.get(
    "/complaints/{complaint_id}",
    response_model=StudentComplaintOut,
    summary="Get one of the caller's own complaints",
)
async def get_own_complaint(
    request: Request,
    complaint_id: str,
    identity: database.Identity = Depends(current_identity),
) -> StudentComplaintOut:
    """404 for another student's complaint - never 403, so existence is hidden."""
    settings = _settings(request)
    try:
        with database.session(settings.database_url, identity) as conn:
            row = database.get_complaint(conn, complaint_id)
    except database.DatabaseError:
        raise HTTPException(503, "Could not load the complaint.") from None

    if row is None:
        raise HTTPException(404, "Complaint not found.")
    # Defence in depth: RLS already hid other students' rows.
    if not identity.is_admin and str(row["student_id"]) != identity.user_id:
        raise HTTPException(404, "Complaint not found.")

    image_url = await _signed_image(settings, row, identity)
    return _student_out(row, image_url, _analysis_status(row))


@router.delete(
    "/complaints/{complaint_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one of the caller's own complaints",
)
async def delete_own_complaint(
    request: Request,
    complaint_id: str,
    identity: database.Identity = Depends(current_identity),
) -> Response:
    """Delete a complaint the caller owns (admins may delete any).

    404 when the row does not exist or RLS hides it - the existence of another
    student's complaint is never disclosed. Every child row (score history, AI
    job, audit events, investigation notes, public copy) cascades via the
    foreign keys. The stored photo is removed best-effort AFTER the commit; a
    storage failure never resurrects the row.
    """
    settings = _settings(request)
    image_path: Optional[str] = None
    try:
        with database.session(settings.database_url, identity) as conn:
            existing = database.get_complaint(conn, complaint_id)
            if existing is None:
                raise HTTPException(404, "Complaint not found.")
            image_path = database.delete_complaint(conn, complaint_id)
    except database.DatabaseError:
        raise HTTPException(503, "Could not delete the complaint.") from None

    if image_path:
        # Best-effort: logged inside storage.delete_image, never raised.
        storage.delete_image(settings, image_path)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Signed-in community view - any authenticated user
# ---------------------------------------------------------------------------
@router.get(
    "/community/campus",
    response_model=list[CommunityComplaintOut],
    summary="Sanitized campus-wide small info (any signed-in user)",
)
async def community_campus(
    request: Request,
    identity: database.Identity = Depends(current_identity),
) -> list[CommunityComplaintOut]:
    """Every campus complaint as SMALL sanitized info (migration 016).

    Served by a SECURITY DEFINER function that exposes only location, status,
    a coarse band, the AI category and the date - never reporter identity,
    description text or a numeric score. Requires a signed-in user, but not
    admin.
    """
    settings = _settings(request)
    try:
        with database.session(settings.database_url, identity) as conn:
            rows = database.community_overview(conn)
    except database.DatabaseError:
        raise HTTPException(503, "Could not load the campus feed.") from None
    return [
        CommunityComplaintOut(
            id=_sid(r["id"]),
            location=r["location"],
            status=r["status"],
            band=r.get("band"),
            category=r.get("ai_category"),
            created_at=r.get("created_at"),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
@router.get(
    "/admin/complaints",
    response_model=list[AdminComplaintOut],
    summary="List every complaint (admin only)",
)
async def list_all_complaints(
    request: Request,
    identity: database.Identity = Depends(current_admin),
    status_filter: Optional[str] = Query(None, alias="status"),
    sort: str = Query("priority", description="priority | newest | oldest"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    band: Optional[str] = Query(
        None, description="Critical | High | Medium | Low | Unscored"
    ),
    category: Optional[str] = Query(None, max_length=100, description="Exact ai_category"),
    q: Optional[str] = Query(
        None, max_length=200, description="Search description, location or id"
    ),
    open_only: bool = Query(False, alias="open", description="Only not-yet-Resolved"),
) -> list[AdminComplaintOut]:
    """Every complaint, with scores and AI suggestions. Admin only.

    The triage filters (band/category/q/open) only narrow the RLS-visible set;
    they never widen it.
    """
    settings = _settings(request)
    try:
        with database.session(settings.database_url, identity) as conn:
            rows = database.list_complaints(
                conn,
                student_id=None,
                status=status_filter,
                sort=sort,
                limit=limit,
                offset=offset,
                band=band,
                category=category,
                q=q,
                open_only=open_only,
            )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except database.DatabaseError:
        raise HTTPException(503, "Could not load complaints.") from None

    out = []
    for row in rows:
        image_url = await _signed_image(settings, row, identity)
        out.append(_admin_out(row, image_url))
    return out


@router.get(
    "/admin/complaints/{complaint_id}",
    response_model=AdminComplaintOut,
    summary="Get any complaint with its score (admin only)",
)
async def get_admin_complaint(
    request: Request,
    complaint_id: str,
    identity: database.Identity = Depends(current_admin),
) -> AdminComplaintOut:
    settings = _settings(request)
    try:
        with database.session(settings.database_url, identity) as conn:
            row = database.get_complaint(conn, complaint_id)
    except database.DatabaseError:
        raise HTTPException(503, "Could not load the complaint.") from None
    if row is None:
        raise HTTPException(404, "Complaint not found.")
    image_url = await _signed_image(settings, row, identity)
    return _admin_out(row, image_url)


@router.patch(
    "/admin/complaints/{complaint_id}/status",
    response_model=AdminComplaintOut,
    summary="Change a complaint's status (admin only)",
)
async def update_status(
    request: Request,
    complaint_id: str,
    body: StatusUpdateIn,
    identity: database.Identity = Depends(current_admin),
) -> AdminComplaintOut:
    """Students can never move a status; only an admin can."""
    settings = _settings(request)
    updated: Optional[dict] = None
    try:
        with database.session(settings.database_url, identity) as conn:
            existing = database.get_complaint(conn, complaint_id)
            if existing is None:
                raise HTTPException(404, "Complaint not found.")
            updated = database.update_status(conn, complaint_id, body.status)
            if updated is not None:
                database.record_status_event(
                    conn,
                    complaint_id,
                    identity.user_id,
                    "admin",
                    existing["status"],
                    body.status,
                )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except database.DatabaseError:
        raise HTTPException(503, "Could not update the complaint.") from None

    if updated is None:
        raise HTTPException(404, "Complaint not found.")
    return _admin_out(updated, None)


@router.patch(
    "/admin/complaints/{complaint_id}/analysis",
    response_model=AdminComplaintOut,
    summary="Confirm scoring inputs and compute the score (admin only)",
)
async def confirm_and_score(
    request: Request,
    complaint_id: str,
    body: AnalysisConfirmIn,
    identity: database.Identity = Depends(current_admin),
) -> AdminComplaintOut:
    """The ONLY endpoint that can produce a score.

    The admin sends the confirmed levels explicitly (D11). An AI suggestion may
    have pre-filled the form, but nothing is scored until a human sends this.
    """
    settings = _settings(request)
    try:
        urgency, impact, safety = body.normalised()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None

    updated: Optional[dict] = None
    try:
        with database.session(settings.database_url, identity) as conn:
            row = database.confirm_analysis(
                conn,
                complaint_id,
                urgency=urgency,
                impact=impact,
                safety=safety,
                actor_id=identity.user_id,
            )
            # One recurrence snapshot for this request (D5).
            count = database.recurrence_snapshot(
                conn, location_code=row.get("location_code"), exclude_id=complaint_id
            )
            created = row["created_at"]
            age_days = scoring.age_days_between(created) if created else 0
            try:
                result = scoring.score_complaint(
                    urgency=urgency,
                    impact=impact,
                    safety=safety,
                    age_days=age_days,
                    recurrence_count=count,
                    recurrence_not_applicable=bool(row.get("recurrence_na"))
                    or row.get("location_code") is None,
                )
            except scoring.ScoringError as exc:
                raise HTTPException(422, str(exc)) from None

            database.save_score(
                conn,
                complaint_id,
                score=result.score,
                breakdown=result.breakdown,
                band=result.band,
                actor_id=identity.user_id,
            )
            updated = database.get_complaint(conn, complaint_id) or row
    except database.DatabaseError as exc:
        raise HTTPException(404, str(exc)) from None

    if updated is None:
        raise HTTPException(404, "Complaint not found.")
    return _admin_out(updated, None)


async def _require_complaint(
    settings: config.Settings, identity: database.Identity, complaint_id: str
) -> None:
    """404 when the complaint does not exist (RLS-hidden rows count as absent)."""
    try:
        with database.session(settings.database_url, identity) as conn:
            row = database.get_complaint(conn, complaint_id)
    except database.DatabaseError:
        raise HTTPException(503, "Could not load the complaint.") from None
    if row is None:
        raise HTTPException(404, "Complaint not found.")


@router.get(
    "/admin/complaints/{complaint_id}/events",
    response_model=list[ComplaintEventOut],
    summary="Audit trail for one complaint (admin only)",
)
async def list_complaint_events(
    request: Request,
    complaint_id: str,
    identity: database.Identity = Depends(current_admin),
) -> list[ComplaintEventOut]:
    """The append-only complaint_events history, newest first."""
    settings = _settings(request)
    await _require_complaint(settings, identity, complaint_id)
    try:
        with database.session(settings.database_url, identity) as conn:
            rows = database.list_events(conn, complaint_id)
    except database.DatabaseError:
        raise HTTPException(503, "Could not load the event history.") from None
    return [
        ComplaintEventOut(
            id=r["id"],
            actor_role=r["actor_role"],
            actor_email=r.get("actor_email"),
            event_type=r["event_type"],
            from_value=r.get("from_value"),
            to_value=r.get("to_value"),
            created_at=r.get("created_at"),
        )
        for r in rows
    ]


@router.get(
    "/admin/complaints/{complaint_id}/notes",
    response_model=list[InvestigationNoteOut],
    summary="Internal investigation notes (admin only)",
)
async def list_complaint_notes(
    request: Request,
    complaint_id: str,
    identity: database.Identity = Depends(current_admin),
) -> list[InvestigationNoteOut]:
    """Admin-only notes. Students never see these."""
    settings = _settings(request)
    await _require_complaint(settings, identity, complaint_id)
    try:
        with database.session(settings.database_url, identity) as conn:
            rows = database.list_notes(conn, complaint_id)
    except database.DatabaseError:
        raise HTTPException(503, "Could not load the notes.") from None
    return [
        InvestigationNoteOut(
            id=str(r["id"]),
            body=r["body"],
            author_kind=r["author_kind"],
            author_email=r.get("author_email"),
            created_at=r.get("created_at"),
        )
        for r in rows
    ]


@router.post(
    "/admin/complaints/{complaint_id}/notes",
    response_model=InvestigationNoteOut,
    summary="Add an internal investigation note (admin only)",
)
async def create_complaint_note(
    request: Request,
    complaint_id: str,
    body: NoteIn,
    identity: database.Identity = Depends(current_admin),
) -> InvestigationNoteOut:
    """Store one admin note and append a 'note_added' audit event."""
    settings = _settings(request)
    text = body.body.strip()
    if not text:
        raise HTTPException(422, "The note cannot be empty.")
    await _require_complaint(settings, identity, complaint_id)
    try:
        with database.session(settings.database_url, identity) as conn:
            row = database.add_note(
                conn, complaint_id, author_id=identity.user_id, body=text
            )
    except database.DatabaseError:
        raise HTTPException(503, "Could not save the note.") from None
    if row is None:
        raise HTTPException(503, "Could not save the note.")
    return InvestigationNoteOut(
        id=str(row["id"]),
        body=row["body"],
        author_kind=row["author_kind"],
        author_email=None,
        created_at=row.get("created_at"),
    )


@router.get(
    "/admin/analytics/summary",
    response_model=AdminAnalyticsOut,
    summary="Dashboard counts (admin only)",
)
async def admin_summary(
    request: Request,
    identity: database.Identity = Depends(current_admin),
) -> AdminAnalyticsOut:
    """Counts for the dashboard.

    `unscored` counts priority_score IS NULL. A stored 0 is a REAL score and is
    counted inside its band, never as unscored (D7).
    """
    settings = _settings(request)
    by_status = {name: 0 for name in scoring.STATUSES}
    by_band = {name: 0 for name in scoring.BANDS}

    try:
        with database.session(settings.database_url, identity) as conn:
            rows = database.list_complaints(
                conn, student_id=None, sort="newest", limit=1000, offset=0
            )
    except database.DatabaseError:
        raise HTTPException(503, "Could not load analytics.") from None

    unscored = 0
    for row in rows:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
        score = row.get("priority_score")
        if score is None:
            unscored += 1
            continue
        try:
            band = scoring.band_for_score(float(score))
        except scoring.ScoringError:
            unscored += 1
            continue
        by_band[band] = by_band.get(band, 0) + 1

    return AdminAnalyticsOut(
        total=len(rows),
        by_status=by_status,
        by_band=by_band,
        unscored=unscored,
        unresolved=len(rows) - by_status.get("Resolved", 0),
    )


# ---------------------------------------------------------------------------
# Public community feed - no authentication
# ---------------------------------------------------------------------------
@router.post(
    "/admin/complaints/{complaint_id}/public-approval",
    response_model=PublicComplaintOut,
    summary="Publish a sanitized complaint to the community feed (admin only)",
)
async def approve_public(
    request: Request,
    complaint_id: str,
    body: PublicApprovalIn,
    identity: database.Identity = Depends(current_admin),
) -> PublicComplaintOut:
    """Approve one complaint for publication.

    This is the ONLY route that can make a complaint public. It is admin-only,
    and the published text is supplied by the admin rather than copied from the
    complaint, so the reporter's identity and words are never exposed by
    default.

    Re-approving updates the existing entry rather than duplicating it.
    """
    settings = _settings(request)
    try:
        with database.session(settings.database_url, identity) as conn:
            if database.get_complaint(conn, complaint_id) is None:
                raise HTTPException(404, "Complaint not found.")
            entry = database.approve_for_public(
                conn,
                complaint_id,
                public_summary=body.public_summary.strip(),
                public_category=body.public_category.strip(),
                public_location=body.public_location.strip(),
                actor_id=identity.user_id,
            )
            conn.execute(
                """
                INSERT INTO public.complaint_events
                    (complaint_id, actor_id, actor_role, event_type, to_value)
                VALUES (%s, %s, 'admin', 'public_approved', 'published')
                """,
                (complaint_id, identity.user_id),
            )
    except database.DatabaseError:
        raise HTTPException(503, "Could not publish the complaint.") from None

    return PublicComplaintOut(
        id=_sid(entry["id"]),
        public_summary=entry["public_summary"],
        public_category=entry["public_category"],
        public_location=entry["public_location"],
        status=entry["status"],
        approved_at=entry.get("approved_at"),
    )


@router.delete(
    "/admin/complaints/{complaint_id}/public-approval",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Withdraw a complaint from the community feed (admin only)",
)
async def revoke_public(
    request: Request,
    complaint_id: str,
    identity: database.Identity = Depends(current_admin),
) -> Response:
    """Withdraw publication.

    The entry is kept but approved_at is cleared, so it becomes a draft and the
    public policy hides it again. Nothing is deleted from the audit trail.
    """
    settings = _settings(request)
    try:
        with database.session(settings.database_url, identity) as conn:
            revoked = database.revoke_public_approval(conn, complaint_id)
            if revoked:
                conn.execute(
                    """
                    INSERT INTO public.complaint_events
                        (complaint_id, actor_id, actor_role, event_type, to_value)
                    VALUES (%s, %s, 'admin', 'public_revoked', 'withdrawn')
                    """,
                    (complaint_id, identity.user_id),
                )
    except database.DatabaseError:
        raise HTTPException(503, "Could not withdraw the complaint.") from None

    if not revoked:
        raise HTTPException(404, "That complaint is not published.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/admin/complaints/{complaint_id}/public-approval",
    response_model=Optional[PublicComplaintOut],
    summary="Whether a complaint is published, and with what text (admin only)",
)
async def public_approval_state(
    request: Request,
    complaint_id: str,
    identity: database.Identity = Depends(current_admin),
) -> Optional[PublicComplaintOut]:
    """Publication state for one complaint; null when it is not published."""
    settings = _settings(request)
    try:
        with database.session(settings.database_url, identity) as conn:
            entry = database.get_public_entry(conn, complaint_id)
    except database.DatabaseError:
        raise HTTPException(503, "Could not read the publication state.") from None

    if entry is None:
        return None
    return PublicComplaintOut(
        id=_sid(entry["id"]),
        public_summary=entry["public_summary"],
        public_category=entry["public_category"],
        public_location=entry["public_location"],
        status=entry["status"],
        approved_at=entry.get("approved_at"),
    )


@router.get(
    "/public/complaints",
    response_model=list[PublicComplaintOut],
    summary="Approved, sanitized complaints",
)
async def public_feed(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    category: Optional[str] = Query(None),
) -> list[PublicComplaintOut]:
    """Unauthenticated, but only ever reads public_complaints.

    That table has no student_id, no score, no free-text description and no
    internal location code, so a private field cannot leak from here.
    """
    settings = _settings(request)
    # No identity: this endpoint is public, so RLS is evaluated for anon.
    anon = database.Identity("00000000-0000-0000-0000-000000000000", "anon")
    try:
        with database.session(settings.database_url, anon) as conn:
            rows = database.list_public_complaints(
                conn, limit=limit, offset=offset, category=category
            )
    except database.DatabaseError:
        raise HTTPException(503, "Could not load the public feed.") from None

    return [
        PublicComplaintOut(
            id=_sid(r["id"]),
            public_summary=r["public_summary"],
            public_category=r["public_category"],
            public_location=r["public_location"],
            status=r["status"],
            approved_at=r.get("approved_at"),
        )
        for r in rows
    ]


def build_router() -> APIRouter:
    """Return a fresh APIRouter carrying this module's routes.

    FastAPI 0.142 will only include a given APIRouter instance once; a second
    include_router() on the same object raises and then registers nothing.
    app.main builds an app at import time and tests call create_app() again, so
    a shared router would leave every later app with zero routes. Cloning the
    routes onto a new router keeps create_app() genuinely repeatable.
    """
    fresh = APIRouter()
    for route in router.routes:
        fresh.routes.append(route)
    return fresh
