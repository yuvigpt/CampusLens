"""
CampusLens - database layer (SQLite by default, PostgreSQL when configured).

Backends
--------
* **SQLite (default)** - the standard-library ``sqlite3`` module and the file
  ``backend/campuslens.db``. This is what local development and the entire
  test suite use; nothing about it changes when PostgreSQL support is unused.
* **PostgreSQL (deployment)** - selected by passing a non-blank keyword-only
  ``database_url`` (normally ``DATABASE_URL`` from the environment) to the
  functions below. It uses psycopg 3 plus a small psycopg-pool pool. If the
  URL is set but the server cannot be reached, startup/operation fails with a
  sanitized error - there is never a silent fallback to SQLite, and the URL or
  its credentials never appear in any message.

Design notes
------------
* The SQLite database file lives at ``backend/campuslens.db``. That path is
  derived from THIS file's location, never from the terminal's current
  working directory, so the app behaves the same no matter where it is
  launched from.
* Every query is parameterized (``?`` placeholders in the SQL text; they are
  translated to ``%s`` immediately before PostgreSQL execution). No SQL string
  formatting, so user text can never be interpreted as SQL.
* SQLite: a fresh connection is opened per operation and always closed again.
  SQLite allows only one writer at a time, so short-lived connections avoid
  "database is locked" during a demo. PostgreSQL: connections come from a
  small thread-safe pool built on first use and closed by the app lifespan.
* Timestamps are UTC text in exactly ``YYYY-MM-DD HH:MM:SS`` on both backends
  (the PostgreSQL columns are TEXT so API output stays byte-identical).
* Each public function takes optional keyword-only ``db_path`` and
  ``database_url``. Production code passes the values from settings; tests
  pass a temporary ``db_path`` and no URL so they never touch real data or a
  real server.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional, Union

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# ---------------------------------------------------------------------------
# Paths (derived from this file, NOT the current working directory)
# ---------------------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parent          # .../backend/app
BACKEND_DIR = APP_DIR.parent                       # .../backend
SCHEMA_PATH = APP_DIR / "schema.sql"
PG_SCHEMA_PATH = APP_DIR / "schema_postgres.sql"   # applied when a URL is set
DB_PATH = BACKEND_DIR / "campuslens.db"            # .../backend/campuslens.db

# ---------------------------------------------------------------------------
# PostgreSQL dialect fragments (fixed strings - the only SQL ever interpolated)
# ---------------------------------------------------------------------------
# Same output as SQLite's datetime('now'): UTC, no timezone suffix, second
# resolution, format YYYY-MM-DD HH:MM:SS. PostgreSQL columns are TEXT so the
# API and the frontend see byte-identical values on both backends.
_PG_NOW = "to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD HH24:MI:SS')"
_SQLITE_NOW = "datetime('now')"

# Pool kept deliberately small: one backend process must not eat the
# database's whole connection budget.
POOL_MIN_SIZE = 1
POOL_MAX_SIZE = 4

# ---------------------------------------------------------------------------
# Domain constants - single source of truth shared with the API and frontend
# ---------------------------------------------------------------------------
STATUS_REPORTED = "Reported"
STATUS_IN_PROGRESS = "In Progress"
STATUS_RESOLVED = "Resolved"

ALLOWED_STATUSES: tuple[str, ...] = (STATUS_REPORTED, STATUS_IN_PROGRESS, STATUS_RESOLVED)
ALLOWED_LEVELS: tuple[str, ...] = ("Low", "Medium", "High")

# Columns of the complaints table, in schema order. Used to build SELECT lists
# and to validate column names, which keeps identifiers out of f-strings.
COMPLAINT_COLUMNS: tuple[str, ...] = (
    "id",
    "description",
    "location",
    "image_path",
    "category",
    "issue_summary",
    "safety_risk",
    "functional_impact",
    "urgency",
    "evidence_from_image",
    "uncertainty_or_missing_information",
    "priority_score",
    "score_breakdown",
    "status",
    "created_at",
    "updated_at",
    "resolved_at",
)

_SELECT_COLUMNS = ", ".join(COMPLAINT_COLUMNS)

# ORDER BY fragments. Keys are looked up in this dict, so the caller's `sort`
# value can never be injected into the SQL text.
_ALLOWED_SORTS: dict[str, str] = {
    "priority": "priority_score IS NULL, priority_score DESC, created_at DESC",
    "newest": "created_at DESC, id DESC",
    "oldest": "created_at ASC, id ASC",
}

# The single PostgreSQL pool for this process: created on first use by
# _ensure_pool(), closed by close_pool() (the app lifespan calls it on
# shutdown). None means "SQLite mode" or "pool not built yet".
_pool: Optional[ConnectionPool] = None
_pool_url: Optional[str] = None


def _pg_error(exc: BaseException, phase: str) -> RuntimeError:
    """Build a clear PostgreSQL error that can never leak the URL.

    Only the exception class name is reported: psycopg/libpq messages may
    contain connection-string details (host, port, user, ...) and the URL
    itself embeds credentials - none of which may ever be exposed.
    """
    return RuntimeError(
        f"PostgreSQL {phase} failed (error type: {type(exc).__name__}). "
        "DATABASE_URL is configured, so the application will NOT fall back "
        "to SQLite; fix DATABASE_URL or the network and restart. "
        "Connection details are omitted from this message on purpose."
    )


def _ensure_pool(database_url: str) -> ConnectionPool:
    """Return the process-wide PostgreSQL pool, creating (and testing) it once.

    Any failure to open the pool or reach the server raises a sanitized
    RuntimeError: no half-built pool is kept and there is no SQLite fallback.
    """
    global _pool, _pool_url
    if _pool is not None:
        if _pool_url == database_url:
            return _pool
        close_pool()                      # URL changed (e.g. between tests)

    try:
        pool = ConnectionPool(
            conninfo=database_url,
            min_size=POOL_MIN_SIZE,
            max_size=POOL_MAX_SIZE,
            # row_factory -> rows behave like dicts, matching sqlite3.Row.
            kwargs={"row_factory": dict_row},
        )
    except Exception as exc:              # malformed URL, bad setup, etc.
        raise _pg_error(exc, "connection") from None

    try:
        with pool.connection() as conn:
            conn.execute("SELECT 1")      # proves the server is reachable
    except Exception as exc:
        try:
            pool.close()                  # never leave a half-built pool behind
        except Exception:
            pass
        raise _pg_error(exc, "connection") from None

    _pool = pool
    _pool_url = database_url
    return pool


def close_pool() -> None:
    """Close the PostgreSQL pool if one is open. No-op in SQLite mode."""
    global _pool, _pool_url
    if _pool is not None:
        try:
            _pool.close()
        finally:
            _pool = None
            _pool_url = None


# ---------------------------------------------------------------------------
# Connection handling
# ---------------------------------------------------------------------------
def get_connection(db_path: Optional[Union[str, Path]] = None) -> sqlite3.Connection:
    """Open a SQLite connection with sane defaults.

    * ``row_factory = sqlite3.Row`` -> rows behave like dictionaries.
    * WAL journal mode -> readers are not blocked by the single writer.
    * ``busy_timeout`` -> wait (rather than fail) if the file is briefly locked.
    """
    path = Path(db_path) if db_path is not None else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def connection(
    db_path: Optional[Union[str, Path]] = None,
    *,
    database_url: Optional[str] = None,
) -> Iterator[Any]:
    """Context manager: yields a connection, commits on success, always closes.

    SQLite (the default): opens a fresh connection, commits on a clean exit,
    rolls back if an exception escapes, and closes in all cases - unchanged.

    PostgreSQL (``database_url`` set): lends a pooled connection; psycopg-pool
    commits on success, rolls back on error and returns it to the pool.
    Connection-level failures are re-raised as sanitized errors (the URL and
    its credentials are never exposed).
    """
    if database_url:
        pool = _ensure_pool(database_url)
        try:
            with pool.connection() as conn:
                yield conn
        except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
            raise _pg_error(exc, "operation") from None
        return

    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _execute(conn: Any, sql: str, params: Any) -> Any:
    """Run ``sql`` with ``params`` on either backend.

    SQL text in this module always uses ``?`` placeholders (never present in
    the validated fragments it is built from), so PostgreSQL execution simply
    swaps them for its own ``%s`` marker; SQLite executes the text verbatim.
    """
    if isinstance(conn, sqlite3.Connection):
        return conn.execute(sql, params)
    return conn.execute(sql.replace("?", "%s"), params)


def init_db(
    db_path: Optional[Union[str, Path]] = None,
    *,
    database_url: Optional[str] = None,
) -> Path:
    """Create the database file/tables if they do not exist yet.

    Idempotent - safe to call on every application start.

    * No ``database_url``: applies ``schema.sql`` to SQLite, exactly as before.
    * ``database_url`` set: applies ``schema_postgres.sql`` to PostgreSQL.
      Connection or statement failures propagate - startup fails loudly and
      never falls back to SQLite.

    Returns the path of the SQLite database that was initialized; in
    PostgreSQL mode there is no file, so the (unused) local default path is
    returned to keep the signature stable.
    """
    if database_url:
        _init_postgres(database_url)
        return Path(db_path) if db_path is not None else DB_PATH

    if not SCHEMA_PATH.is_file():
        raise FileNotFoundError(f"schema.sql not found at {SCHEMA_PATH}")

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with connection(db_path) as conn:
        conn.executescript(schema_sql)

    return Path(db_path) if db_path is not None else DB_PATH


def _init_postgres(database_url: str) -> None:
    """Apply schema_postgres.sql to PostgreSQL. Idempotent, fails loudly."""
    if not PG_SCHEMA_PATH.is_file():
        raise FileNotFoundError(f"schema_postgres.sql not found at {PG_SCHEMA_PATH}")
    statements = _split_ddl(PG_SCHEMA_PATH.read_text(encoding="utf-8"))
    pool = _ensure_pool(database_url)      # validates reachability first
    try:
        with pool.connection() as conn:
            for statement in statements:
                conn.execute(statement)
    except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
        raise _pg_error(exc, "initialization") from None


def _split_ddl(sql_text: str) -> list[str]:
    """Split a simple DDL script into individual statements.

    Used only for schema_postgres.sql, which contains no functions, dollar
    quoting, or semicolons inside string literals - so stripping ``--``
    comments and splitting on ``;`` is exact.
    """
    without_comments = "\n".join(
        line.split("--", 1)[0] for line in sql_text.splitlines()
    )
    return [stmt.strip() for stmt in without_comments.split(";") if stmt.strip()]


# ---------------------------------------------------------------------------
# Small validation / conversion helpers
# ---------------------------------------------------------------------------
def _require_text(value: Any, field: str, max_length: int = 2000) -> str:
    """Ensure a required text field is a non-empty string, and trim it."""
    if value is None or not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{field}' is required and must be a non-empty string")
    cleaned = value.strip()
    if len(cleaned) > max_length:
        raise ValueError(f"'{field}' is too long ({len(cleaned)} chars, max {max_length})")
    return cleaned


def _optional_text(value: Any, field: str, max_length: int = 4000) -> Optional[str]:
    """Normalize an optional text field. Empty string / None both become None."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"'{field}' must be a string when provided")
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        raise ValueError(f"'{field}' is too long ({len(cleaned)} chars, max {max_length})")
    return cleaned


