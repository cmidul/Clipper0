from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from autoclip.api import create_app
from autoclip.engine import ClipError, JobCancelled, Media, Settings, processing_control, run_tool
from autoclip.service import Service
from autoclip.store import Store


def completed_manifest():
    return {"state": "completed", "clips": [
        {"start": 0, "end": 15, "score": 0.6, "evidence": {"audio_peak": 1},
         "file": "clip-01.mp4", "subtitle_file": None, "srt_file": None},
    ]}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = Store(self.root / "queue.sqlite3")
        self.store.add_media("media", "recording.mp4", "media.mp4", "hash", {"duration": 90})

    def test_concurrent_claims_are_unique(self):
        for _ in range(8):
            self.store.create_job("media", {})
        with ThreadPoolExecutor(max_workers=4) as executor:
            claimed = list(executor.map(lambda _: self.store.claim(), range(8)))
        self.assertEqual(len({job["id"] for job in claimed}), 8)
        self.assertIsNone(self.store.claim())

    def test_recovery_preserves_queue_and_marks_running_interrupted(self):
        running = self.store.create_job("media", {})
        self.store.claim()
        queued = self.store.create_job("media", {})
        reopened = Store(self.root / "queue.sqlite3")
        reopened.recover()
        self.assertEqual(reopened.job(running["id"])["state"], "failed")
        self.assertEqual(reopened.job(running["id"])["error_code"], "server_interrupted")
        self.assertEqual(reopened.job(queued["id"])["state"], "queued")

    def test_cancellation_wins_race_with_result_publication(self):
        job = self.store.create_job("media", {})
        self.store.claim()
        self.store.cancel(job["id"])
        self.store.finish(job["id"], manifest=completed_manifest())
        self.assertEqual(self.store.job(job["id"])["state"], "cancelled")
        self.assertEqual(self.store.candidates(job["id"]), [])

    def test_result_publication_is_atomic_and_retry_safe(self):
        job = self.store.create_job("media", {})
        self.store.claim()
        self.store.finish(job["id"], manifest=completed_manifest())
        self.store.finish(job["id"], manifest=completed_manifest())
        self.assertEqual(len(self.store.candidates(job["id"])), 1)
        self.assertEqual(self.store.job(job["id"])["progress_pct"], 100)
        self.assertEqual(self.store.cancel(job["id"])["state"], "completed")

    def test_progress_is_monotonic_and_running_progress_stays_below_completion(self):
        job = self.store.create_job("media", {})
        self.store.claim()
        for progress in (75, 20, 100):
            self.store.update_progress(job["id"], {"phase": "rendering", "progress_pct": progress})
        self.assertEqual(self.store.job(job["id"])["progress_pct"], 99)

    def test_partial_result_failure_rolls_back_all_candidate_rows(self):
        job = self.store.create_job("media", {})
        self.store.claim()
        manifest = completed_manifest()
        manifest["clips"].append({"file": "broken.mp4"})
        with self.assertRaises(KeyError):
            self.store.finish(job["id"], manifest=manifest)
        self.assertEqual(self.store.candidates(job["id"]), [])
        self.assertEqual(self.store.job(job["id"])["state"], "running")

    def test_restart_respects_an_outstanding_cancellation(self):
        job = self.store.create_job("media", {})
        self.store.claim()
        self.store.cancel(job["id"])
        self.store.recover()
        self.assertEqual(self.store.job(job["id"])["state"], "cancelled")


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {
            "AUTOCLIP_DB_PATH": str(self.root / "queue.sqlite3"),
            "AUTOCLIP_RECORDINGS_DIR": str(self.root / "recordings"),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.settings = Settings(self.root, max_bytes=32)
        self.app = create_app(self.settings, start_worker=False)
        self.client = TestClient(self.app, base_url="http://127.0.0.1")
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def imported(self):
        media = Media(self.root / "ignored.mp4", 90, 1920, 1080, "h264", True, 9)
        with patch("autoclip.service.inspect_media", return_value=media):
            response = self.client.post("/media/import", params={"filename": "sample space বাংলা.mp4"}, content=b"recording")
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def finished(self):
        media = self.imported()
        response = self.client.post("/jobs", json={"media_id": media["id"]})
        job_id = response.json()["id"]
        self.app.state.service.store.claim()
        self.app.state.service.store.finish(job_id, manifest=completed_manifest())
        candidate = self.client.get(f"/jobs/{job_id}/candidates").json()[0]
        path = self.root / "clips" / job_id / "clip-01.mp4"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"0123456789")
        return job_id, candidate

    def test_upload_is_managed_and_returns_no_internal_path(self):
        media = self.imported()
        self.assertEqual(media["filename"], "sample space বাংলা.mp4")
        self.assertNotIn("path", media)
        stored = self.app.state.service.store.media(media["id"])
        self.assertEqual((self.root / "imports" / stored["stored_name"]).read_bytes(), b"recording")
        self.assertEqual(len(self.client.get("/media").json()), 1)

    def test_empty_bad_and_oversized_uploads_clean_staging(self):
        self.assertEqual(self.client.post("/media/import?filename=empty.mp4", content=b"").status_code, 400)
        self.assertEqual(self.client.post("/media/import?filename=bad.txt", content=b"bad").status_code, 400)
        self.assertEqual(self.client.post("/media/import?filename=big.mp4", content=b"x" * 33).status_code, 413)
        chunks = iter([b"x" * 20, b"x" * 20])
        self.assertEqual(self.client.post("/media/import?filename=chunked.mp4", content=chunks).status_code, 413)
        self.assertFalse(list((self.root / "imports").glob("*.partial*")))
        self.assertEqual(self.client.get("/media").json(), [])

    def test_local_import_rejects_arbitrary_paths_and_copies_staged_file(self):
        for filename in ("../sample.mp4", "C:\\private.mp4", "subdir/sample.mp4"):
            response = self.client.post("/media/import-local", json={"filename": filename})
            self.assertEqual(response.status_code, 400)
        recordings = self.root / "recordings"
        recordings.mkdir()
        original = recordings / "sample.mp4"
        original.write_bytes(b"original")
        media = Media(original, 90, 100, 100, "h264", False, 8)
        with patch("autoclip.service.inspect_media", return_value=media):
            response = self.client.post("/media/import-local", json={"filename": "sample.mp4"})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(original.read_bytes(), b"original")

    def test_validation_and_queued_cancellation(self):
        media = self.imported()
        for options in ({"max_clips": 11}, {"start": 1}, {"start": 0, "end": 5},
                        {"start": 80, "end": 100}, {"path": "private"}, {"max_clips": True}):
            response = self.client.post("/jobs", json={"media_id": media["id"], **options})
            self.assertEqual(response.status_code, 422, response.text)
        job = self.client.post("/jobs", json={"media_id": media["id"]}).json()
        self.assertEqual(self.client.post(f"/jobs/{job['id']}/cancel").json()["state"], "cancelled")
        self.assertEqual(self.client.post(f"/jobs/{job['id']}/cancel").json()["state"], "cancelled")
        self.assertIsNone(self.app.state.service.store.claim())

    def test_origin_host_and_unknown_ids_are_rejected(self):
        self.assertEqual(self.client.get("/jobs", headers={"Origin": "https://example.com"}).status_code, 403)
        self.assertEqual(self.client.get("/jobs", headers={"Host": "example.com"}).status_code, 400)
        self.assertEqual(self.client.get("/jobs/missing").status_code, 404)
        response = self.client.get("/jobs", headers={"Origin": "http://127.0.0.1:3000"})
        self.assertEqual(response.headers["access-control-allow-origin"], "http://127.0.0.1:3000")

    def test_preview_ranges_download_review_and_queued_revision(self):
        job_id, candidate = self.finished()
        clip_id = candidate["clip_id"]
        response = self.client.get(f"/clips/{clip_id}/preview", headers={"Range": "bytes=0-3"})
        self.assertEqual(response.status_code, 206, response.text)
        self.assertEqual(response.content, b"0123")
        self.assertIn("attachment", self.client.get(f"/clips/{clip_id}/download").headers["content-disposition"])
        self.assertEqual(self.client.get(f"/clips/{clip_id}/subtitles").status_code, 404)
        review = self.client.patch(f"/candidates/{candidate['id']}", json={"review_state": "approved"})
        self.assertEqual(review.json()["review_state"], "approved")
        for end in (5, 100):
            self.assertEqual(self.client.post(f"/candidates/{candidate['id']}/render", json={"start": 0, "end": end}).status_code, 422)
        revision = self.client.post(f"/candidates/{candidate['id']}/render", json={"start": 10, "end": 30, "layout_mode": "crop"})
        self.assertEqual(revision.status_code, 202, revision.text)
        self.assertEqual(revision.json()["source_candidate_id"], candidate["id"])
        self.assertEqual(revision.json()["options"]["layout"], "crop")
        self.assertEqual(self.client.get(f"/jobs/{job_id}").json()["state"], "completed")

    def test_tampered_asset_path_cannot_escape_storage(self):
        _, candidate = self.finished()
        secret = self.root.parent / "outside-secret.mp4"
        with self.app.state.service.store.connection() as db:
            db.execute("UPDATE clips SET path=? WHERE id=?", (str(secret), candidate["clip_id"]))
        self.assertEqual(self.client.get(f"/clips/{candidate['clip_id']}/preview").status_code, 400)

    def test_second_server_cannot_recover_an_active_servers_jobs(self):
        with self.assertRaises(ClipError):
            with TestClient(create_app(self.settings), base_url="http://127.0.0.1"):
                self.fail("Second server acquired the ownership lock")


