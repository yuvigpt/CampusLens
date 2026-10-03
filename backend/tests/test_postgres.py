"""
Offline tests for the PostgreSQL (DATABASE_URL) mode.

No test in this file opens a real PostgreSQL connection:

* ``config.database_url_from_env()`` / ``Settings`` are exercised with a
  patched environment only.
* ``database`` operations run against a fake pool/connection that records the
  SQL it receives, so SQL translation is asserted exactly (``?`` -> ``%s``,
  ``RETURNING id``, the PostgreSQL timestamp expression, LIMIT/OFFSET).
* Failure paths assert a clear RuntimeError that never contains the URL or
  its credentials, and that no half-built pool is left behind.

DATABASE_URL is removed from the environment wherever it could leak in, so
the suite never depends on (or reaches) a real server.
"""

from __future__ import annotations

import contextlib
import os
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import psycopg

from app import config, database

REPO_ROOT = Path(__file__).resolve().parents[2]

# Deliberately "secret" URL: any leak into a message or repr fails a test.
PG_URL = "postgresql://campus_admin:S3cr3t_Passw0rd@db.example.internal:5432/campuslens"


class _FakeCursor:
    """Just enough of a psycopg/sqlite cursor for database.py."""

    def __init__(self, rows=None, rowcount=-1):
        self._rows = list(rows or [])
        self.rowcount = rowcount

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows


def _complaint_row(complaint_id: int = 42) -> dict:
    """A row shaped like the real complaints table (all columns present)."""
    row = {column: None for column in database.COMPLAINT_COLUMNS}
    row.update(
        id=complaint_id,
        description="Lamp is broken",
        location="Library, floor 2",
        status=database.STATUS_REPORTED,
        created_at="2026-01-02 03:04:05",
    )
    return row


class _FakePGConnection:
    """Stands in for a psycopg pooled connection; records every statement."""

    def __init__(self, read_rows=None, update_rowcount=1):
        self.executed: list[tuple[str, object]] = []
        self.execute_kwargs: list[dict] = []
        self._read_rows = list(read_rows) if read_rows is not None else [_complaint_row()]
        self._update_rowcount = update_rowcount
        self.fail_with: Exception | None = None

    def execute(self, sql, params=None, **kwargs):
        if self.fail_with is not None:
            raise self.fail_with
        self.executed.append((sql, params))
        self.execute_kwargs.append(kwargs)
        if "RETURNING id" in sql:
            return _FakeCursor(rows=[{"id": 42}])
        if sql.lstrip().upper().startswith("SELECT 1"):
            return _FakeCursor()
        if sql.lstrip().upper().startswith("UPDATE"):
            return _FakeCursor(rowcount=self._update_rowcount)
        return _FakeCursor(rows=list(self._read_rows))


class _FakePool:
    """Context-manager pool exposing just enough of psycopg_pool's API."""

    def __init__(self, connection_obj=None, connection_error=None):
        self.conn = connection_obj or _FakePGConnection()
        self.connection_error = connection_error
        self.acquired = 0
        self.closed = False

    def connection(self):
        @contextlib.contextmanager
        def _acquire():
            self.acquired += 1
            if self.connection_error is not None:
                raise self.connection_error
            yield self.conn

        return _acquire()

    def close(self):
        self.closed = True