def _validate_level(value: Any, field: str) -> Optional[str]:
    """Allow None or exactly one of Low/Medium/High (case-insensitive in, canonical out)."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    cleaned = value.strip().title()          # 'high' / 'HIGH' -> 'High'
    if cleaned not in ALLOWED_LEVELS:
        raise ValueError(f"'{field}' must be one of {list(ALLOWED_LEVELS)}, got {value!r}")
    return cleaned


def _validate_status(value: Any, field: str = "status") -> str:
    """Ensure a status is one of the three allowed values (exact match)."""
    if not isinstance(value, str) or value not in ALLOWED_STATUSES:
        raise ValueError(f"'{field}' must be one of {list(ALLOWED_STATUSES)}, got {value!r}")
    return value


def _validate_priority_score(value: Any) -> Optional[float]:
    """Allow None or a number, clamped to 0-100."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("'priority_score' must be a number when provided")
    return max(0.0, min(100.0, float(value)))


def _serialize_breakdown(value: Any) -> Optional[str]:
    """Accept a dict or a JSON string; always store a JSON string (or None)."""
    if value is None:
        return None
    if isinstance(value, str):
        try:                                  # must already be valid JSON
            json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"'score_breakdown' string is not valid JSON: {exc}") from exc
        return value
    if isinstance(value, dict):
        return json.dumps(value, separators=(",", ":"))
    raise ValueError("'score_breakdown' must be a dict, a JSON string, or None")


