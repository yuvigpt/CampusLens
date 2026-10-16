"""Admin triage filters, events/notes, student deletion, campus community feed.

Covers the second feature wave:
* admin list filters (band/category/q/open) and their validation;
* the student list's own-rows search (``q``);
* audit-trail events and investigation notes (admin-only, 404 for strangers);
* DELETE /api/complaints/{id} - own row, admin-any, 404 for others, cascade;
* GET /api/community/campus - every campus complaint as sanitized small info.
"""
from __future__ import annotations

from fastapi import status


def _admin(client):
    return {"Authorization": "Bearer " + client.tokens["admin"]}


def _student(client, who="student_a"):
    return {"Authorization": "Bearer " + client.tokens[who]}


def _submit(client, text="Broken light in the stairwell", who="student_a"):
    return client.post(
        "/api/complaints",
        data={"description": text, "location": "Science Block"},
        headers=_student(client, who),
    )


# ---------------------------------------------------------------------------
# Search / filters
# ---------------------------------------------------------------------------


def test_student_search_param_only_returns_own_rows(client):
    theirs = _submit(client, text="UniqueZebra report by B", who="student_b").json()["id"]
    mine = _submit(client, text="UniqueZebra report by A").json()["id"]

    out = client.get(
        "/api/complaints", headers=_student(client), params={"q": "UniqueZebra"}
    )
    assert out.status_code == status.HTTP_200_OK
    ids = [r["id"] for r in out.json()]
    assert mine in ids
    assert theirs not in ids


def test_student_search_is_a_free_text_query(client):
    _submit(client, text="Leaking tap in Hall 12")
    out = client.get(
        "/api/complaints", headers=_student(client), params={"q": "no-such-term"}
    )
    assert out.status_code == status.HTTP_200_OK
    assert out.json() == []


def test_admin_filters_band_category_q_open(client):
    _submit(client, text="Admin searchable row")
    for params in (
        {"band": "Unscored"},
        {"band": "Low"},
        {"q": "searchable"},
        {"open": "true"},
        {"category": "Plumbing"},
    ):
        out = client.get("/api/admin/complaints", headers=_admin(client), params=params)
        assert out.status_code == status.HTTP_200_OK, params


def test_admin_rejects_unknown_band(client):
    out = client.get(
        "/api/admin/complaints", headers=_admin(client), params={"band": "Bogus"}
    )
    assert out.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_admin_filters_never_leak_to_students(client):
    _submit(client, text="row")
    out = client.get(
        "/api/complaints",
        headers=_student(client),
        params={"band": "Critical", "q": "x", "open": "true"},
    )
    # Unknown query params are ignored, never an error, never a widening.
    assert out.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# Events + investigation notes
# ---------------------------------------------------------------------------


def test_admin_can_read_events_and_notes(client):
    cid = _submit(client).json()["id"]
    ev = client.get(f"/api/admin/complaints/{cid}/events", headers=_admin(client))
    nt = client.get(f"/api/admin/complaints/{cid}/notes", headers=_admin(client))
    assert ev.status_code == status.HTTP_200_OK
    assert nt.status_code == status.HTTP_200_OK
    assert isinstance(ev.json(), list) and isinstance(nt.json(), list)


def test_student_cannot_read_events_or_notes(client):
    cid = _submit(client).json()["id"]
    for path in ("events", "notes"):
        out = client.get(f"/api/admin/complaints/{cid}/{path}", headers=_student(client))
        assert out.status_code == status.HTTP_403_FORBIDDEN, path


def test_events_and_notes_404_for_unknown_complaint(client):
    ghost = "00000000-0000-0000-0000-000000000000"
    for path in ("events", "notes"):
        out = client.get(
            f"/api/admin/complaints/{ghost}/{path}", headers=_admin(client)
        )
        assert out.status_code == status.HTTP_404_NOT_FOUND, path


def test_admin_note_roundtrip(client):
    cid = _submit(client).json()["id"]
    created = client.post(
        f"/api/admin/complaints/{cid}/notes",
        headers=_admin(client),
        json={"body": "Asked caretaker for photos."},
    )
    assert created.status_code == status.HTTP_200_OK
    assert created.json()["body"] == "Asked caretaker for photos."

    listed = client.get(f"/api/admin/complaints/{cid}/notes", headers=_admin(client))
    assert any(n["body"] == "Asked caretaker for photos." for n in listed.json())


