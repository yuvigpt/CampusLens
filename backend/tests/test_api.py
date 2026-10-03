"""
Offline API tests for Stage 4 (FastAPI core backend).

These tests never touch the network and never write to the real database.
Each test gets:

  * a temporary SQLite file   -> ``config.settings_for(temp_db, temp_uploads)``
  * a temporary uploads folder
  * an app built with ``create_app()`` so nothing imports the module-level
    ``app`` with its production settings
  * a network guard that fails loudly if ``gemini.call_gemini`` is reached
  * a stubbed ``analyze_complaint``, so no API key and no quota are needed

Run from anywhere with the project venv:

    backend\\venv\\Scripts\\python.exe -m unittest discover -s backend/tests -t backend
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Make "from app import ..." work regardless of the current working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import config, database, gemini, priority, storage  # noqa: E402
from app.main import create_app  # noqa: E402

# A deliberately fake secret, so a leak in a response body is easy to spot.
FAKE_SECRET = "AQ.FAKE-test-secret-do-not-use-1234567890"

KNOWN_ANALYSIS = {
    "category": "Electrical",
    "issue_summary": "Exposed wiring beside a ceiling fan mount.",
    "safety_risk": "High",
    "functional_impact": "Medium",
    "urgency": "High",
    "evidence_from_image": "Bare wires and scorch marks are visible near the fan.",
    "uncertainty_or_missing_information": "Cannot tell whether the breaker is live.",
}

# Same shape, but a category that is NOT in priority.DEFAULT_CATEGORY_CLASSES.
UNKNOWN_CATEGORY_ANALYSIS = dict(KNOWN_ANALYSIS, category="Hyperdrive Manifold")

# gemini.load_image only checks the name and size, and the Gemini call is
# stubbed anyway, so these bytes never need to be a real image.
FAKE_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n" + b"CampusLens fake image payload " * 20

GOOD_DESCRIPTION = "Broken fan in Block C lab, sparks when switched on"
GOOD_LOCATION = "Block C computer lab"


class ApiTestCase(unittest.TestCase):
    """Shared fixture: temp DB, temp uploads, stubbed Gemini, isolated app."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="campuslens_api_test_"))
        self.addCleanup(shutil.rmtree, self.tmp_dir, True)   # runs last
        self.db_path = self.tmp_dir / "test.db"
        self.upload_dir = self.tmp_dir / "uploads"

        # A developer's shell must not change what these tests see: strip
        # any SUPABASE_* variables (patch.dict restores them afterwards).
        self._env_patcher = mock.patch.dict(os.environ)
        self._env_patcher.start()
        self.addCleanup(self._env_patcher.stop)
        # DATABASE_URL is stripped so tests can never be routed to a real
        # PostgreSQL server, even if the developer's shell exports it.
        for name in (
            "DATABASE_URL",
            "SUPABASE_URL",
            "SUPABASE_SERVICE_ROLE_KEY",
            "SUPABASE_BUCKET",
        ):
            os.environ.pop(name, None)

        # SAFETY NET: any test that reaches the real Gemini call fails loudly
        # here instead of quietly spending API quota.
        self._network_guard = mock.patch.object(
            gemini,
            "call_gemini",
            side_effect=AssertionError("a test tried to make a real Gemini call"),
        )
        self._network_guard.start()
        self.addCleanup(self._network_guard.stop)

        # Second SAFETY NET: no test may ever reach Supabase over HTTP.
        # Storage behaviour is always mocked one level above httpx.post.
        self._storage_guard = mock.patch.object(
            storage.httpx,
            "post",
            side_effect=AssertionError("a test tried to make a real Supabase call"),
        )
        self._storage_guard.start()
        self.addCleanup(self._storage_guard.stop)

        self.start_client()

    # -- fixture helpers ---------------------------------------------------
    def start_client(self, *, raise_server_exceptions=True, **overrides):
        """Build the app on the temp paths and run its lifespan (init_db)."""
        settings = config.settings_for(self.db_path, self.upload_dir, **overrides)
        self.app = create_app(settings)
        client = TestClient(self.app, raise_server_exceptions=raise_server_exceptions)
        client.__enter__()          # runs startup: schema + uploads folder
        self.addCleanup(client.__exit__, None, None, None)
        self.client = client
        return client

    def stub_analysis(self, *, analysis=None, ok=True, error=None,
                      error_kind=None, warnings=(), result=None):
        """Replace gemini.analyze_complaint with a canned AnalysisResult."""
        if result is None:
            result = gemini.AnalysisResult(
                ok=ok,
                analysis=analysis,
                error=error,
                error_kind=error_kind,
                model="gemini-3.8-flash",
                elapsed_seconds=0.11,
                warnings=tuple(warnings),
            )
        patcher = mock.patch.object(gemini, "analyze_complaint", return_value=result)
        patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def submit(self, *, description=GOOD_DESCRIPTION, location=GOOD_LOCATION,
               filename="photo.png", content_type="image/png",
               content=FAKE_IMAGE_BYTES, omit=()):
        """POST a multipart complaint. `omit` drops fields to test validation."""
        data = {"description": description, "location": location}
        for field in omit:
            data.pop(field, None)
        files = None
        if "image" not in omit:
            files = {"image": (filename, content, content_type)}
        return self.client.post("/api/complaints", data=data, files=files)

    def seed(self, **fields):
        """Insert a complaint straight through the database layer."""
        fields.setdefault("description", "Seeded complaint")
        fields.setdefault("location", "Seeded location")
        return database.create_complaint(db_path=self.db_path, **fields)

    @staticmethod
    def expected_score(analysis):
        """Score an analysis with priority.py, so tests never hard-code numbers."""
        weight = priority.category_weight_class(analysis["category"])
        return priority.score_complaint(
            safety_risk=analysis["safety_risk"],
            functional_impact=analysis["functional_impact"],
            urgency=analysis["urgency"],
            category_weight=weight,
        )