class DatabaseUrlFromEnvTest(unittest.TestCase):
    """DATABASE_URL loading: environment-only, blank-safe, never repr'd."""

    def tearDown(self):
        database.close_pool()

    def test_unset_yields_none(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("DATABASE_URL", None)
            self.assertIsNone(config.database_url_from_env())

    def test_blank_yields_none(self):
        for blank in ("", "   "):
            with mock.patch.dict(os.environ, {"DATABASE_URL": blank}):
                self.assertIsNone(config.database_url_from_env())

    def test_value_kept_verbatim(self):
        with mock.patch.dict(os.environ, {"DATABASE_URL": PG_URL}):
            self.assertEqual(config.database_url_from_env(), PG_URL)

    def test_legacy_postgres_scheme_normalized(self):
        legacy = "postgres://campus_admin:S3cr3t_Passw0rd@db.example.internal/campuslens"
        with mock.patch.dict(os.environ, {"DATABASE_URL": legacy}):
            self.assertEqual(config.database_url_from_env(), "postgresql://" + legacy[11:])

    def test_default_settings_reads_env(self):
        with mock.patch.dict(os.environ, {"DATABASE_URL": PG_URL}):
            self.assertEqual(config.default_settings().database_url, PG_URL)

    def test_settings_for_forces_sqlite_even_with_env_set(self):
        with mock.patch.dict(os.environ, {"DATABASE_URL": PG_URL}):
            settings = config.settings_for(
                db_path=REPO_ROOT / "backend" / "campuslens.db",
                upload_dir=REPO_ROOT / "backend" / "uploads",
            )
        self.assertIsNone(settings.database_url)

    def test_settings_for_allows_explicit_override(self):
        settings = config.settings_for(
            db_path=REPO_ROOT / "backend" / "campuslens.db",
            upload_dir=REPO_ROOT / "backend" / "uploads",
            database_url=PG_URL,
        )
        self.assertEqual(settings.database_url, PG_URL)

    def test_settings_repr_never_contains_url_or_password(self):
        settings = config.settings_for(
            db_path=REPO_ROOT / "backend" / "campuslens.db",
            upload_dir=REPO_ROOT / "backend" / "uploads",
            database_url=PG_URL,
        )
        text = repr(settings)
        self.assertNotIn(PG_URL, text)
        self.assertNotIn("S3cr3t_Passw0rd", text)
        self.assertNotIn("database_url", text)


class SqlTranslationTest(unittest.TestCase):
    """``?`` -> ``%s`` translation, timestamp expressions, DDL splitting."""

    def test_pg_execute_translates_placeholders(self):
        fake = _FakePGConnection()
        database._execute(fake, "SELECT * FROM t WHERE a = ? AND b = ?", (1, 2))
        sql, params = fake.executed[0]
        self.assertNotIn("?", sql)
        self.assertEqual(sql.count("%s"), 2)
        self.assertEqual(params, (1, 2))

    def test_sqlite_execute_runs_untouched(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        database._execute(conn, "CREATE TABLE t (a INTEGER)", ())
        database._execute(conn, "INSERT INTO t VALUES (?)", (7,))
        rows = database._execute(conn, "SELECT a FROM t WHERE a = ?", (7,)).fetchall()
        self.assertEqual([tuple(r) for r in rows], [(7,)])

    def test_pg_execute_disables_prepared_statements(self):
        """Parameterized PG execution must not use server-side prepared statements.

        Supabase's Transaction Pooler can move a session to a different
        PostgreSQL backend between transactions, which breaks the session-scoped
        ``_pg3_N`` prepared statements psycopg would otherwise create.
        """
        fake = _FakePGConnection()
        database._execute(fake, "SELECT * FROM t WHERE a = ?", (1,))
        self.assertEqual(fake.execute_kwargs[0].get("prepare"), False)

    def test_every_pg_query_path_disables_prepared_statements(self):
        """All four public PG operations funnel through _execute."""
        fake = _FakePGConnection()
        pool = _FakePool(connection_obj=fake)
        with mock.patch.object(database, "_ensure_pool", return_value=pool):
            database.create_complaint(
                description="Broken lamp", location="Library", database_url=PG_URL
            )
            database.get_complaint(42, database_url=PG_URL)
            database.list_complaints(database_url=PG_URL)
            database.update_complaint_status(42, "Resolved", database_url=PG_URL)
        self.assertEqual(len(fake.execute_kwargs), len(fake.executed))
        self.assertGreater(len(fake.execute_kwargs), 0)
        self.assertTrue(
            all(kwargs.get("prepare") is False for kwargs in fake.execute_kwargs)
        )

    def test_sqlite_path_never_sees_the_prepare_flag(self):
        """sqlite3.execute has no ``prepare`` parameter, so the flag stays PG-only."""
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        # Would raise TypeError if prepare= leaked into the SQLite branch.
        database._execute(conn, "SELECT ?", (5,))
        self.assertEqual(database._execute(conn, "SELECT ?", (5,)).fetchone()[0], 5)

    def test_timestamp_expressions(self):
        self.assertEqual(database._SQLITE_NOW, "datetime('now')")
        self.assertEqual(
            database._PG_NOW,
            "to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD HH24:MI:SS')",
        )
        self.assertNotIn("datetime(", database._PG_NOW)

    def test_split_ddl_on_real_schema(self):
        statements = database._split_ddl(
            database.PG_SCHEMA_PATH.read_text(encoding="utf-8")
        )
        self.assertGreaterEqual(len(statements), 4)
        self.assertTrue(statements[0].startswith("CREATE TABLE IF NOT EXISTS complaints"))
        self.assertEqual(sum("CREATE INDEX" in s for s in statements), 3)
        for statement in statements:
            self.assertNotIn("--", statement)


class PostgresSchemaParityTest(unittest.TestCase):
    """schema_postgres.sql mirrors schema.sql column-for-column."""

    _COLUMN_RE = re.compile(r"^\s*([a-z_]+)\s+(?:TEXT|INTEGER|REAL|DOUBLE PRECISION)\b")

    def _columns(self, path: Path) -> list[str]:
        columns = []
        for line in path.read_text(encoding="utf-8").splitlines():
            match = self._COLUMN_RE.match(line.split("--", 1)[0])
            if match:
                columns.append(match.group(1))
        return columns

    def test_columns_match_sqlite_in_order(self):
        self.assertEqual(
            self._columns(database.SCHEMA_PATH),
            self._columns(database.PG_SCHEMA_PATH),
        )

    def test_no_sqlite_only_constructs(self):
        pg_sql = database.PG_SCHEMA_PATH.read_text(encoding="utf-8")
        code_only = "\n".join(line.split("--", 1)[0] for line in pg_sql.splitlines())
        self.assertNotIn("AUTOINCREMENT", code_only)
        self.assertIsNone(re.search(r"\bdatetime\(", code_only))
        self.assertIsNone(re.search(r"\bREAL\b", code_only))
        self.assertIn("DOUBLE PRECISION", code_only)
        self.assertIn("GENERATED BY DEFAULT AS IDENTITY", code_only)

    def test_timestamps_are_text_with_exact_utc_format(self):
        pg_sql = database.PG_SCHEMA_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "DEFAULT (to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD HH24:MI:SS'))",
            pg_sql,
        )
        self.assertRegex(pg_sql, r"created_at\s+TEXT NOT NULL")
        self.assertRegex(pg_sql, r"updated_at\s+TEXT,")
        self.assertRegex(pg_sql, r"resolved_at\s+TEXT\b")

    def test_every_statement_is_idempotent(self):
        for statement in database._split_ddl(
            database.PG_SCHEMA_PATH.read_text(encoding="utf-8")
        ):
            self.assertTrue(
                statement.startswith("CREATE TABLE IF NOT EXISTS")
                or statement.startswith("CREATE INDEX IF NOT EXISTS"),
                statement,
            )


class PoolFailureTest(unittest.TestCase):
    """Connection/init failures raise sanitized errors - no silent SQLite."""

    def setUp(self):
        env_patcher = mock.patch.dict(os.environ)
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        os.environ.pop("DATABASE_URL", None)
        database.close_pool()
        self.addCleanup(database.close_pool)

    def _assert_sanitized(self, error: RuntimeError):
        message = str(error)
        self.assertIn("DATABASE_URL", message)
        self.assertIn("NOT fall back", message)
        self.assertNotIn(PG_URL, message)
        self.assertNotIn("S3cr3t_Passw0rd", message)
        self.assertNotIn("db.example.internal", message)
        self.assertNotIn("campus_admin", message)
        self.assertIsNone(error.__cause__)
        self.assertTrue(error.__suppress_context__)

    def test_pool_construction_failure_is_clear_and_sanitized(self):
        leaky = Exception(
            'connection to server at "db.example.internal" failed: '
            'FATAL: password authentication failed for user "campus_admin"'
        )
        with mock.patch.object(database, "ConnectionPool", side_effect=leaky):
            with self.assertRaises(RuntimeError) as ctx:
                database.init_db(database_url=PG_URL)
        self._assert_sanitized(ctx.exception)
        self.assertIsNone(database._pool)

    def test_reachability_failure_closes_pool_and_keeps_none(self):
        fake_pool = _FakePool(
            connection_error=psycopg.OperationalError(
                'could not connect to server: Connection refused\n'
                '\tIs the server running on host "db.example.internal"?'
            )
        )
        with mock.patch.object(database, "ConnectionPool", return_value=fake_pool):
            with self.assertRaises(RuntimeError) as ctx:
                database.init_db(database_url=PG_URL)
        self._assert_sanitized(ctx.exception)
        self.assertTrue(fake_pool.closed)      # no half-built pool is kept
        self.assertIsNone(database._pool)

    def test_query_failure_is_sanitized(self):
        fake_pool = _FakePool()
        fake_pool.conn.fail_with = psycopg.OperationalError(
            "server closed the connection unexpectedly"
        )
        with mock.patch.object(database, "_ensure_pool", return_value=fake_pool):
            with self.assertRaises(RuntimeError) as ctx:
                database.get_complaint(1, database_url=PG_URL)
        self._assert_sanitized(ctx.exception)

    def test_ddl_statement_failure_propagates_unswallowed(self):
        # A non-connection error must still abort startup (louder than silent).
        fake_pool = _FakePool()
        fake_pool.conn.fail_with = psycopg.Error('syntax error at or near "COLLUM"')
        with mock.patch.object(database, "_ensure_pool", return_value=fake_pool):
            with self.assertRaises(psycopg.Error):
                database.init_db(database_url=PG_URL)

    def test_close_pool_closes_and_clears_state(self):
        fake_pool = _FakePool()
        database._pool = fake_pool
        database._pool_url = PG_URL
        database.close_pool()
        self.assertTrue(fake_pool.closed)
        self.assertIsNone(database._pool)
        self.assertIsNone(database._pool_url)
        database.close_pool()                  # second call is a no-op


class PostgresOperationsTest(unittest.TestCase):
    """Real database functions against a fake pool: SQL is translated."""

    def setUp(self):
        database.close_pool()
        self.addCleanup(database.close_pool)
        self.conn = _FakePGConnection()
        self.pool = _FakePool(self.conn)
        patcher = mock.patch.object(database, "_ensure_pool", return_value=self.pool)
        self._ensure = patcher.start()
        self.addCleanup(patcher.stop)

    def _sql_for(self, needle: str) -> str:
        return next(sql for sql, _ in self.conn.executed if needle in sql)

    def test_create_uses_returning_and_pg_timestamp(self):
        created = database.create_complaint(
            description="Lamp is broken", location="Library, floor 2",
            database_url=PG_URL,
        )
        insert_sql = self._sql_for("INSERT INTO complaints")
        self.assertIn("RETURNING id", insert_sql)
        self.assertIn(database._PG_NOW, insert_sql)
        self.assertNotIn("datetime('now')", insert_sql)
        self.assertNotIn("?", insert_sql)
        self.assertIn("%s", insert_sql)
        self.assertEqual(created["id"], 42)
        self.assertEqual(self._ensure.call_args.args[0], PG_URL)

    def test_get_translates_select(self):
        complaint = database.get_complaint(7, database_url=PG_URL)
        select_sql = self._sql_for("WHERE id =")
        self.assertNotIn("?", select_sql)
        self.assertIn("%s", select_sql)
        self.assertEqual(complaint["id"], 42)

    def test_list_without_limit_uses_offset_only(self):
        rows = database.list_complaints(database_url=PG_URL, offset=5)
        list_sql = self._sql_for("ORDER BY")
        self.assertIn("OFFSET %s", list_sql)
        self.assertNotIn("LIMIT", list_sql)     # never the SQLite LIMIT -1 trick
        self.assertNotIn("-1", list_sql)
        self.assertEqual(len(rows), 1)

    def test_list_with_limit_uses_both_placeholders(self):
        database.list_complaints(database_url=PG_URL, limit=10, offset=2)
        list_sql = self._sql_for("ORDER BY")
        self.assertIn("LIMIT %s OFFSET %s", list_sql)
        self.assertNotIn("-1", list_sql)
        params = next(p for s, p in self.conn.executed if "ORDER BY" in s)
        self.assertEqual(params[-2:], [10, 2])

    def test_list_without_paging_has_no_limit_clause(self):
        database.list_complaints(database_url=PG_URL)
        list_sql = self._sql_for("ORDER BY")
        self.assertNotIn("LIMIT", list_sql)
        self.assertNotIn("OFFSET", list_sql)

    def test_update_uses_pg_timestamp_and_reads_back(self):
        updated = database.update_complaint_status(5, "Resolved", database_url=PG_URL)
        update_sql = next(
            sql for sql, _ in self.conn.executed
            if sql.lstrip().upper().startswith("UPDATE")
        )
        self.assertIn(database._PG_NOW, update_sql)
        self.assertNotIn("datetime('now')", update_sql)
        self.assertNotIn("?", update_sql)
        self.assertEqual(update_sql.count("%s"), 3)
        self.assertIsNotNone(updated)
        self.assertIsNotNone(self._sql_for("WHERE id ="))   # read-back went to PG too

    def test_sqlite_mode_never_touches_the_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "probe.db"
            database.init_db(db_path)
            database.create_complaint(description="x", location="y", db_path=db_path)
            rows = database.list_complaints(db_path=db_path)
        self.assertEqual(len(rows), 1)
        self._ensure.assert_not_called()
        self.assertEqual(self.pool.acquired, 0)


class InitPostgresTest(unittest.TestCase):
    """init_db(database_url=...) applies schema_postgres.sql; safe to re-run."""

    def setUp(self):
        database.close_pool()
        self.addCleanup(database.close_pool)
        self.conn = _FakePGConnection()
        self.pool = _FakePool(self.conn)
        patcher = mock.patch.object(database, "_ensure_pool", return_value=self.pool)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_applies_all_statements_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            returned = database.init_db(Path(tmp) / "unused.db", database_url=PG_URL)
            self.assertEqual(returned, Path(tmp) / "unused.db")
        expected = database._split_ddl(
            database.PG_SCHEMA_PATH.read_text(encoding="utf-8")
        )
        self.assertEqual([sql for sql, _ in self.conn.executed], expected)
        self.assertTrue(expected[0].startswith("CREATE TABLE IF NOT EXISTS complaints"))
        # Second start re-applies the same IF NOT EXISTS statements: no drops.
        database.init_db(database_url=PG_URL)
        self.assertEqual(
            [sql for sql, _ in self.conn.executed], expected + expected
        )

    def test_missing_schema_file_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                database, "PG_SCHEMA_PATH", Path(tmp) / "missing.sql"
            ):
                with self.assertRaises(FileNotFoundError):
                    database.init_db(database_url=PG_URL)


class WiringTest(unittest.TestCase):
    """Call sites forward settings.database_url end-to-end (source checks)."""

    def _read(self, relative: str) -> str:
        return (REPO_ROOT / relative).read_text(encoding="utf-8")

    def test_complaints_router_passes_database_url(self):
        source = self._read("backend/app/routers/complaints.py")
        self.assertGreaterEqual(source.count("database_url=settings.database_url"), 4)

    def test_analytics_router_passes_database_url(self):
        source = self._read("backend/app/routers/analytics.py")
        self.assertGreaterEqual(source.count("database_url=settings.database_url"), 1)

    def test_lifespan_initializes_pg_and_closes_pool(self):
        source = self._read("backend/app/main.py")
        self.assertIn("database_url=settings.database_url", source)
        self.assertIn("database.close_pool()", source)

    def test_api_tests_strip_database_url(self):
        self.assertIn('"DATABASE_URL"', self._read("backend/tests/test_api.py"))

    def test_requirements_pin_psycopg_and_pool(self):
        requirements = self._read("backend/requirements.txt")
        self.assertIn("psycopg[binary]==", requirements)
        self.assertIn("psycopg-pool==", requirements)


if __name__ == "__main__":
    unittest.main()