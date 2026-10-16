"""
Shared test fixtures.

Nothing here touches a real database, Supabase project or AI provider:

* the JWT is verified against a locally generated RSA key and a stubbed JWKS
  endpoint, so no network call is made;
* `database.session` is replaced by an in-memory fake that mimics PostgreSQL
  RLS, so authorisation is exercised without a live server;
* storage and the AI provider are stubbed at the HTTP boundary.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import ai, auth, config, database, storage
from app.main import create_app

STUDENT_A = "11111111-1111-4111-8111-111111111111"
STUDENT_B = "22222222-2222-4222-8222-222222222222"
ADMIN = "33333333-3333-4333-8333-333333333333"


# ---------------------------------------------------------------------------
# RSA keypair + tokens
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def jwks(rsa_key):
    """Public JWK for the local key, as Supabase's JWKS endpoint returns."""
    from jwt.algorithms import RSAAlgorithm

    pub = RSAAlgorithm.to_jwk(rsa_key.public_key())
    import json as _json

    data = _json.loads(pub)
    return {"keys": [{"kid": "test-key", "alg": "RS256", "use": "sig", **data}]}


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch):
    """Never read a developer's real .env during tests."""
    monkeypatch.setattr(config, "_load_dotenv", lambda: None)
    for name in ("GEMINI_API_KEY",):
        monkeypatch.delenv(name, raising=False)


def make_token(key, sub, *, role="authenticated", exp_minutes=60, **claims):
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "aud": "authenticated",
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=exp_minutes)).timestamp()),
        **claims,
    }
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": "test-key"})


@pytest.fixture
def tokens(rsa_key, jwks):
    return {
        "student_a": make_token(rsa_key, STUDENT_A),
        "student_b": make_token(rsa_key, STUDENT_B),
        "admin": make_token(rsa_key, ADMIN),
        # A forged token that CLAIMS admin. The role must be ignored.
        "forged_admin": make_token(rsa_key, STUDENT_A, role="service_role"),
    }


