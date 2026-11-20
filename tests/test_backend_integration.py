"""Real upload, durable processing, revision and restart checks."""

import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np
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

    def test_ranked_clip_spatial_revision_matches_still_and_persists(self):
        with tempfile.TemporaryDirectory(prefix="autoclip-spatial-beta-") as directory:
            root = Path(directory)
            source = root / "disposable.mp4"
            run_tool(["ffmpeg", "-nostdin", "-v", "error", "-n",
                      "-f", "lavfi", "-i", "color=gray:s=320x180:r=10:d=20",
                      "-f", "lavfi", "-i", "sine=f=440:r=48000:d=20",
                      "-vf", "drawbox=x=288:y=0:w=32:h=180:color=blue:t=fill",
                      "-af", "volume=0:enable='lt(t,8)+gte(t,9)'",
                      "-c:v", "libx264", "-threads", "1", "-c:a", "aac", str(source)])
            settings = Settings(root / "data", threads=1)
            with patch.dict(os.environ, {"AUTOCLIP_DB_PATH": str(root / "queue.sqlite3")}):
                with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
                    upload = client.post("/media/import?filename=disposable.mp4", content=source.read_bytes())
                    self.assertEqual(upload.status_code, 201, upload.text)
                    media_id = upload.json()["id"]
                    initial = client.post("/jobs", json={"media_id": media_id, "max_clips": 1,
                        "clip_length": 15, "resolution": 480, "framing": {"mode": "full_gameplay", "background": "pad"}})
                    self.assertEqual(initial.status_code, 202, initial.text)
                    first_job = self.wait_for_job(client, initial.json()["id"])
                    self.assertEqual(first_job["state"], "completed", first_job)
                    [first] = client.get(f"/jobs/{first_job['id']}/candidates").json()
                    interval = {key: first[key] for key in ("start", "end")}
                    framing = {"mode": "focus_crop", "focus_point": {"x": 1, "y": 0.5},
                               "auto_focus": False, "foreground_zoom": 1.5}
                    response = client.post(f"/media/{media_id}/frames", json={"time": first["start"] + 1,
                        "composition": {**interval, "framing": framing, "aspect_ratio": "9:16", "resolution": 480}})
                    self.assertEqual(response.status_code, 202, response.text)
                    preview = self.wait_for_job(client, response.json()["id"])
                    self.assertEqual(preview["state"], "completed", preview)
                    self.assertEqual(preview["frame_framing_mode"], "focus_crop")
                    image = client.get(preview["frame_url"])
                    self.assertEqual(image.status_code, 200)
                    still = cv2.imdecode(np.frombuffer(image.content, np.uint8), cv2.IMREAD_COLOR)
                    self.assertEqual(still.shape[:2], (854, 480))

                    response = client.post(f"/candidates/{first['id']}/render", json={**interval, "framing": framing})
                    self.assertEqual(response.status_code, 202, response.text)
                    revised_job = self.wait_for_job(client, response.json()["id"])
                    self.assertEqual(revised_job["state"], "completed", revised_job)
                    [revised] = client.get(f"/jobs/{revised_job['id']}/candidates").json()
                    self.assertEqual(revised["source_candidate_id"], first["id"])
                    self.assertEqual(client.get(revised["preview_url"], headers={"Range": "bytes=0-15"}).status_code, 206)
                    for name, candidate in (("full", first), ("focus", revised)):
                        download = client.get(candidate["download_url"])
                        self.assertEqual(download.status_code, 200)
                        (root / f"{name}.mp4").write_bytes(download.content)

                focus = root / "focus.mp4"
                probe = json.loads(run_tool(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(focus)]))
                video, audio = probe["streams"]
                self.assertEqual((video["codec_name"], video["width"], video["height"]), ("h264", 480, 854))
                self.assertEqual(video["sample_aspect_ratio"], "1:1")
                self.assertEqual(video["display_aspect_ratio"], "240:427")  # 9:16 rounded to even dimensions.
                self.assertEqual(audio["codec_name"], "aac")
                self.assertAlmostEqual(float(video["start_time"]), float(audio["start_time"]), delta=0.05)
                self.assertAlmostEqual(float(video["duration"]), 15, delta=0.1)
                self.assertAlmostEqual(float(video["duration"]), float(audio["duration"]), delta=0.1)
                frames = {}
                for name in ("full", "focus"):
                    run_tool(["ffmpeg", "-nostdin", "-v", "error", "-ss", "1", "-i", str(root / f"{name}.mp4"),
                              "-frames:v", "1", "-threads", "1", str(root / f"{name}.png")])
                    frames[name] = cv2.imread(str(root / f"{name}.png"))
                self.assertLess(int(frames["full"][200, 410, 0]), 20)
                self.assertGreater(int(frames["focus"][200, 410, 0]), 150)
                difference = np.abs(still.astype(np.int16) - frames["focus"].astype(np.int16))
                self.assertLess(float(difference.mean()), 5)
                with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
                    reopened = client.get(f"/jobs/{revised_job['id']}").json()
                    self.assertEqual(reopened["options"]["framing"]["foreground_zoom"], 1.5)
                    self.assertEqual(client.get(f"/media/{media_id}").status_code, 200)

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