class HealthTest(ApiTestCase):
    """GET /api/health is a liveness probe, not an information leak."""

    def test_health_returns_ok(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "ok", "service": "campuslens-api", "version": "1.0.0"},
        )

    def test_health_leaks_no_paths_or_secrets(self):
        text = self.client.get("/api/health").text
        for forbidden in (
            "campuslens.db", ".env", "venv", "C:\\", "/backend",
            "GEMINI_API_KEY", FAKE_SECRET, "uploads/",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)

    def test_openapi_document_is_served(self):
        self.assertEqual(self.client.get("/openapi.json").status_code, 200)


class SubmitComplaintTest(ApiTestCase):
    """POST /api/complaints - the full image -> Gemini -> score -> store path."""

    def test_success_with_known_category_is_scored_and_saved(self):
        self.stub_analysis(analysis=KNOWN_ANALYSIS)
        response = self.submit()

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        expected = self.expected_score(KNOWN_ANALYSIS)

        self.assertEqual(payload["category"], "Electrical")
        self.assertEqual(payload["priority_score"], expected.score)
        self.assertEqual(payload["priority_band"], expected.band)
        self.assertEqual(payload["score_breakdown"]["band"], expected.band)
        self.assertEqual(payload["score_breakdown"]["inputs"]["category_weight"],
                         priority.category_weight_class("Electrical"))
        self.assertEqual(payload["status"], database.STATUS_REPORTED)
        self.assertEqual(payload["warnings"], [])
        self.assertIsNone(payload["resolved_at"])

        # The AI outcome is reported back to the caller.
        self.assertTrue(payload["analysis"]["ok"])
        self.assertIsNone(payload["analysis"]["error"])
        self.assertEqual(payload["analysis"]["model"], "gemini-3.8-flash")

        # ...and the row really is in the temporary database.
        stored = database.get_complaint(payload["id"], db_path=self.db_path)
        self.assertIsNotNone(stored)
        self.assertEqual(stored["description"], GOOD_DESCRIPTION)
        self.assertEqual(stored["priority_score"], expected.score)

    def test_success_stores_exactly_one_generated_filename(self):
        self.stub_analysis(analysis=KNOWN_ANALYSIS)
        payload = self.submit(filename="holiday photos.png").json()

        on_disk = list(self.upload_dir.iterdir())
        self.assertEqual(len(on_disk), 1)
        # The client's name is never used: a generated 32-hex name is.
        stem = on_disk[0].stem
        self.assertEqual(len(stem), 32)
        self.assertEqual(payload["image_path"], f"uploads/{on_disk[0].name}")
        self.assertEqual(payload["image_url"], f"/uploads/{on_disk[0].name}")

    def test_gemini_failure_still_saves_the_complaint(self):
        self.stub_analysis(
            ok=False, analysis=None,
            error="Could not reach the analysis service.",
            error_kind="network",
        )
        response = self.submit()

        self.assertEqual(response.status_code, 201)
        payload = response.json()

        # The student's words and photo survive the failure...
        self.assertEqual(payload["description"], GOOD_DESCRIPTION)
        self.assertEqual(payload["location"], GOOD_LOCATION)
        self.assertTrue(payload["image_url"])
        self.assertEqual(payload["status"], database.STATUS_REPORTED)

        # ...with the AI columns and score left NULL, and a warning explaining it.
        self.assertIsNone(payload["category"])
        self.assertIsNone(payload["priority_score"])
        self.assertIsNone(payload["priority_band"])
        self.assertIsNone(payload["score_breakdown"])
        self.assertFalse(payload["analysis"]["ok"])
        self.assertEqual(payload["analysis"]["error_kind"], "network")
        self.assertTrue(any("unavailable" in w for w in payload["warnings"]))

        # A second row is never created.
        self.assertEqual(len(database.list_complaints(db_path=self.db_path)), 1)
        stored = database.get_complaint(payload["id"], db_path=self.db_path)
        self.assertIsNone(stored["category"])
        self.assertIsNone(stored["priority_score"])

    def test_unknown_category_is_saved_without_a_guessed_score(self):
        self.stub_analysis(analysis=UNKNOWN_CATEGORY_ANALYSIS)
        response = self.submit()

        self.assertEqual(response.status_code, 201)
        payload = response.json()

        # The analysis is kept as-is...
        self.assertEqual(payload["category"], "Hyperdrive Manifold")
        self.assertEqual(payload["issue_summary"], KNOWN_ANALYSIS["issue_summary"])
        self.assertTrue(payload["analysis"]["ok"])

        # ...but no score is invented for a category we cannot map.
        self.assertIsNone(payload["priority_score"])
        self.assertIsNone(payload["priority_band"])
        self.assertIsNone(payload["score_breakdown"])
        self.assertTrue(
            any("Hyperdrive Manifold" in w for w in payload["warnings"]),
            msg=f"expected an unmapped-category warning, got {payload['warnings']}",
        )

    def test_analysis_warnings_are_forwarded_to_the_caller(self):
        self.stub_analysis(analysis=KNOWN_ANALYSIS,
                           warnings=("Gemini added an unexpected field.",))
        payload = self.submit().json()
        self.assertIn("Gemini added an unexpected field.", payload["warnings"])

    def test_missing_image_is_rejected(self):
        self.stub_analysis(analysis=KNOWN_ANALYSIS)
        response = self.submit(omit=("image",))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(database.list_complaints(db_path=self.db_path), [])

    def test_missing_description_is_rejected(self):
        self.stub_analysis(analysis=KNOWN_ANALYSIS)
        response = self.submit(omit=("description",))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(database.list_complaints(db_path=self.db_path), [])

    def test_blank_description_is_rejected(self):
        self.stub_analysis(analysis=KNOWN_ANALYSIS)
        self.assertEqual(self.submit(description="   ").status_code, 422)

    def test_blank_location_is_rejected(self):
        self.stub_analysis(analysis=KNOWN_ANALYSIS)
        self.assertEqual(self.submit(location="  ").status_code, 422)

    def test_unsupported_image_type_is_rejected(self):
        self.stub_analysis(analysis=KNOWN_ANALYSIS)
        response = self.submit(filename="notes.pdf",
                               content_type="application/pdf",
                               content=b"%PDF-1.4 not an image")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(database.list_complaints(db_path=self.db_path), [])
        self.assertEqual(list(self.upload_dir.iterdir()), [])

    def test_oversized_image_is_rejected(self):
        self.start_client(max_upload_bytes=64)
        self.stub_analysis(analysis=KNOWN_ANALYSIS)
        response = self.submit(content=FAKE_IMAGE_BYTES)   # far bigger than 64 bytes
        self.assertEqual(response.status_code, 413)
        self.assertEqual(database.list_complaints(db_path=self.db_path), [])

    def test_analysis_is_never_reached_for_an_invalid_request(self):
        # No analysis stub here: if the handler called Gemini the network guard
        # would raise, and the 422 below would never come back.
        self.assertEqual(self.submit(location="   ").status_code, 422)