# ---------------------------------------------------------------------------
# Fake database that mimics RLS
# ---------------------------------------------------------------------------
class FakeConn:
    """Mimics the subset of psycopg used by app.database.

    Crucially it applies the same authorisation rule as the real policies:
    a non-admin may only read or write rows whose student_id matches.
    """

    def __init__(self, store: "FakeStore"):
        self.store = store
        self.identity: Optional[database.Identity] = None

    # -- helpers ----------------------------------------------------------
    def _visible(self, row):
        # "admin" mirrors the admin policy; "system" mirrors the service-role
        # connection the background worker uses for ai_* bookkeeping.
        if self.identity.role in {"admin", "system"}:
            return True
        return str(row.get("student_id")) == self.identity.user_id

    def execute(self, sql, params=None):
        s = sql.strip().lower()
        if s.startswith("set local"):
            return None
        if "from public.profiles" in s:
            role = self.store.roles.get(params[0])
            if role is None:
                return _Result([])
            if "full_name" in s:            # load_profile selects more columns
                return _Result([{
                    "id": params[0],
                    "email": f"{params[0][:8]}@example.test",
                    "full_name": "Test User",
                    "role": role,
                    "created_at": None,
                }])
            return _Result([{"role": role}])
        if "insert into public.complaints" in s:
            row = self.store.create(self.identity.user_id, params)
            return _Result([row])
        if "select count(*)" in s:
            code = params[0]
            exclude = params[2]
            # Mirrors the real query: same location, inside the 90-day window,
            # excluding the complaint being scored.
            n = len([
                c for c in self.store.complaints.values()
                if c["location_code"] == code and str(c["id"]) != str(exclude)
            ])
            return _Result([{"n": n}])
        # Public feed: reads public_complaints only, which RLS exposes to anon.
        if "from public.public_complaints" in s:
            # public_read_approved: approved_at IS NOT NULL is the gate.
            rows = [r for r in self.store.public if r.get("approved_at") is not None]
            if "where source_complaint_id = %s" in s:
                rows = [r for r in rows if str(r["source_complaint_id"]) == str(params[0])]
            if "where public_category = %s" in s:
                rows = [r for r in rows if r["public_category"] == params[0]]
            return _Result(rows)
        # Audit trail + investigation notes (migration 006). The API only
        # exposes them to admins; students read events of their own complaint
        # only, mirroring events_own_read.
        if s.startswith("select") and "from public.complaint_events" in s:
            if self.identity.role != "admin":
                own = {
                    str(c["id"])
                    for c in self.store.complaints.values()
                    if self._visible(c)
                }
                rows = [e for e in self.store.events if str(e["complaint_id"]) in own]
            else:
                rows = list(self.store.events)
            return _Result([e for e in rows if str(e["complaint_id"]) == str(params[0])])
        if s.startswith("select") and "from public.investigation_notes" in s:
            if self.identity.role != "admin":
                return _Result([])
            return _Result(
                [n for n in self.store.notes if str(n["complaint_id"]) == str(params[0])]
            )
        if s.startswith("insert into public.investigation_notes"):
            if self.identity.role != "admin":
                # notes_admin_all: a non-admin insert matches no rows.
                return _Result([])
            complaint_id, author_id, body = params
            note = {
                "id": f"note-{len(self.store.notes) + 1}",
                "complaint_id": complaint_id,
                "author_id": author_id,
                "author_kind": "admin",
                "body": body,
                "created_at": "2026-01-01T00:00:00Z",
            }
            self.store.notes.append(note)
            return _Result(
                [{"id": note["id"], "body": body,
                  "author_kind": "admin", "created_at": note["created_at"]}]
            )
        # Every event INSERT the app writes (created, status_changed,
        # analysis_confirmed, note_added, public_approved/revoked) lands in the
        # fake audit trail so the timeline endpoint shows real history.
        if s.startswith("insert into public.complaint_events"):
            event_type = "created"
            for candidate in (
                "status_changed", "analysis_confirmed", "note_added",
                "public_approved", "public_revoked", "scored", "ai_retried",
                "created",
            ):
                if f"'{candidate}'" in s:
                    event_type = candidate
                    break
            if event_type == "status_changed":
                actor_role = params[2]
                from_value, to_value = params[3], params[4]
            elif event_type == "analysis_confirmed":
                actor_role = "admin"
                from_value, to_value = None, params[2]
            elif event_type == "created":
                actor_role = params[2]
                from_value, to_value = None, "Reported"
            else:
                actor_role = "admin"
                from_value, to_value = None, None
            event = {
                "id": len(self.store.events) + 1,
                "complaint_id": params[0],
                "actor_id": params[1],
                "actor_role": actor_role,
                "event_type": event_type,
                "from_value": from_value,
                "to_value": to_value,
                "created_at": "2026-01-01T00:00:00Z",
            }
            self.store.events.append(event)
            return _Result([])
        # Approve / revoke are admin-only writes.
        if "insert into public.public_complaints" in s:
            if not (self.identity.role in {"admin", "system"}):
                # Mirrors the real RLS: only admins may write this table.
                return _Result([])
            return _ApprovalResult(self.store, params)
        if s.startswith("update public.public_complaints"):
            return _RevokeResult(self.store, params[0])
        # Migration 016: sanitized campus feed via SECURITY DEFINER function.
        # Returns every complaint with ONLY small info, regardless of RLS
        # visibility - the function's column list is the privacy boundary.
        if "from public.community_overview" in s:
            rows = [
                {
                    "id": c["id"],
                    "location": c["location_raw"],
                    "status": c["status"],
                    "band": c.get("band"),
                    "ai_category": c.get("ai_category"),
                    "created_at": c.get("created_at"),
                }
                for c in self.store.complaints.values()
            ]
            return _Result(rows)
        # Migration 016: DELETE ... RETURNING image_path. The visibility rule
        # mirrors complaints_own_delete / complaints_admin_all.
        if s.startswith("delete from public.complaints"):
            row = self.store.complaints.get(str(params[0]))
            if row is None or not self._visible(row):
                return _Result([])
            del self.store.complaints[str(params[0])]
            # CASCADE: events, notes, scores, jobs and public copies follow.
            self.store.events = [
                e for e in self.store.events if str(e["complaint_id"]) != str(params[0])
            ]
            self.store.notes = [
                n for n in self.store.notes if str(n["complaint_id"]) != str(params[0])
            ]
            self.store.public = [
                p for p in self.store.public
                if str(p.get("source_complaint_id")) != str(params[0])
            ]
            return _Result([{"image_path": row.get("image_path")}])
        if s.startswith("select") and "from public.complaints" in s:
            rows = [c for c in self.store.complaints.values() if self._visible(c)]
            if "where id = %s" in s:
                return _Result([c for c in rows if str(c["id"]) == str(params[0])])
            # List query: emulate the triage filters positionally, in the same
            # order database.list_complaints appends its clauses
            # (student_id, status, band, category, q, open) so a test can assert
            # what a filter actually narrows - not merely that it 200s.
            where = ""
            if "where " in s:
                where = s.split("where ", 1)[1]
                for stop in ("order by", " limit "):
                    if stop in where:
                        where = where.split(stop, 1)[0]
            pos = 0
            if "student_id = %s" in where:
                sid = params[pos]
                pos += 1
                rows = [c for c in rows if str(c.get("student_id")) == str(sid)]
            if "status = %s" in where:
                st = params[pos]
                pos += 1
                rows = [c for c in rows if c.get("status") == st]
            if "priority_score is null" in where:  # the band CASE expression
                want = params[pos]
                pos += 1
                rows = [c for c in rows if _band_of(c) == want]
            if "ai_category = %s" in where:
                cat = params[pos]
                pos += 1
                rows = [
                    c for c in rows if str(c.get("ai_category")) == str(cat)
                ]
            if "ilike %s" in where:
                like = str(params[pos]).lstrip("%").rstrip("%").lower()
                pos += 3  # description, location_raw, id::text
                rows = [
                    c for c in rows
                    if like in str(c.get("description") or "").lower()
                    or like in str(c.get("location_raw") or "").lower()
                    or like in str(c.get("id") or "").lower()
                ]
            if "status <> 'resolved'" in where:
                rows = [c for c in rows if c.get("status") != "Resolved"]
            return _Result(rows)
        if s.startswith("update public.complaints"):
            return _UpdateResult(self, s, params)
        # Migration 014: the AI write-back goes through a SECURITY DEFINER
        # function that updates only the seven ai_* columns of one row. The
        # elevated function bypasses RLS in production, so no visibility
        # check is applied here either.
        if "store_ai_suggestion" in s:
            keys = (
                "ai_category", "ai_summary", "ai_evidence", "ai_uncertainty",
                "ai_urgency", "ai_impact", "ai_safety",
            )
            row = self.store.complaints.get(str(params[0]))
            if row is not None:
                for key, value in zip(keys, params[1:]):
                    row[key] = value
            return _Result([])
        # Migration 014: the failure upsert is elevated the same way. The
        # fake store models no jobs table, so this is a faithful no-op.
        if "record_job_failure" in s:
            return _Result([])
        # Migration 015: automatic scoring. The elevated function reads the
        # ai_* levels just stored, scores them with the deterministic ladder
        # (urgency 30/15/0, impact 25/12/0, safety 10/5/0) and writes
        # priority_score + band. It mirrors store_auto_score exactly: a row that
        # already has a score is left alone (no re-score), and a missing level
        # defaults to Low. Tests assert the score appears without any admin
        # confirm call.
        if "store_auto_score" in s:
            row = self.store.complaints.get(str(params[0]))
            if row is not None and row.get("priority_score") is None:
                u = _level_points(row.get("ai_urgency"), {"high": 30, "medium": 15})
                i = _level_points(row.get("ai_impact"), {"high": 25, "medium": 12})
                sfty = _level_points(row.get("ai_safety"), {"high": 10, "medium": 5})
                total = float(u + i + sfty)
                if total <= 29:
                    band = "Low"
                elif total <= 54:
                    band = "Medium"
                elif total <= 74:
                    band = "High"
                else:
                    band = "Critical"
                # Safety floor: High safety can never band Low.
                if str(row.get("ai_safety") or "").strip().lower() == "high" and band == "Low":
                    band = "Medium"
                row["priority_score"] = total
                row["score_breakdown"] = {"total": total, "band": band, "source": "ai_auto"}
                row["score_computed_at"] = "2024-01-01T00:00:00Z"
                row["band"] = band
            return _Result([])
        return _Result([])


