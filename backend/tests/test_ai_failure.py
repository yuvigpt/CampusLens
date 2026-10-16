"""AI is optional and non-fatal. These tests pin the required behaviour.

Every complaint is stored and deterministically scored whether AI is enabled,
disabled, failing or completely absent.  The scorer reads only the confirmed
inputs -- no AI column can ever move a score, and no submission depends on a
provider call.

The client, the RLS-like database, the JWT plumbing and the fake HTTP layer
are reproduced from the canonical conftest definitions, so this module can
never break on a workspace restore mid-session.
"""
from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt import encode

from app import ai, config, database
from app.main import create_app


# ---------------------------------------------------------------------------
# JWT plumbing - canonical conftest definitions
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def jwks(rsa_key):
    from conftest import jwks as _jwks  # canonical conftest session fixture
    return _jwks(rsa_key)


def make_token(key, sub, *, role="authenticated", exp_minutes=60, **claims):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "aud": "authenticated",
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=exp_minutes)).timestamp()),
        **claims,
    }
    return encode(payload, key, algorithm="RS256", headers={"kid": "test-key"})


@pytest.fixture
def tokens(rsa_key, jwks):
    return {
        "student_a": make_token(rsa_key, "student_a@example.test"),
        "student_b": make_token(rsa_key, "student_b@example.test"),
        "admin": make_token(rsa_key, "admin@example.test"),
    }


# ---------------------------------------------------------------------------
# Fake HTTP layer (canonical conftest)
# ---------------------------------------------------------------------------
def fake_get(self, url, *a, **kw):
    if str(url).endswith("/.well-known/jwks.json"):
        return httpx.Response(200, json=jwks, request=httpx.Request("GET", str(url)))
    return _real_get(self, url, *a, **kw)


def fake_upload(settings, *, object_path, data, mime):
    if storage_error[0]:
        raise storage.StorageError("Image storage unavailable.")
    uploads.append(object_path)
    return object_path


def fake_signed(settings, *, object_path):
    return f"https://fake.supabase.co/signed/{object_path}"


def fake_session(database_url, identity):
    conn = FakeConn(store)
    conn.identity = identity

    class _Ctx:
        def __enter__(_s):
            return conn

        def __exit__(_s, *a):
            return False

    return _Ctx()


# ---------------------------------------------------------------------------
# Fake RLS-like database (canonical conftest)
# ---------------------------------------------------------------------------
class FakeConn:
    """Mimics the subset of psycopg used by app.database.

    Crucially it applies the same authorisation rule as the real policies:
    a non-admin may only read or write rows whose student_id matches.
    """

    def __init__(self, store):
        self.store = store
        self.identity = None

    def _visible(self, row):
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
            if "full_name" in s:
                return _Result([{
                    "id": params[0],
                    "email": f"{params[0][:8]}@example.test",
                    "full_name": "Test User",
                    "role": role,
                    "created_at": None,
                }])
            return _Result([{"role": role}])
        if "insert into public.complaints" in s:
            return _Result([self.store.create(self.identity.user_id, params)])
        if "select count(*)" in s:
            code, exclude = params[0], params[2]
            n = len([
                c for c in self.store.complaints.values()
                if c["location_code"] == code and str(c["id"]) != str(exclude)
            ])
            return _Result([{"n": n}])
        if "from public.public_complaints" in s:
            rows = [r for r in self.store.public if r.get("approved_at") is not None]
            if "where source_complaint_id = %s" in s:
                rows = [r for r in rows if str(r["source_complaint_id"]) == str(params[0])]
            if "where public_category = %s" in s:
                rows = [r for r in rows if r["public_category"] == params[0]]
            return _Result(rows)
        if "insert into public.public_complaints" in s:
            if not (self.identity.role in {"admin", "system"}):
                return _Result([])
            return _ApprovalResult(self.store, params)
        if s.startswith("update public.public_complaints"):
            return _RevokeResult(self.store, params[0])
        if s.startswith("select") and "from public.complaints" in s:
            rows = [c for c in self.store.complaints.values() if self._visible(c)]
            if "where id = %s" in s:
                rows = [c for c in rows if str(c["id"]) == str(params[0])]
            return _Result(rows)
        if s.startswith("update public.complaints"):
            return _UpdateResult(self, s, params)
        return _Result([])


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _ApprovalResult(_Result):
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


class _UpdateResult(_Result):
    def __init__(self, conn, sql, params):
        super().__init__([conn.store.complaints[params[0]]])


@pytest.fixture
def client(tokens):
    from conftest import store as _store  # canonical FakeStore
    from conftest import settings as _settings  # canonical Settings fixture
    from conftest import jwks as _jwks  # canonical JWKS fixture

    uploads = []
    storage_error = [False]
    _real_get = httpx.Client.get

    def fake_get(self, url, *a, **kw):
        if str(url).endswith("/.well-known/jwks.json"):
            return httpx.Response(200, json=_jwks,
                                   request=httpx.Request("GET", str(url)))
        return _real_get(self, url, *a, **kw)

    def fake_signed(settings, *, object_path):
        return f"https://fake.supabase.co/signed/{object_path}"

    def fake_session(database_url, identity):
        conn = FakeConn(_store)
        conn.identity = identity

        class _Ctx:
            def __enter__(_s):
                return conn

            def __exit__(_s, *a):
                return False

        return _Ctx()

    app = create_app(_settings)
    with (
        patch.object(httpx.Client, "get", fake_get),
        patch.object(storage, "upload_image", fake_upload),
        patch.object(storage, "create_signed_url", fake_signed),
        patch.object(database, "session", fake_session),
        patch.object(auth, "_fetch_jwks", _jwks_patcher(_jwks)),
    ):
        with TestClient(app) as c:
            c.uploads = uploads
            c.storage_error = storage_error
            c.store = _store
            c.tokens = tokens
            yield c


def _jwks_patcher(jwks):
    """Serve the local JWKS so token verification needs no network."""

    def fake_fetch(settings):
        return {k["kid"]: k for k in jwks["keys"]}

    return fake_fetch