def _row_to_complaint(row: Optional[Any]) -> Optional[dict[str, Any]]:
    """Convert a database row (sqlite3.Row or psycopg dict row) into a plain dict.

    score_breakdown is stored as TEXT but returned as a dict (when it parses),
    because that is what the API and the dashboard want to render.
    """
    if row is None:
        return None

    complaint = dict(row)
    raw = complaint.get("score_breakdown")
    if raw is None:
        complaint["score_breakdown"] = None
    else:
        try:
            complaint["score_breakdown"] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            complaint["score_breakdown"] = raw      # hand back whatever is stored
    return complaint


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
def create_complaint(
    *,
    description: str,
    location: str,
    image_path: Optional[str] = None,
    category: Optional[str] = None,
    issue_summary: Optional[str] = None,
    safety_risk: Optional[str] = None,
    functional_impact: Optional[str] = None,
    urgency: Optional[str] = None,
    evidence_from_image: Optional[str] = None,
    uncertainty_or_missing_information: Optional[str] = None,
    priority_score: Optional[float] = None,
    score_breakdown: Optional[Union[dict[str, Any], str]] = None,
    status: str = STATUS_REPORTED,
    db_path: Optional[Union[str, Path]] = None,
    database_url: Optional[str] = None,
) -> dict[str, Any]:
    """Insert one complaint and return it as a dict (including its new id).

    Only ``description`` and ``location`` are mandatory. The AI-derived fields
    are optional so a complaint can still be recorded when analysis fails.
    """
    description = _require_text(description, "description")
    location = _require_text(location, "location", max_length=300)
    image_path = _optional_text(image_path, "image_path", max_length=500)
    category = _optional_text(category, "category", max_length=100)
    issue_summary = _optional_text(issue_summary, "issue_summary")
    safety_risk = _validate_level(safety_risk, "safety_risk")
    functional_impact = _validate_level(functional_impact, "functional_impact")
    urgency = _validate_level(urgency, "urgency")
    evidence_from_image = _optional_text(evidence_from_image, "evidence_from_image")
    uncertainty_or_missing_information = _optional_text(
        uncertainty_or_missing_information, "uncertainty_or_missing_information"
    )
    priority_score = _validate_priority_score(priority_score)
    score_breakdown_json = _serialize_breakdown(score_breakdown)
    status = _validate_status(status)

    now_expr = _PG_NOW if database_url else _SQLITE_NOW
    sql = f"""
        INSERT INTO complaints (
            description, location, image_path, category, issue_summary,
            safety_risk, functional_impact, urgency, evidence_from_image,
            uncertainty_or_missing_information, priority_score, score_breakdown,
            status, resolved_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            CASE WHEN ? = 'Resolved' THEN {now_expr} ELSE NULL END
        )
    """
    params = (
        description, location, image_path, category, issue_summary,
        safety_risk, functional_impact, urgency, evidence_from_image,
        uncertainty_or_missing_information, priority_score, score_breakdown_json,
        status, status,                      # 2nd 'status' feeds the resolved_at CASE
    )

    with connection(db_path, database_url=database_url) as conn:
        if database_url:
            # PostgreSQL has no lastrowid; RETURNING gives the new id back.
            cursor = _execute(conn, sql + " RETURNING id", params)
            new_id = cursor.fetchone()["id"]
        else:
            cursor = conn.execute(sql, params)
            new_id = cursor.lastrowid

    created = get_complaint(new_id, db_path=db_path, database_url=database_url)
    if created is None:                      # pragma: no cover - should never happen
        raise RuntimeError(f"Complaint {new_id} was inserted but could not be read back")
    return created


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------
def _validate_int(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"'{field}' must be an integer")
    if value < minimum:
        raise ValueError(f"'{field}' must be >= {minimum}, got {value}")
    return value