def _level_points(value, high_medium):
    """Deterministic level->points mirror of migration 015's CASE ladder."""
    key = str(value or "low").strip().lower()
    if key in high_medium:
        return high_medium[key]
    return 0


def _band_of(row):
    """Coarse band from a stored score; 'Unscored' for SQL NULL (D9)."""
    score = row.get("priority_score")
    if score is None:
        return "Unscored"
    score = float(score)
    if score <= 29:
        return "Low"
    if score <= 54:
        return "Medium"
    if score <= 74:
        return "High"
    return "Critical"


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _UpdateResult(_Result):
    def __init__(self, conn, sql, params):
        self._conn = conn
        self._sql = sql
        self._params = params
        self._rows = []
        store = conn.store
        # UPDATE ... WHERE id = %s  (params end with the id)
        cid = self._params[-1]
        row = store.complaints.get(str(cid))
        if row is None or not conn._visible(row):
            self._rows = []
        else:
            if " set ai_" in self._sql:
                # The AI suggestion path writes only ai_* columns. `self._sql`
                # arrives lower-cased (see FakeConn.execute); match " set ai_"
                # so the branch fires whatever ai_* column comes first in the
                # assignment list (ai_category leads in production).
                # Each assignment is "<column> = %s"; keep only the column name.
                assigns = self._sql.split("set ", 1)[1].split("where")[0]
                keys = [part.split("=")[0].strip() for part in assigns.split(",")]
                for key, value in zip(keys, self._params):
                    row[key] = value
            if "set confirmed_urgency" in self._sql:
                row.update(
                    confirmed_urgency=self._params[0],
                    confirmed_impact=self._params[1],
                    confirmed_safety=self._params[2],
                    confirmed_by=self._params[3],
                )
            if "set priority_score" in self._sql:
                import json as _json

                row["priority_score"] = float(self._params[0])
                row["score_breakdown"] = _json.loads(self._params[1])
            if "set status" in self._sql:
                row["status"] = self._params[0]
            self._rows = [row]
        super().__init__(self._rows)



