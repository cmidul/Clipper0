"""Real upload, durable processing, revision and restart checks."""

import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from autoclip.api import create_app
from autoclip.engine import Settings, run_tool


class BackendIntegrationTests(unittest.TestCase):
    def wait_for_job(self, client, job_id):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            response = client.get(f"/jobs/{job_id}")
            self.assertEqual(response.status_code, 200, response.text)
            job = response.json()
            if job["state"] in {"completed", "failed", "cancelled"}:
                return job
            time.sleep(0.02)
        self.fail("Job did not reach a terminal state within 60 seconds")

    def test_real_upload_render_review_revision_and_restart(self):
        root = Path("local-data/test-runs").resolve()
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="api-integration-", dir=root) as directory:
            folder = Path(directory)
            source = folder / "authorized synthetic sample.mp4"
            run_tool([
                "ffmpeg", "-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i",
                "color=c=navy:size=320x180:rate=15:duration=20", "-c:v", "libx264",
                "-threads", "2", str(source),
            ])
            settings = Settings(folder / "data", threads=2)
            environment = {"AUTOCLIP_DB_PATH": str(folder / "queue.sqlite3"),
                           "AUTOCLIP_RECORDINGS_DIR": str(folder / "recordings")}
            with patch.dict(os.environ, environment):
                with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
                    self.assertEqual(client.get("/health").status_code, 200)
                    invalid = client.post("/media/import?filename=fake.mp4", content=b"invalid media")
                    self.assertEqual(invalid.status_code, 400)
                    upload = client.post("/media/import", params={"filename": source.name}, content=source.read_bytes())
                    self.assertEqual(upload.status_code, 201, upload.text)
                    media = upload.json()
                    self.assertFalse(media["audio_present"])
                    initial = client.post("/jobs", json={"media_id": media["id"], "start": 0, "end": 15, "captions": True})
                    self.assertEqual(initial.status_code, 202, initial.text)
                    job_id = initial.json()["id"]
                    finished = self.wait_for_job(client, job_id)
                    self.assertEqual(finished["state"], "completed", finished)
                    self.assertEqual(finished["progress_pct"], 100)
                    self.assertEqual(finished["caption_status"], "no_speech")
                    candidate = client.get(f"/jobs/{job_id}/candidates").json()[0]
                    downloaded = client.get(candidate["download_url"])
                    self.assertEqual(downloaded.status_code, 200)
                    output = folder / "downloaded.mp4"
                    output.write_bytes(downloaded.content)
                    run_tool(["ffmpeg", "-nostdin", "-v", "error", "-i", str(output), "-f", "null", "-"])
                    client.patch(f"/candidates/{candidate['id']}", json={"review_state": "approved"})
                    revised = client.post(f"/candidates/{candidate['id']}/render", json={"start": 2, "end": 17, "layout_mode": "crop"})
                    self.assertEqual(revised.status_code, 202, revised.text)
                    revision_job = self.wait_for_job(client, revised.json()["id"])
                    self.assertEqual(revision_job["state"], "completed", revision_job)
                    revision = client.get(f"/jobs/{revision_job['id']}/candidates").json()[0]
                    self.assertEqual(revision["source_candidate_id"], candidate["id"])
                    self.assertEqual(revision["start"], 2)
                    self.assertEqual(revision["end"], 17)
                    self.assertEqual(client.get(candidate["download_url"]).status_code, 200)
                with TestClient(create_app(settings), base_url="http://127.0.0.1") as restarted:
                    self.assertEqual(restarted.get(f"/jobs/{job_id}").json()["state"], "completed")
                    persisted = restarted.get(f"/jobs/{job_id}/candidates").json()[0]
                    self.assertEqual(persisted["review_state"], "approved")
                    self.assertEqual(restarted.get(persisted["preview_url"]).status_code, 200)

    def test_missing_encoder_binary_becomes_a_failed_job(self):
        root = Path("local-data/test-runs").resolve()
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="api-failure-", dir=root) as directory:
            folder = Path(directory)
            source = folder / "sample.mp4"
            run_tool(["ffmpeg", "-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i",
                      "color=c=black:size=160x90:duration=16", "-c:v", "libx264", "-threads", "2", str(source)])
            settings = Settings(folder / "data", ffmpeg="autoclip-missing-ffmpeg-9621")
            with patch.dict(os.environ, {"AUTOCLIP_DB_PATH": str(folder / "queue.sqlite3")}):
                with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
                    self.assertEqual(client.get("/health").status_code, 503)
                    media = client.post("/media/import?filename=sample.mp4", content=source.read_bytes()).json()
                    with self.assertLogs("autoclip.service", level="ERROR"):
                        job = client.post("/jobs", json={"media_id": media["id"], "start": 0, "end": 15}).json()
                        failed = self.wait_for_job(client, job["id"])
                    self.assertEqual(failed["state"], "failed")
                    self.assertIn("Missing executable", failed["error_message"])
                    self.assertEqual(client.get(f"/jobs/{job['id']}/candidates").json(), [])


if __name__ == "__main__":
    unittest.main()
