"""
CampusLens - Supabase PostgreSQL data access.

Every statement is parameterised; no SQL is ever built by string formatting of
user input. Identifier names come only from the fixed tuples in this module.

Row Level Security is the real authorisation boundary. Each request opens a
transaction and issues::

    SET LOCAL ROLE authenticated;
    SET LOCAL request.jwt.claims = '{"sub":"<uuid>","role":"authenticated"}';

so the policies written in the Stage 1 migrations (001-009) are evaluated by
PostgreSQL exactly as they are for a browser client. The application never
"decides" who may see a row; it only supplies the verified identity.

The service-role key is NEVER used for data access. Only the pooled
``DATABASE_URL`` is used, and the identity is applied with SET LOCAL ROLE
inside the request's transaction so it is reverted on commit or rollback.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Any, Iterator, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import scoring

logger = logging.getLogger("campuslens.db")

POOL_MIN_SIZE = 1
POOL_MAX_SIZE = 8

PRIVATE_COMPLAINT_COLUMNS: tuple[str, ...] = (
    "id", "student_id", "description", "location_raw", "location_code",
    "recurrence_na", "image_path",
    "ai_category", "ai_summary", "ai_evidence", "ai_uncertainty",
    "ai_urgency", "ai_impact", "ai_safety",
    "confirmed_urgency", "confirmed_impact", "confirmed_safety",
    "analysis_confirmed_at", "confirmed_by",
    "priority_score", "score_breakdown", "score_version", "score_computed_at",
    "status", "created_at", "updated_at", "resolved_at",
)

_SELECT_LIST = ", ".join(PRIVATE_COMPLAINT_COLUMNS)

# SQL CASE mirroring scoring.band_for_score() so a band filter compares against
# exactly the label the admin sees in the response body (which is derived from
# priority_score, never from a stored column - complaints has no band column).
# The boundaries are the scoring module's constants, interpolated as integers:
# no user input ever reaches this string.
_BAND_CASE_SQL = f"""
    CASE
        WHEN priority_score IS NULL THEN 'Unscored'
        WHEN priority_score <= {scoring.BAND_LOW_MAX} THEN 'Low'
        WHEN priority_score <= {scoring.BAND_MEDIUM_MAX} THEN 'Medium'
        WHEN priority_score <= {scoring.BAND_HIGH_MAX} THEN 'High'
        ELSE 'Critical'
    END
"""

PUBLIC_COLUMNS: tuple[str, ...] = (
    "id", "public_summary", "public_category", "public_location",
    "status", "approved_at",
)

_PUBLIC_SELECT_LIST = ", ".join(PUBLIC_COLUMNS)

_pool: Optional[ConnectionPool] = None


class DatabaseError(RuntimeError):
    """A database operation failed. Never carries the connection URL."""


class Identity:
    """The verified caller, derived from a Supabase Auth JWT.

    `role` is read from the profiles table, never from the token's own claims,
    so a client cannot grant itself admin by crafting a JWT.
    """

    __slots__ = ("user_id", "role")

    def __init__(self, user_id: str, role: str) -> None:
        self.user_id = user_id
        self.role = role

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def get_pool(database_url: str) -> ConnectionPool:
    """Build (once) the shared connection pool."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            database_url,
            min_size=POOL_MIN_SIZE,
            max_size=POOL_MAX_SIZE,
            open=False,
            kwargs={"row_factory": dict_row, "autocommit": True},
        )
        _pool.open()
    return _pool