class _ApprovalResult(_Result):
    """Models approve_for_public: upsert keyed on source_complaint_id."""

    def __init__(self, store, params):
        cid, summary, category, location, actor = params
        row = next((r for r in store.public
                    if str(r["source_complaint_id"]) == str(cid)), None)
        if row is None:
            row = {
                "id": f"pub-{len(store.public) + 1}",
                "source_complaint_id": cid,
                "public_summary": summary,
                "public_category": category,
                "public_location": location,
                "status": "Reported",
                "approved_at": "2026-01-01T00:00:00Z",
                "approved_by": actor,
            }
            store.public.append(row)
        else:
            row.update(public_summary=summary, public_category=category,
                       public_location=location, approved_at="2026-01-01T00:00:00Z",
                       approved_by=actor)
        super().__init__([{k: row[k] for k in
                           ("id", "public_summary", "public_category",
                            "public_location", "status", "approved_at")}])


class _RevokeResult(_Result):
    """Models revoke_public_approval: clears approved_at, never deletes."""

    def __init__(self, store, cid):
        row = next((r for r in store.public
                    if str(r["source_complaint_id"]) == str(cid)), None)
        if row is not None:
            row["approved_at"] = None
            row["approved_by"] = None
            super().__init__([{"id": row["id"]}])
        else:
            super().__init__([])