class ListDetailStatusTest(ApiTestCase):
    """GET /api/complaints, GET /api/complaints/{id} and PATCH .../status."""

    def test_list_orders_highest_priority_first(self):
        low = self.seed(description="low", priority_score=10.0,
                        score_breakdown={"band": "Low"})
        high = self.seed(description="high", priority_score=88.0,
                         score_breakdown={"band": "High"})
        rows = self.client.get("/api/complaints").json()
        self.assertEqual([row["id"] for row in rows], [high["id"], low["id"]])
        self.assertEqual([row["priority_band"] for row in rows], ["High", "Low"])

    def test_list_filters_by_status(self):
        self.seed(description="keep")
        self.seed(description="done", status=database.STATUS_RESOLVED)
        rows = self.client.get("/api/complaints",
                               params={"status": database.STATUS_RESOLVED}).json()
        self.assertEqual([row["description"] for row in rows], ["done"])

    def test_list_filters_by_category(self):
        self.seed(description="elec", category="Electrical")
        self.seed(description="clean", category="Cleanliness")
        rows = self.client.get("/api/complaints",
                               params={"category": "Electrical"}).json()
        self.assertEqual([row["description"] for row in rows], ["elec"])

    def test_list_supports_limit_and_offset(self):
        for i in range(5):
            self.seed(description=f"c{i}", priority_score=float((i + 1) * 10))
        rows = self.client.get("/api/complaints",
                               params={"limit": 2, "offset": 2}).json()
        # scores 50,40,30,20,10 -> page 2 of 2 is 30 then 20.
        self.assertEqual([row["description"] for row in rows], ["c2", "c1"])

    def test_list_rejects_an_unknown_sort(self):
        response = self.client.get("/api/complaints", params={"sort": "sideways"})
        self.assertEqual(response.status_code, 422)

    def test_list_rejects_an_unknown_status_filter(self):
        response = self.client.get("/api/complaints", params={"status": "Bogus"})
        self.assertEqual(response.status_code, 422)

    def test_list_rejects_a_negative_limit(self):
        response = self.client.get("/api/complaints", params={"limit": -1})
        self.assertEqual(response.status_code, 422)

    def test_empty_database_returns_an_empty_list(self):
        response = self.client.get("/api/complaints")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_detail_returns_the_complaint(self):
        seeded = self.seed(description="detail me")
        response = self.client.get(f"/api/complaints/{seeded['id']}")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["description"], "detail me")
        self.assertEqual(payload["status"], database.STATUS_REPORTED)

    def test_detail_unknown_id_is_404(self):
        self.assertEqual(self.client.get("/api/complaints/999999").status_code, 404)

    def test_detail_malformed_id_is_422(self):
        for bad in ("not-a-number", "0", "-3"):
            with self.subTest(bad=bad):
                self.assertEqual(self.client.get(f"/api/complaints/{bad}").status_code, 422)

    def test_status_update_moves_a_complaint(self):
        seeded = self.seed()
        response = self.client.patch(
            f"/api/complaints/{seeded['id']}/status",
            json={"status": database.STATUS_IN_PROGRESS},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], database.STATUS_IN_PROGRESS)
        stored = database.get_complaint(seeded["id"], db_path=self.db_path)
        self.assertEqual(stored["status"], database.STATUS_IN_PROGRESS)

    def test_resolving_sets_resolved_at_and_reopening_clears_it(self):
        seeded = self.seed()
        url = f"/api/complaints/{seeded['id']}/status"

        self.client.patch(url, json={"status": database.STATUS_RESOLVED})
        self.assertIsNotNone(
            database.get_complaint(seeded["id"], db_path=self.db_path)["resolved_at"])

        self.client.patch(url, json={"status": database.STATUS_REPORTED})
        self.assertIsNone(
            database.get_complaint(seeded["id"], db_path=self.db_path)["resolved_at"])

    def test_status_update_unknown_id_is_404(self):
        response = self.client.patch("/api/complaints/424242/status",
                                     json={"status": database.STATUS_RESOLVED})
        self.assertEqual(response.status_code, 404)

    def test_status_update_rejects_an_unknown_status(self):
        seeded = self.seed()
        response = self.client.patch(f"/api/complaints/{seeded['id']}/status",
                                     json={"status": "Bogus"})
        self.assertEqual(response.status_code, 422)
        # Nothing was written: the complaint keeps its original status.
        stored = database.get_complaint(seeded["id"], db_path=self.db_path)
        self.assertEqual(stored["status"], database.STATUS_REPORTED)

    def test_status_update_requires_a_body(self):
        seeded = self.seed()
        response = self.client.patch(f"/api/complaints/{seeded['id']}/status", json={})
        self.assertEqual(response.status_code, 422)