def close_pool() -> None:
    """Close the pool on shutdown."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def session(database_url: str, identity: Identity) -> Iterator[Any]:
    """Open a transaction acting AS the verified caller, so RLS applies."""
    pool = get_pool(database_url)
    try:
        with pool.connection() as conn:
            previous_autocommit = conn.autocommit
            conn.autocommit = False
            try:
                claims = json.dumps({"sub": str(identity.user_id), "role": identity.role})
                conn.execute("SET LOCAL ROLE authenticated")
                # set_config() takes a real bind parameter; a bare
                # `SET ... = %s` does NOT, because psycopg3 turns %s into $1 and
                # PostgreSQL rejects bind parameters in SET statements
                # (syntax error at or near "$1"). `true` makes it transaction
                # scoped, exactly like SET LOCAL.
                conn.execute(
                    "SELECT set_config('request.jwt.claims', %s, true)", (claims,)
                )
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.autocommit = previous_autocommit
    except psycopg.Error as exc:
        logger.error("database error (%s)", type(exc).__name__)
        raise DatabaseError("Database operation failed.") from None


def load_role(conn: Any, user_id: str) -> Optional[str]:
    """Role for a user id, read from profiles (migrations 001/012)."""
    row = conn.execute(
        "SELECT role FROM public.profiles WHERE id = %s", (user_id,)
    ).fetchone()
    return row["role"] if row else None


def load_profile(conn: Any, user_id: str) -> Optional[dict[str, Any]]:
    """The caller's own profile row.

    Returns the row only for the caller themselves - the id is matched exactly,
    and RLS restricts this to the row the caller owns. Returns None when there
    is no profiles row, which normally means the signup trigger (migration 012)
    has not created one yet.

    Only non-sensitive fields are selected: id, email, full_name, role and the
    creation timestamp. No password material, no auth.users columns, no tokens.
    """
    row = conn.execute(
        """
        SELECT id, email, full_name, role, created_at
          FROM public.profiles
         WHERE id = %s
        """,
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Complaints
# ---------------------------------------------------------------------------
def create_complaint(
    conn: Any,
    *,
    student_id: str,
    description: str,
    location_raw: str,
    location_code: Optional[str],
    image_path: Optional[str],
) -> dict[str, Any]:
    """Insert one complaint and return it.

    The AI columns and every score column are left NULL: a submission is never
    blocked on, or influenced by, an AI provider.
    """
    row = conn.execute(
        f"""
        INSERT INTO public.complaints
            (student_id, description, location_raw, location_code, image_path)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING {_SELECT_LIST}
        """,
        (student_id, description, location_raw, location_code, image_path),
    ).fetchone()
    return dict(row)


def record_created_event(conn: Any, complaint_id: str, actor_id: str, role: str) -> None:
    """Append the 'created' audit row."""
    conn.execute(
        """
        INSERT INTO public.complaint_events
            (complaint_id, actor_id, actor_role, event_type, to_value)
        VALUES (%s, %s, %s, 'created', 'Reported')
        """,
        (complaint_id, actor_id, role),
    )


def get_complaint(conn: Any, complaint_id: str) -> Optional[dict[str, Any]]:
    """One complaint, as RLS allows the caller to see it.

    Returns None both when the row is absent and when RLS hides it, so a
    student cannot probe for another student's complaint.
    """
    row = conn.execute(
        f"SELECT {_SELECT_LIST} FROM public.complaints WHERE id = %s",
        (complaint_id,),
    ).fetchone()
    return dict(row) if row else None


def delete_complaint(conn: Any, complaint_id: str) -> Optional[str]:
    """Delete one complaint and return its image_path (or None).

    RLS decides what may be deleted: complaints_own_delete for the owner,
    complaints_admin_all for an admin. Child rows (scores, jobs, events, notes,
    public copies) cascade in PostgreSQL. The returned image_path lets the
    caller remove the stored object best-effort.
    """
    row = conn.execute(
        """
        DELETE FROM public.complaints
         WHERE id = %s
         RETURNING image_path
        """,
        (complaint_id,),
    ).fetchone()
    return row["image_path"] if row else None


def community_overview(conn: Any, limit: int = 500) -> list[dict[str, Any]]:
    """Sanitized campus-wide feed via the migration-016 SECURITY DEFINER fn.

    Contains ONLY id/location/status/band/ai_category/created_at - never a
    reporter identity, description text or a numeric score.
    """
    rows = conn.execute(
        "SELECT * FROM public.community_overview() LIMIT %s",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_complaints(
    conn: Any,
    *,
    student_id: Optional[str] = None,
    status: Optional[str] = None,
    sort: str = "priority",
    limit: int = 50,
    offset: int = 0,
    band: Optional[str] = None,
    category: Optional[str] = None,
    q: Optional[str] = None,
    open_only: bool = False,
) -> list[dict[str, Any]]:
    """List complaints the caller may see.

    `student_id` comes from the verified token, never from the request body or
    query string. The triage filters (band/category/q/open_only) are admin
    conveniences applied on top of the same RLS-visible set - they can only
    narrow what the policies already allow.
    """
    if status is not None and status not in scoring.STATUSES:
        raise ValueError(f"status must be one of {list(scoring.STATUSES)}")
    if sort not in {"priority", "newest", "oldest"}:
        raise ValueError("sort must be priority, newest or oldest")
    if band is not None and band not in (*scoring.BANDS, "Unscored"):
        raise ValueError(
            f"band must be one of {list(scoring.BANDS)} or 'Unscored'"
        )

    # NULLS LAST keeps Unscored (NULL) rows below every real score, including 0.
    order = {
        "priority": "priority_score DESC NULLS LAST, created_at DESC",
        "newest": "created_at DESC",
        "oldest": "created_at ASC",
    }[sort]

    clauses: list[str] = []
    params: list[Any] = []
    if student_id is not None:
        clauses.append("student_id = %s")
        params.append(student_id)
    if status is not None:
        clauses.append("status = %s")
        params.append(status)
    if band is not None:
        clauses.append(f"({_BAND_CASE_SQL}) = %s")
        params.append(band)
    if category is not None:
        clauses.append("ai_category = %s")
        params.append(category)
    if q:
        clauses.append(
            "(description ILIKE %s OR location_raw ILIKE %s OR id::text ILIKE %s)"
        )
        like = f"%{q}%"
        params.extend([like, like, like])
    if open_only:
        clauses.append("status <> 'Resolved'")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend([limit, offset])

    rows = conn.execute(
        f"""
        SELECT {_SELECT_LIST}
        FROM public.complaints
        {where}
        ORDER BY {order}
        LIMIT %s OFFSET %s
        """,
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def list_events(conn: Any, complaint_id: str, limit: int = 200) -> list[dict[str, Any]]:
    """The append-only audit trail for one complaint, newest first.

    The profiles join is cosmetic (actor email for the admin UI) and is allowed
    by the profiles_admin_all RLS policy; authorisation comes from the caller
    being an admin, enforced upstream.
    """
    rows = conn.execute(
        """
        SELECT e.id, e.actor_role, e.event_type, e.from_value, e.to_value,
               e.created_at, p.email AS actor_email
          FROM public.complaint_events e
          LEFT JOIN public.profiles p ON p.id = e.actor_id
         WHERE e.complaint_id = %s
         ORDER BY e.created_at DESC, e.id DESC
         LIMIT %s
        """,
        (complaint_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def list_notes(conn: Any, complaint_id: str, limit: int = 200) -> list[dict[str, Any]]:
    """Internal investigation notes for one complaint, newest first."""
    rows = conn.execute(
        """
        SELECT n.id, n.body, n.author_kind, n.created_at,
               p.email AS author_email
          FROM public.investigation_notes n
          LEFT JOIN public.profiles p ON p.id = n.author_id
         WHERE n.complaint_id = %s
         ORDER BY n.created_at DESC, n.id DESC
         LIMIT %s
        """,
        (complaint_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def add_note(
    conn: Any, complaint_id: str, *, author_id: str, body: str
) -> Optional[dict[str, Any]]:
    """Insert one admin note and append a 'note_added' audit event.

    The event's to_value stays NULL: complaint_events is readable by the
    complaint's student, so note content must never be copied there.
    """
    row = conn.execute(
        """
        INSERT INTO public.investigation_notes
            (complaint_id, author_id, author_kind, body)
        VALUES (%s, %s, 'admin', %s)
        RETURNING id, body, author_kind, created_at
        """,
        (complaint_id, author_id, body),
    ).fetchone()
    conn.execute(
        """
        INSERT INTO public.complaint_events
            (complaint_id, actor_id, actor_role, event_type, to_value)
        VALUES (%s, %s, 'admin', 'note_added', NULL)
        """,
        (complaint_id, author_id),
    )
    return dict(row) if row else None


def update_status(
    conn: Any, complaint_id: str, new_status: str
) -> Optional[dict[str, Any]]:
    """Move a complaint between the three allowed statuses."""
    if new_status not in scoring.STATUSES:
        raise ValueError(f"status must be one of {list(scoring.STATUSES)}")

    row = conn.execute(
        f"""
        UPDATE public.complaints
           SET status = %s,
               resolved_at = CASE WHEN %s = 'Resolved' THEN now() ELSE resolved_at END
         WHERE id = %s
        RETURNING {_SELECT_LIST}
        """,
        (new_status, new_status, complaint_id),
    ).fetchone()
    return dict(row) if row else None


def record_status_event(
    conn: Any,
    complaint_id: str,
    actor_id: str,
    role: str,
    previous: Optional[str],
    new: str,
) -> None:
    """Append a status_changed audit row."""
    conn.execute(
        """
        INSERT INTO public.complaint_events
            (complaint_id, actor_id, actor_role, event_type, from_value, to_value)
        VALUES (%s, %s, %s, 'status_changed', %s, %s)
        """,
        (complaint_id, actor_id, role, previous, new),
    )


def confirm_analysis(
    conn: Any,
    complaint_id: str,
    *,
    urgency: str,
    impact: str,
    safety: str,
    actor_id: str,
) -> dict[str, Any]:
    """Store admin-confirmed levels. This is the only way a score is produced."""
    row = conn.execute(
        f"""
        UPDATE public.complaints
           SET confirmed_urgency = %s,
               confirmed_impact  = %s,
               confirmed_safety  = %s,
               analysis_confirmed_at = now(),
               confirmed_by = %s
         WHERE id = %s
        RETURNING {_SELECT_LIST}
        """,
        (urgency, impact, safety, actor_id, complaint_id),
    ).fetchone()
    if row is None:
        raise DatabaseError("Complaint not found.")
    return dict(row)


# ---------------------------------------------------------------------------
# Recurrence (D5) - ONE snapshot per request so rows never disagree
# ---------------------------------------------------------------------------
def recurrence_snapshot(
    conn: Any, *, location_code: Optional[str], exclude_id: Optional[str] = None
) -> int:
    """Count prior similar complaints in the 90-day window.

    A NULL location_code means recurrence is not applicable (D10), so the count
    is 0. Callers compute this ONCE per response and reuse it, so two
    complaints in the same group always receive the same number.
    """
    if location_code is None:
        return 0
    row = conn.execute(
        """
        SELECT count(*) AS n
          FROM public.complaints
         WHERE location_code = %s
           AND created_at >= now() - make_interval(days => %s)
           AND (%s::uuid IS NULL OR id <> %s::uuid)
        """,
        (location_code, scoring.RECURRENCE_WINDOW_DAYS, exclude_id, exclude_id),
    ).fetchone()
    return int(row["n"]) if row else 0


def save_score(
    conn: Any,
    complaint_id: str,
    *,
    score: float,
    breakdown: dict[str, Any],
    band: str,
    actor_id: str,
) -> None:
    """Persist a computed score and append one history row (D9)."""
    conn.execute(
        """
        UPDATE public.complaints
           SET priority_score = %s, score_breakdown = %s,
               score_computed_at = now()
         WHERE id = %s
        """,
        (score, json.dumps(breakdown), complaint_id),
    )
    age = breakdown.get("age", {}) or {}
    recurrence = breakdown.get("recurrence", {}) or {}
    conn.execute(
        """
        INSERT INTO public.complaint_scores
            (complaint_id, age_days, recurrence_count, score, band, band_raw,
             safety_floor_applied, trigger_reason)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'admin_confirm')
        """,
        (
            complaint_id,
            int(age.get("days", 0)),
            int(recurrence.get("count", 0)),
            score,
            band,
            str(breakdown.get("band_raw", band)),
            bool(breakdown.get("safety_floor_applied", False)),
        ),
    )
    conn.execute(
        """
        INSERT INTO public.complaint_events
            (complaint_id, actor_id, actor_role, event_type, to_value)
        VALUES (%s, %s, 'admin', 'analysis_confirmed', %s)
        """,
        (complaint_id, actor_id, band),
    )


# ---------------------------------------------------------------------------
# AI jobs (optional enrichment; never required for a complaint to exist)
# ---------------------------------------------------------------------------
# The seven AI columns, in the exact parameter order of migration 014's
# store_ai_suggestion(). Scores and status are deliberately absent.
AI_SUGGESTION_COLUMNS: tuple[str, ...] = (
    "ai_category", "ai_summary", "ai_evidence", "ai_uncertainty",
    "ai_urgency", "ai_impact", "ai_safety",
)


def enqueue_analysis_job(conn: Any, complaint_id: str) -> None:
    """Create the optional AI job. Never raises for a missing provider."""
    conn.execute(
        """
        INSERT INTO public.analysis_jobs (complaint_id, status)
        VALUES (%s, 'pending')
        ON CONFLICT DO NOTHING
        """,
        (complaint_id,),
    )


def store_ai_suggestion(conn: Any, complaint_id: str, suggestion: dict) -> None:
    """Persist the AI suggestion through migration 014's SECURITY DEFINER
    function, which writes ONLY the seven ai_* columns of one row.

    The old raw `UPDATE ... SET ai_*` ran as Identity(complaint_id, "system"),
    a session that satisfies no UPDATE policy on complaints: PostgreSQL
    silently filtered the statement to zero rows, so the admin card's
    "Full AI assessment" always showed "Not provided". The function has no
    parameters for priority_score, status or anything else, so elevation can
    never become a scoring backdoor.
    """
    values = tuple(suggestion.get(column) for column in AI_SUGGESTION_COLUMNS)
    placeholders = ", ".join(["%s"] * (len(AI_SUGGESTION_COLUMNS) + 1))
    conn.execute(
        f"SELECT public.store_ai_suggestion({placeholders})",
        (complaint_id, *values),
    )


def record_job_failure(conn: Any, complaint_id: str, error: str, attempts: int) -> None:
    """Record an AI failure. The complaint itself is never touched.

    Delegates to migration 014's SECURITY DEFINER function: the system
    session (sub = complaint id) has no INSERT/UPDATE policy on
    analysis_jobs, so the raw upsert used to raise 42501 and the failure was
    silently lost.
    """
    conn.execute(
        "SELECT public.record_job_failure(%s, %s, %s)",
        (complaint_id, attempts, error[:500]),
    )


def store_auto_score(conn: Any, complaint_id: str, actor_id: Optional[str]) -> None:
    """Score a complaint automatically from its own stored ai_* levels.

    Delegates to migration 015's SECURITY DEFINER function. The system
    session (sub = complaint id) satisfies no UPDATE policy on complaints, so
    the function - like store_ai_suggestion - is elevated and bypasses RLS to
    write the score, the score_breakdown, the complaint_scores history row and
    one audit event. It reads ONLY the row's ai_urgency/ai_impact/ai_safety;
    there is no parameter for levels or a score, so this can never be fed a
    number from the caller.

    The function never raises and never re-scores an already-scored row, so a
    second call (e.g. an AI re-run) is a harmless no-op. Best-effort: any error
    is swallowed here so a scoring hiccup can never fail a submission whose
    complaint and suggestion are already committed.
    """
    try:
        conn.execute(
            "SELECT public.store_auto_score(%s, %s)",
            (complaint_id, actor_id),
        )
    except Exception:
        logger.warning("could not compute automatic score for %s", complaint_id)


# ---------------------------------------------------------------------------
# Public feed (no authentication; only approved rows)
# ---------------------------------------------------------------------------
def approve_for_public(
    conn: Any,
    complaint_id: str,
    *,
    public_summary: str,
    public_category: str,
    public_location: str,
    actor_id: str,
) -> dict[str, Any]:
    """Publish (or re-publish) one complaint to the community feed.

    This is the ONLY write path into public_complaints, and it is reachable
    only from an admin-only route. approved_at is set explicitly here - it is
    never defaulted - so a row is public because an admin decided, not because
    it was inserted.

    The caller supplies sanitized text. Nothing is copied from the complaint, so
    the reporter's own words and identity can never leak by accident.
    """
    row = conn.execute(
        """
        INSERT INTO public.public_complaints
            (source_complaint_id, public_summary, public_category,
             public_location, approved_by, approved_at)
        VALUES (%s, %s, %s, %s, %s, now())
        ON CONFLICT (source_complaint_id) DO UPDATE
            SET public_summary  = EXCLUDED.public_summary,
                public_category = EXCLUDED.public_category,
                public_location = EXCLUDED.public_location,
                approved_by     = EXCLUDED.approved_by,
                approved_at     = EXCLUDED.approved_at
        RETURNING id, public_summary, public_category, public_location,
                  status, approved_at
        """,
        (complaint_id, public_summary, public_category, public_location, actor_id),
    ).fetchone()
    if row is None:
        raise DatabaseError("Complaint not found.")
    return dict(row)


def revoke_public_approval(conn: Any, complaint_id: str) -> bool:
    """Withdraw a complaint from the public feed.

    The row is kept but approved_at is cleared, so it becomes a draft again and
    the public policy hides it. Returning False means nothing was published.
    """
    row = conn.execute(
        """
        UPDATE public.public_complaints
           SET approved_at = NULL, approved_by = NULL
         WHERE source_complaint_id = %s
        RETURNING id
        """,
        (complaint_id,),
    ).fetchone()
    return row is not None


def get_public_entry(conn: Any, complaint_id: str) -> Optional[dict[str, Any]]:
    """The published entry for a complaint, or None if it is not published."""
    row = conn.execute(
        """
        SELECT id, public_summary, public_category, public_location,
               status, approved_at
          FROM public.public_complaints
         WHERE source_complaint_id = %s
        """,
        (complaint_id,),
    ).fetchone()
    return dict(row) if row else None


def list_public_complaints(
    conn: Any, *, limit: int = 50, offset: int = 0, category: Optional[str] = None
) -> list[dict[str, Any]]:
    """Approved, sanitized complaints only.

    Reads public_complaints, which physically has no student_id, no score and
    no free-text description, so nothing private can leak from here.
    """
    if category:
        rows = conn.execute(
            f"""
            SELECT {_PUBLIC_SELECT_LIST}
              FROM public.public_complaints
             WHERE public_category = %s
             ORDER BY approved_at DESC
             LIMIT %s OFFSET %s
            """,
            (category, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            f"""
            SELECT {_PUBLIC_SELECT_LIST}
              FROM public.public_complaints
             ORDER BY approved_at DESC
             LIMIT %s OFFSET %s
            """,
            (limit, offset),
        ).fetchall()
    return [dict(r) for r in rows]