class FakeStore:
    def __init__(self):
        self.complaints: dict[str, dict] = {}
        self.roles: dict[str, str] = {
            STUDENT_A: "student",
            STUDENT_B: "student",
            ADMIN: "admin",
        }
        self.public: list[dict] = []
        self.events: list[dict] = []
        self.notes: list[dict] = []
        self.fail_next = None

    def create(self, _identity_user_id, params):
        """params follow the real SQL column order.

        (student_id, description, location_raw, location_code, image_path)
        """
        import uuid as _uuid

        cid = str(_uuid.uuid4())
        row = {
            "id": cid,
            "student_id": params[0],
            "description": params[1],
            "location_raw": params[2],
            "location_code": params[3],
            "image_path": params[4],
            "recurrence_na": False,
            "ai_category": None, "ai_summary": None, "ai_evidence": None,
            "ai_uncertainty": None, "ai_urgency": None, "ai_impact": None,
            "ai_safety": None,
            "confirmed_urgency": None, "confirmed_impact": None,
            "confirmed_safety": None, "analysis_confirmed_at": None,
            "confirmed_by": None,
            "priority_score": None, "score_breakdown": None,
            "score_version": "v1", "score_computed_at": None,
            "status": "Reported",
            "created_at": datetime.now(timezone.utc),
            "updated_at": None, "resolved_at": None,
        }
        self.complaints[cid] = row
        return row


@pytest.fixture
def store():
    return FakeStore()


# ---------------------------------------------------------------------------
# Settings + client
# ---------------------------------------------------------------------------
@pytest.fixture
def settings() -> config.Settings:
    # Good-era config: Settings is a frozen dataclass with no db_path /
    # upload_dir (SQLite and the local upload folder are gone). Secrets are
    # obvious fakes; bucket matches SUPABASE_BUCKET in .env.
    return config.Settings(
        database_url="postgresql://fake/fake",
        supabase_url="https://fake.supabase.co",
        supabase_anon_key="fake-anon",
        supabase_service_role_key="fake-service-role",
        bucket="CLimage",
        ai_enabled=True,
    )


@pytest.fixture
def client(settings, store, tokens, rsa_key, jwks):
    """TestClient with JWT, database, storage and AI all faked."""
    import httpx

    # 1. JWKS served locally; every other HTTP call passes through untouched.
    _real_get = httpx.Client.get

    def fake_get(self, url, *a, **kw):
        if str(url).endswith("/.well-known/jwks.json"):
            return httpx.Response(200, json=jwks, request=httpx.Request("GET", str(url)))
        return _real_get(self, url, *a, **kw)

    # 2. Storage: record uploads, return a fake signed URL.
    uploads: list[str] = []
    storage_error: list[bool] = [False]

    def fake_upload(settings, *, object_path, data, mime):
        if storage_error[0]:
            raise storage.StorageError("Image storage unavailable.")
        uploads.append(object_path)
        return object_path

    def fake_signed(settings, *, object_path):
        return f"https://fake.supabase.co/signed/{object_path}"

    # 3. Database: our RLS-like fake.
    def fake_session(database_url, identity):
        conn = FakeConn(store)
        conn.identity = identity

        class _Ctx:
            def __enter__(_s):
                return conn

            def __exit__(_s, *a):
                return False

        return _Ctx()

    app = create_app(settings)

    with patch.object(httpx.Client, "get", fake_get), \
         patch.object(storage, "upload_image", fake_upload), \
         patch.object(storage, "create_signed_url", fake_signed), \
         patch.object(database, "session", fake_session), \
         patch.object(auth, "_fetch_jwks", _jwks_patcher(jwks)):
        with TestClient(app) as c:
            c.uploads = uploads
            c.storage_error = storage_error
            c.store = store
            c.tokens = tokens
            yield c


def _jwks_patcher(jwks):
    """Serve the local JWKS so token verification needs no network."""
    def fake_fetch(settings):
        return {k["kid"]: k for k in jwks["keys"]}
    return fake_fetch
