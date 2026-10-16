"""
CampusLens - backfill for complaints whose AI suggestion was never stored.

Every complaint submitted before migration 014 has NULL ai_* columns: the old
write-back ran as the system identity, matched no UPDATE policy on
complaints, and PostgreSQL silently updated zero rows (no error, no warning).
The admin card's "Full AI assessment" therefore showed "Not provided" for the
whole backlog, even when the analysis had succeeded in the 201 response.

This script re-runs the analysis for each affected row and stores it through
the exact production path: a system-identity session calling migration 014's
``store_ai_suggestion()`` (which writes ONLY the seven ai_* columns - scores
and status are not parameters of the function, so they cannot be touched).

Scope and honesty:

* Only rows matching ``ai_summary IS NULL AND ai_category IS NULL`` are
  considered - never a row that already holds an analysis.
* The original photo is NOT re-uploaded to the provider; analysis runs on the
  description text alone (``image_bytes=None``), so ``ai_evidence`` may be
  thinner than it was for a first-time submission with a photo.
* The read of the backlog uses the raw ``DATABASE_URL`` connection (read-only
  SELECT); the system identity has no SELECT policy on complaints, by design.
* Each row is independent: a provider failure is logged and skipped, never
  fatal.

Usage (from the repository root):

    # Show what would be analysed, without calling the provider or writing.
    python backend/backfill_ai_suggestions.py --dry-run

    # Actually analyse and store (one provider call per stale row).
    python backend/backfill_ai_suggestions.py

Requires AI_ENABLED=true and a configured provider key in backend/.env.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import ai, config, database  # noqa: E402

logger = logging.getLogger("campuslens.backfill_ai")

STALE_SQL = """
    SELECT id, description
      FROM public.complaints
     WHERE ai_summary IS NULL
       AND ai_category IS NULL
     ORDER BY created_at
"""


def _raw_connection():
    """Owner connection for the read-only backlog query only.

    The system identity deliberately has no SELECT policy on complaints, so
    the list of stale rows must come from the same DATABASE_URL every other
    operator script uses.
    """
    import psycopg

    settings = config.settings_from_env()
    return psycopg.connect(settings.database_url, connect_timeout=15), settings


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    conn, settings = _raw_connection()
    try:
        with conn:
            rows = conn.execute(STALE_SQL).fetchall()
    finally:
        conn.close()

    if not rows:
        print("Nothing to do: every complaint already has an ai_summary.")
        return 0

    if not (settings.ai_enabled and ai.is_configured()):
        print(
            "AI is disabled or unconfigured (AI_ENABLED / GEMINI_API_KEY). "
            "Cannot produce suggestions."
        )
        return 1

    print(f"{len(rows)} complaint(s) with no stored AI suggestion.")
    stored = failed = skipped = 0

    try:
        for row in rows:
            cid, description = str(row[0]), row[1]
            short = (description or "")[:48].replace("\n", " ")
            if dry_run:
                print(f"  [dry-run] {cid}  {short!r}")
                skipped += 1
                continue
            try:
                suggestion = ai.analyse(
                    description=description, image_bytes=None, image_mime=None
                )
            except ai.AnalysisUnavailable as exc:
                print(f"  [skipped] {cid}  provider unavailable ({exc.kind})")
                failed += 1
                continue
            except Exception as exc:  # never fatal for the batch
                print(f"  [skipped] {cid}  {type(exc).__name__}: {exc}")
                failed += 1
                continue

            # Exact production path: system identity + migration 014 function.
            with database.session(
                settings.database_url, database.Identity(cid, "system")
            ) as session:
                database.store_ai_suggestion(session, cid, suggestion)
            stored += 1
            print(f"  [stored]  {cid}  {short!r} -> {suggestion.get('ai_category')}")
    finally:
        # Close the shared pool explicitly; otherwise its background threads
        # trip a PythonFinalizationError on interpreter shutdown (exit code 1).
        database.close_pool()

    verb = "would store" if dry_run else "stored"
    print(f"\nDone: {verb} {stored}, skipped {failed}, dry-run {skipped}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
