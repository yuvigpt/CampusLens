"""The public approval gate.

A complaint becomes public ONLY because an admin published it. A student
submission must never appear in the community feed by itself.

These tests pin the gate at three levels:
  1. schema  - approved_at is nullable, so draft vs approved is representable
  2. policy  - only an admin can write public_complaints at all
  3. flow    - publication happens only through the admin approval route
"""

import re
from pathlib import Path

APPROVE = "/public-approval"


def _admin(client):
    return {"Authorization": "Bearer " + client.tokens["admin"]}


def _student(client):
    return {"Authorization": "Bearer " + client.tokens["student_a"]}


def _submit(client, text="Broken light in the stairwell"):
    return client.post(
        "/api/complaints",
        data={"description": text, "location": "Science Block"},
        headers=_student(client),
    ).json()["id"]


def _publish(client, cid, summary="Lighting fault reported on the main stairwell",
             category="Electrical", location="Science Block, ground floor"):
    return client.post(f"/api/admin/complaints/{cid}{APPROVE}", json={
        "public_summary": summary, "public_category": category,
        "public_location": location,
    }, headers=_admin(client))


# ---------------------------------------------------------------------------
# 1. Schema: draft must be representable
# ---------------------------------------------------------------------------
def test_approved_at_is_nullable_in_the_migration():
    """If approved_at were NOT NULL, the approval policy could never filter."""
    sql = (Path(__file__).resolve().parent.parent
           / "migrations" / "007_public.sql").read_text(encoding="utf-8")
    assert re.search(r"approved_at\s+timestamptz\s*(?!NOT NULL)", sql), \
        "approved_at must be nullable so an unpublished draft is representable"
    assert "approved_at         timestamptz NOT NULL" not in sql


def test_public_policy_filters_on_approved_at():
    sql = (Path(__file__).resolve().parent.parent
           / "migrations" / "007_public.sql").read_text(encoding="utf-8")
    assert "USING (approved_at IS NOT NULL)" in sql


# ---------------------------------------------------------------------------
# 2. Policy: only admins can publish
# ---------------------------------------------------------------------------
def test_student_cannot_publish(client):
    cid = _submit(client)
    r = _publish(client, cid)          # helper sends ADMIN headers; override:
    assert r.status_code == 200        # admin path works
    r2 = client.post(f"/api/admin/complaints/{cid}{APPROVE}", json={
        "public_summary": "Student tries to publish this",
        "public_category": "Electrical",
        "public_location": "Science Block",
    }, headers=_student(client))
    assert r2.status_code == 403


def test_anonymous_cannot_publish(client):
    cid = _submit(client)
    r = client.post(f"/api/admin/complaints/{cid}{APPROVE}", json={
        "public_summary": "Anonymous tries to publish this",
        "public_category": "Electrical",
        "public_location": "Science Block",
    })
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# 3. Flow: submission alone never publishes
# ---------------------------------------------------------------------------
def test_submitted_complaint_is_absent_from_the_public_feed(client):
    _submit(client)
    assert client.get("/api/public/complaints").json() == []


def test_several_unapproved_complaints_stay_private(client):
    for i, text in enumerate(("Broken light", "Cracked window", "Leaking tap")):
        client.post("/api/complaints",
                    data={"description": text, "location": "Science Block"},
                    headers={"Authorization": "Bearer " + client.tokens[
                        "student_a" if i % 2 == 0 else "student_b"]})
    assert len(client.store.complaints) == 3
    assert client.get("/api/public/complaints").json() == []


def test_admin_publish_makes_it_appear(client):
    cid = _submit(client)
    r = _publish(client, cid)
    assert r.status_code == 200
    feed = client.get("/api/public/complaints").json()
    assert len(feed) == 1
    assert feed[0]["public_summary"].startswith("Lighting fault")


def test_revoking_hides_it_again(client):
    cid = _submit(client)
    _publish(client, cid)
    assert len(client.get("/api/public/complaints").json()) == 1

    r = client.delete(f"/api/admin/complaints/{cid}{APPROVE}", headers=_admin(client))
    assert r.status_code == 204
    assert client.get("/api/public/complaints").json() == []


def test_student_cannot_revoke(client):
    cid = _submit(client)
    _publish(client, cid)
    r = client.delete(f"/api/admin/complaints/{cid}{APPROVE}", headers=_student(client))
    assert r.status_code == 403
    assert len(client.get("/api/public/complaints").json()) == 1


def test_republishing_updates_rather_than_duplicates(client):
    cid = _submit(client)
    _publish(client, cid, summary="First published summary")
    _publish(client, cid, summary="Corrected published summary")
    feed = client.get("/api/public/complaints").json()
    assert len(feed) == 1
    assert feed[0]["public_summary"] == "Corrected published summary"


def test_publication_state_is_admin_only(client):
    cid = _submit(client)
    assert client.get(f"/api/admin/complaints/{cid}{APPROVE}",
                       headers=_student(client)).status_code == 403
    assert client.get(f"/api/admin/complaints/{cid}{APPROVE}",
                      headers=_admin(client)).json() is None


def test_published_text_never_includes_the_original_report(client):
    """The admin supplies the text; the reporter's words are not copied."""
    cid = _submit(client, "I am the only woman on this floor and I am scared")
    _publish(client, cid)
    body = client.get("/api/public/complaints").text
    assert "only woman" not in body
    assert "scared" not in body


def test_short_summary_is_rejected(client):
    cid = _submit(client)
    r = _publish(client, cid, summary="too short")
    assert r.status_code == 422
    assert client.get("/api/public/complaints").json() == []


def test_publishing_an_unknown_complaint_is_404(client):
    r = _publish(client, "00000000-0000-4000-8000-000000000000")
    assert r.status_code == 404
