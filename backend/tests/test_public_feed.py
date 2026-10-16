"""GET /api/public/complaints - the community feed.

Unauthenticated, but must only ever expose approved, sanitized rows: no
reporter identity, no score, no free-text description, no internal location
code.
"""

FORBIDDEN = [
    "student_id", "priority_score", "score_breakdown", "description",
    "location_raw", "location_code", "image_path", "confirmed_urgency",
    "confirmed_impact", "confirmed_safety", "confirmed_by", "ai_summary",
    "ai_evidence", "ai_uncertainty", "ai_urgency", "ai_impact", "ai_safety",
]


def _seed_public(client, rows):
    """Populate the fake public table with APPROVED entries.

    Stands in for an admin having published them, so these rows pass the
    public_read_approved gate (approved_at IS NOT NULL).
    """
    client.store.public.clear()
    for summary, category in rows:
        client.store.public.append({
            "id": f"pub-{len(client.store.public) + 1}",
            "public_summary": summary,
            "public_category": category,
            "public_location": "Science Block, ground floor",
            "status": "Reported",
            # Seeded rows are APPROVED entries: approved_at must be set for the
            # public_read_approved policy to let them through.
            "approved_at": "2026-01-01T00:00:00Z",
        })


def test_public_feed_needs_no_token(client):
    _seed_public(client, [("Lighting fault reported", "Electrical")])
    r = client.get("/api/public/complaints")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_public_feed_is_empty_when_nothing_is_approved(client):
    assert client.get("/api/public/complaints").json() == []


def test_public_row_exposes_only_the_approved_fields(client):
    _seed_public(client, [("Lighting fault reported", "Electrical")])
    row = client.get("/api/public/complaints").json()[0]
    assert set(row) == {
        "id", "public_summary", "public_category", "public_location",
        "status", "approved_at",
    }


def test_public_response_never_contains_internal_fields(client):
    _seed_public(client, [("Lighting fault reported", "Electrical")])
    body = client.get("/api/public/complaints").text
    for field in FORBIDDEN:
        assert field not in body, f"{field} leaked from the public feed"


def test_unapproved_complaints_are_absent(client):
    # Two real complaints exist, but nothing was approved for publication.
    headers = {"Authorization": "Bearer " + client.tokens["student_a"]}
    for text in ("Broken light in the stairwell", "Cracked window in lab 2"):
        client.post(
            "/api/complaints",
            data={"description": text, "location": "Science Block"},
            headers=headers,
        )
    assert len(client.store.complaints) == 2
    # The feed is driven by public_complaints, not by complaints.
    assert client.get("/api/public/complaints").json() == []


def test_public_feed_ignores_the_callers_token(client):
    """Supplying a student token must not widen or change the feed."""
    _seed_public(client, [("Lighting fault reported", "Electrical")])
    anon = client.get("/api/public/complaints").json()
    as_student = client.get(
        "/api/public/complaints",
        headers={"Authorization": "Bearer " + client.tokens["student_a"]},
    ).json()
    assert anon == as_student


def test_public_feed_supports_the_category_filter(client):
    _seed_public(client, [
        ("Lighting fault reported", "Electrical"),
        ("Leaking tap in the washroom", "Plumbing"),
    ])
    only = client.get("/api/public/complaints?category=Plumbing").json()
    assert len(only) == 1
    assert only[0]["public_category"] == "Plumbing"