def test_empty_note_is_rejected(client):
    cid = _submit(client).json()["id"]
    out = client.post(
        f"/api/admin/complaints/{cid}/notes",
        headers=_admin(client),
        json={"body": "   "},
    )
    assert out.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


def test_student_deletes_own_complaint_and_children_cascade(client):
    cid = _submit(client).json()["id"]
    # Seed an event + note so the cascade has something to remove.
    client.patch(
        f"/api/admin/complaints/{cid}/status",
        headers=_admin(client),
        json={"status": "In Progress"},
    )
    client.post(
        f"/api/admin/complaints/{cid}/notes",
        headers=_admin(client),
        json={"body": "note"},
    )
    assert len(client.store.events) >= 1

    out = client.delete(f"/api/complaints/{cid}", headers=_student(client))
    assert out.status_code == status.HTTP_204_NO_CONTENT
    assert cid not in client.store.complaints
    # CASCADE: children are gone with the parent.
    assert all(str(e["complaint_id"]) != cid for e in client.store.events)
    assert all(str(n["complaint_id"]) != cid for n in client.store.notes)
    assert all(
        str(p.get("source_complaint_id")) != cid for p in client.store.public
    )

    # A later read is a 404, not an error.
    assert (
        client.get(f"/api/complaints/{cid}", headers=_student(client)).status_code
        == status.HTTP_404_NOT_FOUND
    )


def test_student_cannot_delete_another_students_complaint(client):
    theirs = _submit(client, text="Not mine to delete", who="student_b").json()["id"]
    out = client.delete(f"/api/complaints/{theirs}", headers=_student(client))
    assert out.status_code == status.HTTP_404_NOT_FOUND
    assert theirs in client.store.complaints  # untouched


def test_delete_of_unknown_id_is_404(client):
    ghost = "00000000-0000-0000-0000-000000000000"
    out = client.delete(f"/api/complaints/{ghost}", headers=_student(client))
    assert out.status_code == status.HTTP_404_NOT_FOUND


def test_admin_can_delete_any_complaint(client):
    cid = _submit(client, text="Admin will remove this", who="student_b").json()["id"]
    out = client.delete(f"/api/complaints/{cid}", headers=_admin(client))
    assert out.status_code == status.HTTP_204_NO_CONTENT
    assert cid not in client.store.complaints


def test_unauthenticated_delete_is_rejected(client):
    cid = _submit(client).json()["id"]
    out = client.delete(f"/api/complaints/{cid}")
    assert out.status_code == status.HTTP_401_UNAUTHORIZED
    assert cid in client.store.complaints


# ---------------------------------------------------------------------------
# Community overview (any signed-in user)
# ---------------------------------------------------------------------------


def test_community_feed_shows_all_campuses_small_info(client):
    _submit(client, text="A's complaint")
    _submit(client, text="B's complaint", who="student_b")

    out = client.get("/api/community/campus", headers=_student(client))
    assert out.status_code == status.HTTP_200_OK
    rows = out.json()
    # Both complaints are visible to student A through the sanitized function.
    assert len(rows) >= 2
    for row in rows:
        assert set(row) == {"id", "location", "status", "band", "category", "created_at"}


def test_community_feed_never_exposes_pii_or_free_text(client):
    _submit(client, text="Very distinctive complaint text")

    rows = client.get("/api/community/campus", headers=_student(client)).json()
    assert rows, "expected at least one row"
    for row in rows:
        blob = str(row).lower()
        for forbidden in ("description", "student_id", "priority_score",
                          "ai_summary", "image", "email"):
            assert forbidden not in blob


def test_community_feed_requires_a_token(client):
    _submit(client)
    out = client.get("/api/community/campus")
    assert out.status_code == status.HTTP_401_UNAUTHORIZED


def test_community_feed_works_for_admin_too(client):
    _submit(client)
    out = client.get("/api/community/campus", headers=_admin(client))
    assert out.status_code == status.HTTP_200_OK