def get_complaint(
    complaint_id: int,
    *,
    db_path: Optional[Union[str, Path]] = None,
    database_url: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Fetch a single complaint by id. Returns None if it does not exist."""
    complaint_id = _validate_int(complaint_id, "complaint_id", minimum=1)

    sql = f"SELECT {_SELECT_COLUMNS} FROM complaints WHERE id = ?"
    with connection(db_path, database_url=database_url) as conn:
        row = _execute(conn, sql, (complaint_id,)).fetchone()
    return _row_to_complaint(row)


def list_complaints(
    *,
    status: Optional[str] = None,
    category: Optional[str] = None,
    sort: str = "priority",
    limit: Optional[int] = None,
    offset: Optional[int] = 0,
    db_path: Optional[Union[str, Path]] = None,
    database_url: Optional[str] = None,
) -> list[dict[str, Any]]:
    """List complaints, by default highest priority first.

    Filters
        status   : one of Reported / In Progress / Resolved (omit for all)
        category : exact category match (omit for all)
    Ordering
        sort     : 'priority' (default), 'newest', or 'oldest'. Complaints with
                   a NULL priority_score always sort last under 'priority',
                   so un-analysed complaints never jump the queue.
    Paging
        limit / offset : omit `limit` to fetch everything.
    """
    clauses: list[str] = []
    params: list[Any] = []

    if status is not None:
        clauses.append("status = ?")
        params.append(_validate_status(status))

    if category is not None:
        cleaned = _optional_text(category, "category", max_length=100)
        if cleaned:
            clauses.append("category = ?")
            params.append(cleaned)

    # `sort` is a dict lookup, never string-formatted into the SQL itself.
    if sort not in _ALLOWED_SORTS:
        raise ValueError(f"'sort' must be one of {sorted(_ALLOWED_SORTS)}, got {sort!r}")
    order_by = _ALLOWED_SORTS[sort]

    sql = f"SELECT {_SELECT_COLUMNS} FROM complaints"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += f" ORDER BY {order_by}"

    if limit is not None or (offset or 0) > 0:
        clean_limit = None if limit is None else _validate_int(limit, "limit")
        clean_offset = _validate_int(offset or 0, "offset")
        if database_url:
            # PostgreSQL rejects LIMIT -1; OFFSET alone means "no limit".
            if clean_limit is not None:
                sql += " LIMIT ? OFFSET ?"
                params.extend([clean_limit, clean_offset])
            else:
                sql += " OFFSET ?"
                params.append(clean_offset)
        else:
            # SQLite needs a LIMIT before it will accept an OFFSET; -1 means "no limit".
            sql += " LIMIT ? OFFSET ?"
            params.extend([-1 if clean_limit is None else clean_limit, clean_offset])

    with connection(db_path, database_url=database_url) as conn:
        rows = _execute(conn, sql, params).fetchall()
    return [_row_to_complaint(row) for row in rows]


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------
def update_complaint_status(
    complaint_id: int,
    status: str,
    *,
    db_path: Optional[Union[str, Path]] = None,
    database_url: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Change a complaint's status. Returns the updated complaint, or None if unknown.

    Side effects:
        updated_at  -> always set to the current UTC time
        resolved_at -> set when moving INTO 'Resolved', cleared when moving out
    """
    complaint_id = _validate_int(complaint_id, "complaint_id", minimum=1)
    status = _validate_status(status)

    now_expr = _PG_NOW if database_url else _SQLITE_NOW
    sql = f"""
        UPDATE complaints
           SET status      = ?,
               updated_at  = {now_expr},
               resolved_at = CASE WHEN ? = 'Resolved' THEN {now_expr} ELSE NULL END
         WHERE id = ?
    """
    with connection(db_path, database_url=database_url) as conn:
        cursor = _execute(conn, sql, (status, status, complaint_id))
        if cursor.rowcount == 0:
            return None                      # no such complaint

    return get_complaint(complaint_id, db_path=db_path, database_url=database_url)


# ---------------------------------------------------------------------------
# Manual use:  backend\venv\Scripts\python.exe backend\app\database.py
# Creates the database file and tables, then prints where they live.
# ---------------------------------------------------------------------------
def _main() -> int:
    path = init_db()
    print("CampusLens database ready")
    print(f"  file  : {path}")
    print(f"  schema: {SCHEMA_PATH}")
    if (os.environ.get("DATABASE_URL") or "").strip():
        print("  note  : DATABASE_URL is set - PostgreSQL is initialized when")
        print("          the app starts, not by this SQLite-only CLI.")
    with connection() as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall()
        names = [r["name"] for r in rows if not r["name"].startswith("sqlite_")]
        count = conn.execute("SELECT COUNT(*) AS n FROM complaints").fetchone()["n"]
    print(f"  tables: {', '.join(names)}")
    print(f"  rows  : {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())