class AnalyticsTest(ApiTestCase):
    """GET /api/analytics/summary - the admin dashboard numbers."""

    def test_empty_database_reports_zero_everywhere(self):
        payload = self.client.get("/api/analytics/summary").json()
        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["unscored"], 0)
        self.assertEqual(payload["unresolved"], 0)
        self.assertEqual(payload["by_category"], {})
        self.assertEqual(sum(payload["by_status"].values()), 0)
        for band in ("Critical", "High", "Medium", "Low"):
            with self.subTest(band=band):
                self.assertEqual(payload["by_priority_band"][band], 0)

    def test_counts_cover_status_band_category_and_unscored(self):
        # 1. scored and still open
        scored = self.expected_score(KNOWN_ANALYSIS)
        self.seed(description="scored electrical", category="Electrical",
                  priority_score=scored.score, score_breakdown=scored.breakdown)
        # 2. resolved, never analysed -> unscored
        self.seed(description="never analysed", status=database.STATUS_RESOLVED)
        # 3. scored but from a category we cannot map
        self.seed(description="mystery", category="Hyperdrive Manifold",
                  priority_score=90.0, score_breakdown={"band": "Critical"})
        # 4. open, unscored, no category at all
        self.seed(description="waiting", status=database.STATUS_IN_PROGRESS)

        payload = self.client.get("/api/analytics/summary").json()

        self.assertEqual(payload["total"], 4)
        self.assertEqual(payload["by_status"], {
            database.STATUS_REPORTED: 2,
            database.STATUS_IN_PROGRESS: 1,
            database.STATUS_RESOLVED: 1,
        })
        self.assertEqual(payload["unscored"], 2)
        self.assertEqual(payload["unresolved"], 3)
        self.assertEqual(payload["by_priority_band"]["Critical"], 2)
        # Bands plus unscored must always add up to the total.
        self.assertEqual(sum(payload["by_priority_band"].values())
                         + payload["unscored"], payload["total"])
        self.assertEqual(payload["by_category"], {
            "Electrical": 1,
            "Hyperdrive Manifold": 1,
            "Unclassified": 2,
        })

    def test_band_falls_back_to_priority_thresholds(self):
        # No score_breakdown stored, so the band must come from priority.py.
        self.seed(priority_score=49.0)
        self.seed(priority_score=50.0)
        payload = self.client.get("/api/analytics/summary").json()
        self.assertEqual(payload["by_priority_band"][priority.band_for_score(49.0)], 1)
        self.assertEqual(payload["by_priority_band"][priority.band_for_score(50.0)], 1)

    def test_totals_agree_with_the_list_endpoint(self):
        for i in range(3):
            self.seed(description=f"c{i}", priority_score=float(i * 10))
        payload = self.client.get("/api/analytics/summary").json()
        listed = self.client.get("/api/complaints").json()
        self.assertEqual(payload["total"], len(listed))


