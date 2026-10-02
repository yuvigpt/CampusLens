"""
CampusLens - database layer test (Stage 1).

What this does
--------------
Runs a self-contained check of ``app/database.py``:
initialize -> insert a temporary complaint -> read it back -> update its status
-> verify the update, plus a few negative and SQL-injection sanity checks.

Isolation
---------
Everything runs against a TEMPORARY database file inside the system temp
folder, and that folder is deleted at the end. ``backend/campuslens.db`` is
never written to, and the script asserts that it was not created by the test.

All rows this script creates are marked with TEST_MARKER so any stray data is
obvious. It also proves the DB path is derived from the source file location
rather than the current working directory, so try running it from anywhere:

    cd C:\\
    C:\\Users\\yuvig\\Campuslens\\backend\\venv\\Scripts\\python.exe C:\\Users\\yuvig\\Campuslens\\backend\\test_database.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

# Allow "from app import database" no matter which folder this is run from.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import database as db  # noqa: E402

TEST_MARKER = "[TEMP TEST DATA - safe to delete]"

_results: list[tuple[str, bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    """Record and print one assertion."""
    ok = bool(condition)
    _results.append((label, ok, detail))
    line = f"  [{'PASS' if ok else 'FAIL'}] {label}"
    if detail and not ok:
        line += f"  -> {detail}"
    print(line)
    return ok


def raises_value_error(func, *args, **kwargs) -> bool:
    """True if calling func(*args, **kwargs) raises ValueError (our validation error)."""
    try:
        func(*args, **kwargs)
    except ValueError:
        return True
    except Exception as exc:                      # wrong error type is a failure
        print(f"       (unexpected {type(exc).__name__} instead of ValueError)")
        return False
    return False


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print("=== CampusLens - database test (Stage 1) ===")
    print(f"Production DB path     : {db.DB_PATH}")
    prod_existed_before = db.DB_PATH.exists()
    print(f"Production DB existed  : {prod_existed_before}")

    tmp_dir = Path(tempfile.mkdtemp(prefix="campuslens_test_"))
    test_db = tmp_dir / "temp_campuslens_test.db"
    print(f"TEMPORARY test DB      : {test_db}")
    print("NOTE: the real backend/campuslens.db is never touched by this test.")
    print()

    try:
        # ---------------------------------------------------------------- 1
        print("1. Initialize the temporary database")
        returned_path = db.init_db(db_path=test_db)
        check("init_db created the database file", test_db.is_file())
        check("init_db returned the temp path", Path(returned_path) == test_db)
        db.init_db(db_path=test_db)
        check("init_db is idempotent (safe to run twice)", True)

        # ---------------------------------------------------------------- 2
        print("\n2. Verify the complaints table schema")
        with db.connection(test_db) as conn:
            info = conn.execute("PRAGMA table_info(complaints)").fetchall()
            column_names = {row["name"] for row in info}
            table_names = {
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        missing = set(db.COMPLAINT_COLUMNS) - column_names
        check("all 17 expected columns exist", not missing, f"missing: {sorted(missing)}")
        check("no unexpected extra columns", not (column_names - set(db.COMPLAINT_COLUMNS)),
              f"extra: {sorted(column_names - set(db.COMPLAINT_COLUMNS))}")
        check("'complaints' table exists", "complaints" in table_names)

        # ---------------------------------------------------------------- 3
        print("\n3. Insert a TEMPORARY test complaint")
        breakdown = {"safety": 40, "impact": 15, "urgency": 25, "category": 7.5, "total": 87.5}
        created = db.create_complaint(
            description=f"{TEST_MARKER} Broken ceiling fan in Block C lab, sparks when switched on.",
            location="Block C - Computer Lab 2",
            image_path="uploads/temp_test_dummy.jpg",
            category="Electrical",
            issue_summary="Ceiling fan sparks when switched on.",
            safety_risk="High",
            functional_impact="Medium",
            urgency="High",
            evidence_from_image="Exposed wiring visible near the fan mount.",
            uncertainty_or_missing_information="Cannot tell whether the breaker is still live.",
            priority_score=87.5,
            score_breakdown=breakdown,
            db_path=test_db,
        )
        new_id = created.get("id")
        check("create_complaint returned a dict", isinstance(created, dict))
        check("new row has an integer id", isinstance(new_id, int) and not isinstance(new_id, bool),
              f"got {new_id!r}")
        check("status defaults to 'Reported'", created.get("status") == "Reported",
              f"got {created.get('status')!r}")
        check("created_at is populated", bool(created.get("created_at")))
        check("updated_at starts as None", created.get("updated_at") is None)
        check("resolved_at starts as None", created.get("resolved_at") is None)
        check("score_breakdown round-trips as a dict", created.get("score_breakdown") == breakdown,
              f"got {created.get('score_breakdown')!r}")
        check("test marker present in description", TEST_MARKER in (created.get("description") or ""))

        # ---------------------------------------------------------------- 4
        print("\n4. Read the complaint back by id")
        fetched = db.get_complaint(new_id, db_path=test_db)
        check("get_complaint found the row", fetched is not None)
        if fetched:
            for field in (
                "description", "location", "image_path", "category", "issue_summary",
                "safety_risk", "functional_impact", "urgency", "evidence_from_image",
                "uncertainty_or_missing_information", "priority_score",
            ):
                check(f"field '{field}' round-tripped", fetched.get(field) == created.get(field),
                      f"{fetched.get(field)!r} != {created.get(field)!r}")
        check("get_complaint on a missing id returns None",
              db.get_complaint(999_999, db_path=test_db) is None)

        # ---------------------------------------------------------------- 5
        print("\n5. List complaints (filters + sorting)")
        rows = db.list_complaints(db_path=test_db)
        check("list_complaints returns a list", isinstance(rows, list))
        check("list includes the new row", any(r["id"] == new_id for r in rows))
        check("filter status='Reported' includes it",
              any(r["id"] == new_id for r in db.list_complaints(status="Reported", db_path=test_db)))
        check("filter status='Resolved' excludes it",
              all(r["id"] != new_id for r in db.list_complaints(status="Resolved", db_path=test_db)))
        check("filter category='Electrical' includes it",
              any(r["id"] == new_id for r in db.list_complaints(category="Electrical", db_path=test_db)))
        check("sort='newest' runs",
              isinstance(db.list_complaints(sort="newest", db_path=test_db), list))
        check("limit works", len(db.list_complaints(limit=1, db_path=test_db)) <= 1)

        # ---------------------------------------------------------------- 6
        print("\n6. Update the status and verify the update")
        in_progress = db.update_complaint_status(new_id, "In Progress", db_path=test_db)
        check("update returned the row", in_progress is not None)
        check("status is now 'In Progress'", in_progress.get("status") == "In Progress",
              f"got {in_progress.get('status')!r}")
        check("updated_at was set", bool(in_progress.get("updated_at")))
        check("resolved_at still None while In Progress", in_progress.get("resolved_at") is None)

        resolved_row = db.update_complaint_status(new_id, "Resolved", db_path=test_db)
        check("status is now 'Resolved'", resolved_row.get("status") == "Resolved")
        check("resolved_at was set on resolve", bool(resolved_row.get("resolved_at")))

        reread = db.get_complaint(new_id, db_path=test_db)
        check("update persisted (verified by a fresh read)", reread.get("status") == "Resolved")

        reopened = db.update_complaint_status(new_id, "Reported", db_path=test_db)
        check("reopening clears resolved_at", reopened.get("resolved_at") is None)
        check("updating a missing id returns None",
              db.update_complaint_status(999_999, "Resolved", db_path=test_db) is None)

        # ---------------------------------------------------------------- 7
        print("\n7. Invalid input is rejected")
        check("empty description rejected",
              raises_value_error(db.create_complaint, description="   ", location="X", db_path=test_db))
        check("empty location rejected",
              raises_value_error(db.create_complaint, description="x", location="", db_path=test_db))
        check("invalid status rejected",
              raises_value_error(db.create_complaint, description="x", location="y",
                                 status="Bogus", db_path=test_db))
        check("invalid safety_risk rejected",
              raises_value_error(db.create_complaint, description="x", location="y",
                                 safety_risk="Extreme", db_path=test_db))
        check("malformed score_breakdown JSON rejected",
              raises_value_error(db.create_complaint, description="x", location="y",
                                 score_breakdown="{not json", db_path=test_db))
        check("invalid sort rejected (injection attempt as sort value)",
              raises_value_error(db.list_complaints, sort="; DROP TABLE complaints;--", db_path=test_db))
        check("invalid status on update rejected",
              raises_value_error(db.update_complaint_status, new_id, "Done", db_path=test_db))

        # ---------------------------------------------------------------- 8
        print("\n8. SQL parameterization sanity check")
        hostile = f"{TEST_MARKER} Robert'); DROP TABLE complaints;--"
        hostile_row = db.create_complaint(
            description=hostile, location=f"{TEST_MARKER} Injection Test", db_path=test_db
        )
        check("hostile text stored literally, not executed",
              hostile_row.get("description") == hostile, f"got {hostile_row.get('description')!r}")
        remaining = db.list_complaints(db_path=test_db)
        check("complaints table still intact (2 temp rows)", len(remaining) == 2,
              f"got {len(remaining)} rows")

        # ---------------------------------------------------------------- 9
        print("\n9. Confirm the production database was not touched")
        check("backend/campuslens.db unchanged by this test",
              db.DB_PATH.exists() == prod_existed_before,
              f"existed before={prod_existed_before}, after={db.DB_PATH.exists()}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print(f"\nCleaned up the temporary database folder: {tmp_dir}")

    passed = sum(1 for _, ok, _ in _results if ok)
    failed = len(_results) - passed
    print("=" * 64)
    print(f"RESULT: {passed} passed, {failed} failed, {len(_results)} total")
    if failed:
        print("Failures:")
        for label, ok, detail in _results:
            if not ok:
                print(f"  - {label}" + (f"  ({detail})" if detail else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())