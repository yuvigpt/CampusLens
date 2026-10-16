"""
CampusLens - backfill for complaints that are still missing a priority score.

Targets complaints where ``priority_score IS NULL`` (the "Unscored" state) and
writes a deterministic auto-score for each, reusing the same scorer and database
helpers that the admin-confirmed scoring path uses. (Submission itself never
scores: a fresh complaint stays NULL until an admin confirms or this script
runs.)

The computation itself is pure Python (``scoring.score_complaint``). The only
writes are the three statements inside ``database.save_score``:

    UPDATE public.complaints     (priority_score, score_breakdown, ...)
    INSERT public.complaint_scores
    INSERT public.complaint_events

so the history/audit trail stays consistent with the admin-confirmed scoring
path.

The backfill must run with admin authority (the `complaints_admin_all` policy
reads `public.is_admin()`, which is true only for a `profiles` row with `role =
'admin'`). Pass that admin's profile id via ``ADMIN_USER_ID``; the script
refuses to proceed if it is not an admin.

Usage (from the repository root):

    # Show what would be scored, without writing anything.
    ADMIN_USER_ID=<admin uuid> python backend/backfill_unscored_scores.py --dry-run

    # Actually write the scores.
    ADMIN_USER_ID=<admin uuid> python backend/backfill_unscored_scores.py

The script reads ``DATABASE_URL`` from the environment or from ``backend/.env``.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import database, scoring  # noqa: E402

logger = logging.getLogger("campuslens.backfill")

ERROR_MESSAGE = (
    "Please make sure you ran this with the project virtualenv activated "
    "and with DATABASE_URL available."
)


def _env_or_env_file(name: str, default: str | None = None) -> str | None:
    """Read a value from the environment, then from backend/.env as a fallback."""
    value = os.environ.get(name)
    if value:
        return value
    env_file = Path(__file__).resolve().parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            if key.strip() == name:
                return val.strip().strip("'\"")
    return default


def _unscored_rows(conn: Any) -> list[dict[str, Any]]:
    return list(
        conn.execute(
            """
            SELECT id, created_at, recurrence_na, location_code
              FROM public.complaints
             WHERE priority_score IS NULL
             ORDER BY id
            """
        ).fetchall()
    )


def _compute_score(row: dict[str, Any]) -> scoring.ScoreResult:
    return scoring.score_complaint(
        urgency="Low",
        impact="Low",
        safety="Low",
        age_days=scoring.age_days_between(row["created_at"]),
        recurrence_count=0,
        recurrence_not_applicable=bool(row.get("recurrence_na"))
        or row.get("location_code") is None,
    )


def _score_and_persist(
    conn: Any, complaint_id: str, row: dict[str, Any], actor_id: str
) -> scoring.ScoreResult:
    result = _compute_score(row)
    database.save_score(
        conn,
        complaint_id,
        score=result.score,
        breakdown=result.breakdown,
        band=result.band,
        actor_id=actor_id,
    )
    return result


def _dry_run(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        result = _compute_score(row)
        print(
            f"  {row['id']}  band={result.band:<8} "
            f"score={result.score:6.2f}  age_days={result.breakdown['age']['days']}"
        )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("campuslens.db").setLevel(logging.WARNING)

    db_url = _env_or_env_file("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL is required (environment or backend/.env).")
        return 1

    admin_id = os.environ.get("ADMIN_USER_ID")
    if not admin_id:
        logger.error(
            "ADMIN_USER_ID (an admin profile id) is required. "
            "Find one with: SELECT id FROM public.profiles WHERE role = 'admin';"
        )
        return 1

    dry_run = "--dry-run" in sys.argv

    with database.session(db_url, database.Identity(admin_id, "admin")) as conn:
        is_admin = conn.execute("SELECT public.is_admin()").fetchone()["is_admin"]
        if not is_admin:
            logger.error("%s is not an admin: is_admin() returned false.", admin_id)
            return 1

        rows = _unscored_rows(conn)
        logger.info("Found %d complaint(s) without a priority score.", len(rows))

        if dry_run:
            _dry_run(rows)
            logger.info("Dry run complete - nothing was written.")
            return 0

        processed = 0
        skipped = 0
        for row in rows:
            try:
                _score_and_persist(conn, row["id"], row, admin_id)
            except scoring.ScoringError as exc:
                skipped += 1
                logger.warning(
                    "Skipped %s: %s", row["id"], exc, exc_info=True
                )
                continue
            processed += 1

    logger.info("Backfill complete: %d scored, %d skipped.", processed, skipped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