class UploadSafetyTest(ApiTestCase):
    """GET /uploads/{filename} may only ever serve files inside uploads/."""

    def submit_and_get_url(self):
        self.stub_analysis(analysis=KNOWN_ANALYSIS)
        return self.submit().json()["image_url"]

    def test_stored_image_is_served_back_byte_for_byte(self):
        response = self.client.get(self.submit_and_get_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, FAKE_IMAGE_BYTES)

    def test_unknown_generated_name_is_404(self):
        self.assertEqual(self.client.get("/uploads/deadbeef.png").status_code, 404)

    def test_non_image_extension_is_404(self):
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        (self.upload_dir / "notes.txt").write_text("private note")
        self.assertEqual(self.client.get("/uploads/notes.txt").status_code, 404)

    def test_literal_and_encoded_traversal_are_404(self):
        for path in (
            "/uploads/../../app/config.py",
            "/uploads/../config.py",
            "/uploads/..%2F..%2Fapp%2Fconfig.py",
            "/uploads/%2e%2e%2fconfig.py",
            "/uploads/....//config.py",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn("GEMINI_API_KEY", response.text)

    def test_a_file_outside_uploads_is_unreachable(self):
        outside = self.tmp_dir / "outside.txt"
        outside.write_text("must never be served")
        for path in (
            "/uploads/..%2Foutside.txt",
            "/uploads/%2e%2e%2foutside.txt",
            "/uploads/..%2F..%2Foutside.txt",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn("must never be served", response.text)


class SecurityTest(ApiTestCase):
    """CORS and error handling."""

    def test_cors_allows_the_local_dev_server(self):
        response = self.client.options(
            "/api/complaints",
            headers={"Origin": "http://localhost:5173",
                     "Access-Control-Request-Method": "POST"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"),
                         "http://localhost:5173")

    def test_cors_refuses_any_other_origin(self):
        response = self.client.options(
            "/api/complaints",
            headers={"Origin": "https://evil.example",
                     "Access-Control-Request-Method": "POST"},
        )
        self.assertIsNone(response.headers.get("access-control-allow-origin"))

    def test_no_wildcard_origin_is_configured(self):
        self.assertNotIn("*", self.app.state.settings.cors_origins)

    def test_unexpected_error_never_leaks_details(self):
        self.start_client(raise_server_exceptions=False)
        boom = "TOP-SECRET internal path C:\\secret\\campuslens.db"
        with mock.patch.object(database, "list_complaints",
                               side_effect=RuntimeError(boom)):
            response = self.client.get("/api/analytics/summary")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn(boom, response.text)
        self.assertNotIn("Traceback", response.text)
        self.assertNotIn("campuslens.db", response.text)


# ---------------------------------------------------------------------------
# Supabase Storage: configured deployments vs. untouched local fallback
# ---------------------------------------------------------------------------

FAKE_SUPABASE_KEY = "service-role-FAKE-key-do-not-use-98765"
SUPABASE_PROJECT = "https://example.supabase.co"
SUPABASE_OVERRIDES = {
    "supabase_url": SUPABASE_PROJECT,
    "supabase_service_role_key": FAKE_SUPABASE_KEY,
    "supabase_bucket": "imagestorage",
}


class SupabaseUploadFlowTest(ApiTestCase):
    """POST /api/complaints with and without Supabase Storage configured.

    setUp() stripped SUPABASE_* from the environment, so "unconfigured"
    here can never be masked by a developer's shell.
    """

    def test_env_absent_keeps_exact_local_behavior(self):
        self.assertFalse(self.app.state.settings.supabase_enabled)
        self.stub_analysis(analysis=KNOWN_ANALYSIS)
        response = self.submit()

        self.assertEqual(response.status_code, 201)
        on_disk = list(self.upload_dir.iterdir())
        self.assertEqual(len(on_disk), 1)  # local file kept, as always
        stored = database.list_complaints(db_path=self.db_path)
        self.assertEqual(stored[0]["image_path"], f"uploads/{on_disk[0].name}")

    def test_configured_upload_moves_bytes_to_bucket_and_removes_local_file(self):
        self.stub_analysis(analysis=KNOWN_ANALYSIS)
        self.start_client(**SUPABASE_OVERRIDES)
        captured = {}

        def fake_upload(settings, data, *, content_type, object_path):
            captured.update(
                settings=settings,
                data=data,
                content_type=content_type,
                object_path=object_path,
            )
            return object_path

        with mock.patch.object(storage, "upload", side_effect=fake_upload) as up:
            response = self.submit()

        self.assertEqual(response.status_code, 201)
        up.assert_called_once()
        payload = response.json()

        # The same object key flows to the bucket, the API and the database.
        object_path = captured["object_path"]
        self.assertRegex(object_path, r"^uploads/[0-9a-f]{32}\.png$")
        self.assertEqual(captured["data"], FAKE_IMAGE_BYTES)
        self.assertEqual(captured["content_type"], "image/png")
        self.assertIs(captured["settings"], self.app.state.settings)
        self.assertEqual(captured["settings"].supabase_bucket, "imagestorage")
        self.assertEqual(payload["image_path"], object_path)
        self.assertEqual(payload["image_url"], f"/{object_path}")
        stored = database.list_complaints(db_path=self.db_path)
        self.assertEqual(stored[0]["image_path"], object_path)

        # The temporary local copy is gone - only the bucket keeps the bytes.
        self.assertEqual(list(self.upload_dir.iterdir()), [])

    def test_configured_upload_failure_is_generic_502_and_keeps_everything(self):
        self.stub_analysis(analysis=KNOWN_ANALYSIS)
        self.start_client(**SUPABASE_OVERRIDES)
        boom = storage.StorageError(f"upload rejected {FAKE_SUPABASE_KEY}")
        with mock.patch.object(storage, "upload", side_effect=boom):
            response = self.submit()

        # Decision: fail the submission, reveal nothing.
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "Image storage unavailable.")
        self.assertNotIn(FAKE_SUPABASE_KEY, response.text)

        # No complaint row pointing at local-only storage...
        self.assertEqual(database.list_complaints(db_path=self.db_path), [])
        # ...and the temporary local image file is kept.
        self.assertEqual(len(list(self.upload_dir.iterdir())), 1)

    def test_storage_failure_even_when_gemini_fails_is_still_502(self):
        # Storage runs regardless of analysis outcome; a storage outage must
        # never produce a row that points at local-only storage.
        self.stub_analysis(
            ok=False, analysis=None, error="down", error_kind="network"
        )
        self.start_client(**SUPABASE_OVERRIDES)
        boom = storage.StorageError("upload rejected")
        with mock.patch.object(storage, "upload", side_effect=boom):
            response = self.submit()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(database.list_complaints(db_path=self.db_path), [])

    def test_gemini_failure_with_storage_configured_still_saves(self):
        self.stub_analysis(
            ok=False, analysis=None, error="down", error_kind="network"
        )
        self.start_client(**SUPABASE_OVERRIDES)

        def fake_upload(settings, data, *, content_type, object_path):
            return object_path

        with mock.patch.object(storage, "upload", side_effect=fake_upload) as up:
            response = self.submit()

        self.assertEqual(response.status_code, 201)
        up.assert_called_once()
        self.assertEqual(len(list(self.upload_dir.iterdir())), 0)


class SupabaseServeTest(ApiTestCase):
    """GET /uploads/{filename} in a configured deployment (private bucket)."""

    NAME = "0123456789abcdef0123456789abcdef.png"
    SIGNED = (
        f"{SUPABASE_PROJECT}/storage/v1/object/sign/imagestorage"
        f"/uploads/{NAME}?token=fake.jwt.token"
    )

    def test_missing_local_file_redirects_to_signed_url(self):
        self.start_client(**SUPABASE_OVERRIDES)
        with mock.patch.object(storage, "signed_url", return_value=self.SIGNED) as sign:
            response = self.client.get(
                f"/uploads/{self.NAME}", follow_redirects=False
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], self.SIGNED)
        sign.assert_called_once_with(
            self.app.state.settings, f"uploads/{self.NAME}"
        )

    def test_signing_failure_is_generic_502(self):
        self.start_client(**SUPABASE_OVERRIDES)
        boom = storage.StorageError(f"cannot sign {FAKE_SUPABASE_KEY}")
        with mock.patch.object(storage, "signed_url", side_effect=boom):
            response = self.client.get(
                f"/uploads/{self.NAME}", follow_redirects=False
            )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "Image storage unavailable.")
        self.assertNotIn(FAKE_SUPABASE_KEY, response.text)
        self.assertNotIn(SUPABASE_PROJECT, response.text)

    def test_legacy_local_file_is_still_served_directly_when_configured(self):
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        (self.upload_dir / self.NAME).write_bytes(b"legacy bytes")
        self.start_client(**SUPABASE_OVERRIDES)
        with mock.patch.object(storage, "signed_url") as sign:
            response = self.client.get(
                f"/uploads/{self.NAME}", follow_redirects=False
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"legacy bytes")
        sign.assert_not_called()  # disk wins; no bucket round-trip

    def test_traversal_and_bad_names_never_reach_storage(self):
        self.start_client(**SUPABASE_OVERRIDES)
        with mock.patch.object(storage, "signed_url") as sign:
            for path in (
                "/uploads/../../app/config.py",
                "/uploads/../config.py",
                "/uploads/..%2F..%2Fapp%2Fconfig.py",
                "/uploads/%2e%2e%2fconfig.py",
                "/uploads/....//config.py",
                "/uploads/notes.txt",
            ):
                with self.subTest(path=path):
                    response = self.client.get(path, follow_redirects=False)
                    self.assertEqual(response.status_code, 404)
        sign.assert_not_called()

    def test_unconfigured_missing_file_is_plain_404_without_signing(self):
        # setUp() stripped SUPABASE_*: the storage branch must not even run.
        with mock.patch.object(storage, "signed_url") as sign:
            response = self.client.get(
                f"/uploads/{self.NAME}", follow_redirects=False
            )
        self.assertEqual(response.status_code, 404)
        sign.assert_not_called()

    def test_unconfigured_traversal_still_404(self):
        with mock.patch.object(storage, "signed_url") as sign:
            response = self.client.get(
                "/uploads/..%2F..%2Fapp%2Fconfig.py", follow_redirects=False
            )
        self.assertEqual(response.status_code, 404)
        sign.assert_not_called()




