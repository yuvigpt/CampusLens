"""Private image storage: type, size and ownership."""

import io
import zlib
import struct


def make_jpeg(payload_size: int = 64) -> bytes:
    """A byte string that really starts with the JPEG magic number."""
    return b"\xff\xd8\xff\xe0" + b"\x00" * 10 + b"JFIF" + b"\x00" * payload_size + b"\xff\xd9"


def make_png() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


def make_webp() -> bytes:
    return b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 20


def _submit(client, who, *, filename="photo.jpg", data=None, ctype="image/jpeg"):
    """POST one complaint. `data=None` means "a valid JPEG"."""
    if data is None:
        data = make_jpeg()
    headers = {"Authorization": "Bearer " + client.tokens[who]}
    return client.post(
        "/api/complaints",
        data={"description": "Broken light in the stairwell", "location": "Science Block"},
        files={"image": (filename, io.BytesIO(data), ctype)},
        headers=headers,
    )


def test_valid_jpeg_is_uploaded_under_the_owner_prefix(client):
    r = _submit(client, "student_a")
    assert r.status_code == 201
    assert len(client.uploads) == 1
    path = client.uploads[0]
    student_a = "11111111-1111-4111-8111-111111111111"
    assert path.startswith(f"{student_a}/"), path
    assert path.endswith((".jpg", ".jpeg", ".png", ".webp"))


def test_png_is_detected_from_its_bytes_not_the_header(client):
    # Claims JPEG, but the bytes are PNG: the magic number must win.
    r = _submit(client, "student_a", filename="x.jpg", data=make_png(), ctype="image/jpeg")
    assert r.status_code == 201
    assert client.uploads[0].endswith(".png")


def test_webp_is_accepted(client):
    r = _submit(client, "student_a", data=make_webp())
    assert r.status_code == 201
    assert client.uploads[0].endswith(".webp")


def test_a_non_image_is_rejected(client):
    r = _submit(client, "student_a", data=b"#!/bin/sh\nrm -rf /", ctype="application/x-sh")
    assert r.status_code == 422
    assert client.uploads == []


def test_an_oversized_image_is_rejected(client):
    r = _submit(client, "student_a", data=b"\xff\xd8\xff" + b"\x00" * (6 * 1024 * 1024))
    assert r.status_code == 413
    assert client.uploads == []


def test_an_empty_file_is_rejected(client):
    r = _submit(client, "student_a", data=b"")
    assert r.status_code == 422


def test_the_client_filename_is_never_used_as_the_path(client):
    r = _submit(client, "student_a", filename="../../app/database.py")
    assert r.status_code in (201, 422)
    for path in client.uploads:
        assert ".." not in path
        assert "database.py" not in path


def test_storage_failure_writes_nothing(client):
    client.storage_error[0] = True
    r = _submit(client, "student_a")
    assert r.status_code == 502
    assert client.store.complaints == {}


def test_the_complaint_references_the_exact_object_path(client):
    r = _submit(client, "student_a")
    cid = r.json()["id"]
    assert client.store.complaints[cid]["image_path"] == client.uploads[0]


def test_a_student_does_not_get_a_signed_url_for_someone_else(client):
    a = client.post(
        "/api/complaints",
        data={"description": "Broken light in the stairwell", "location": "Science Block"},
        files={"image": ("p.jpg", io.BytesIO(make_jpeg()), "image/jpeg")},
        headers={"Authorization": "Bearer " + client.tokens["student_a"]},
    )
    cid = a.json()["id"]
    b = client.get(
        f"/api/complaints/{cid}",
        headers={"Authorization": "Bearer " + client.tokens["student_b"]},
    )
    assert b.status_code == 404


def test_the_owner_receives_a_signed_url(client):
    r = client.post(
        "/api/complaints",
        data={"description": "Broken light in the stairwell", "location": "Science Block"},
        files={"image": ("p.jpg", io.BytesIO(make_jpeg()), "image/jpeg")},
        headers={"Authorization": "Bearer " + client.tokens["student_a"]},
    )
    got = client.get(
        f"/api/complaints/{r.json()['id']}",
        headers={"Authorization": "Bearer " + client.tokens["student_a"]},
    )
    assert got.status_code == 200
    assert got.json()["image_url"].startswith("https://fake.supabase.co/signed/")


def test_create_signed_url_ensures_storage_v1_prefix(monkeypatch):
    from app import config, storage

    test_settings = config.Settings(
        database_url="postgresql://fake",
        supabase_url="https://testproj.supabase.co",
        supabase_anon_key="fake-anon",
        supabase_service_role_key="test-key",
        bucket="CLimage",
    )

    class DummyResponse:
        status_code = 200

        def json(self):
            return {"signedURL": "/object/sign/CLimage/user/pic.jpg?token=abc"}

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, json=None, headers=None):
            return DummyResponse()

    monkeypatch.setattr(storage.httpx, "Client", DummyClient)
    signed = storage.create_signed_url(test_settings, object_path="user/pic.jpg")
    assert (
        signed
        == "https://testproj.supabase.co/storage/v1/object/sign/CLimage/user/pic.jpg?token=abc"
    )