class WorkerTests(unittest.TestCase):
    def test_worker_health_recovers_after_a_transient_database_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = Service(Settings(root), root / "queue.sqlite3", root / "recordings")
            real_claim = service.store.claim
            attempts = 0
            retry_started = threading.Event()
            release_retry = threading.Event()

            def flaky_claim():
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise sqlite3.OperationalError("temporary busy database")
                if attempts == 2:
                    retry_started.set()
                    if not release_retry.wait(5):
                        raise AssertionError("Recovery retry was not released")
                return real_claim()

            with patch.object(service.store, "claim", side_effect=flaky_claim):
                service.start()
                try:
                    self.assertTrue(retry_started.wait(5), "Worker did not retry the database claim")
                    self.assertEqual(service.worker_error, "temporary busy database")
                    release_retry.set()
                    deadline = time.monotonic() + 3
                    while service.worker_error is not None and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertGreaterEqual(attempts, 2)
                    self.assertIsNone(service.worker_error)
                    self.assertTrue(service.thread.is_alive())
                finally:
                    release_retry.set()
                    service.stop()

    def test_single_worker_cancels_and_continues_with_next_job(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = Service(Settings(root), root / "queue.sqlite3", root / "recordings")
            service.store.add_media("media", "sample.mp4", "sample.mp4", "hash", {"duration": 90})
            first = service.store.create_job("media", {})
            second = service.store.create_job("media", {})
            entered = threading.Event()
            active = 0
            maximum_active = 0

            def fake_process(source, settings, *, output_id, cancelled, progress_callback):
                nonlocal active, maximum_active
                active += 1
                maximum_active = max(maximum_active, active)
                try:
                    progress_callback({"phase": "rendering", "progress_pct": 75})
                    if output_id == first["id"]:
                        entered.set()
                        deadline = time.monotonic() + 5
                        while time.monotonic() < deadline:
                            if cancelled():
                                raise JobCancelled()
                            time.sleep(0.01)
                        raise AssertionError("Cancellation was never observed")
                    folder = root / "clips" / output_id
                    folder.mkdir(parents=True)
                    (folder / "clip-01.mp4").write_bytes(b"test")
                    path = folder / "manifest.json"
                    path.write_text(json.dumps(completed_manifest()), encoding="utf-8")
                    return path
                finally:
                    active -= 1

            with patch("autoclip.service.process", side_effect=fake_process):
                service.start()
                try:
                    self.assertTrue(entered.wait(5))
                    service.store.cancel(first["id"])
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline and service.store.job(second["id"])["state"] != "completed":
                        time.sleep(0.01)
                    self.assertEqual(service.store.job(first["id"])["state"], "cancelled")
                    self.assertEqual(service.store.job(second["id"])["state"], "completed")
                    self.assertEqual(maximum_active, 1)
                finally:
                    service.stop()

    def test_child_process_is_killed_on_cooperative_cancellation(self):
        event = threading.Event()
        timer = threading.Timer(0.3, event.set)
        timer.start()
        started = time.monotonic()
        try:
            with processing_control(event.is_set, None), self.assertRaises(JobCancelled):
                run_tool([sys.executable, "-c", "import time; time.sleep(30)"])
        finally:
            timer.cancel()
        self.assertLess(time.monotonic() - started, 3)

    def test_child_timeout_remains_a_friendly_error(self):
        started = time.monotonic()
        with self.assertRaisesRegex(ClipError, "time limit"):
            run_tool([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.05)
        self.assertLess(time.monotonic() - started, 3)


if __name__ == "__main__":
    unittest.main()
