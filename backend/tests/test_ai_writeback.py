"""Migration 014: the AI write-back must actually persist.

The admin card's "Full AI assessment" reads the ai_* columns straight from
the row. Before migration 014 the write-back UPDATE ran as the system
identity (sub = complaint id), matched no UPDATE policy on complaints, and
PostgreSQL silently updated zero rows - so every card showed "Not provided"
while the 201 body still carried the analysis. These tests pin the fix at
the source level: the function exists, is SECURITY DEFINER, is granted only
to the backend's roles, touches nothing but ai_* - and the router really
calls it instead of interpolating raw SQL.
"""
from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
MIGRATION = BACKEND / "migrations" / "014_ai_writeback.sql"
ROUTER = BACKEND / "app" / "routers" / "complaints.py"
DATABASE = BACKEND / "app" / "database.py"

AI_COLUMNS = (
    "ai_category", "ai_summary", "ai_evidence", "ai_uncertainty",
    "ai_urgency", "ai_impact", "ai_safety",
)


def test_migration_defines_both_functions_as_security_definer():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE OR REPLACE FUNCTION public.store_ai_suggestion" in sql
    assert "CREATE OR REPLACE FUNCTION public.record_job_failure" in sql
    # Two functions -> SECURITY DEFINER must appear at least twice.
    assert sql.count("SECURITY DEFINER") >= 2


def test_migration_grants_execute_only_to_backend_roles():
    sql = MIGRATION.read_text(encoding="utf-8")
    for fn in ("store_ai_suggestion", "record_job_failure"):
        assert f"REVOKE ALL ON FUNCTION public.{fn}" in sql  # from PUBLIC
        assert f"FROM anon" in sql or "FROM PUBLIC" in sql
        assert "TO authenticated" in sql
    # anon must never gain EXECUTE on the elevated functions.
    assert "TO anon" not in sql


def test_function_body_touches_exactly_the_ai_columns():
    """The elevated function must be unable to write scores or status."""
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    # Body of store_ai_suggestion only (between its AS $$ and closing $$).
    body = sql.split("as $$", 1)[1].split("$$", 1)[0]
    assert "update public.complaints" in body
    for column in AI_COLUMNS:
        assert column in body
    for forbidden in (
        "priority_score", "score_breakdown", "confirmed_urgency",
        "confirmed_impact", "confirmed_safety", "status", "student_id",
    ):
        assert forbidden not in body, f"function must not write {forbidden}"


def test_router_calls_the_function_instead_of_raw_update():
    """The interpolated `UPDATE ... SET {assignments}` statement is gone."""
    router = ROUTER.read_text(encoding="utf-8")
    assert "database.store_ai_suggestion" in router
    assert 'UPDATE public.complaints SET {assignments}' not in router

    database = DATABASE.read_text(encoding="utf-8")
    assert "SELECT public.store_ai_suggestion(" in database
    assert "SELECT public.record_job_failure(" in database
    assert "AI_SUGGESTION_COLUMNS" in database
