"""Queued source-frame extraction, input bounds and safe asset serving."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from autoclip.api import create_app
from autoclip.engine import Settings


class FramePreviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="autoclip-frame-api-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        recordings = root / "recordings"
        recordings.mkdir()
        source = recordings / "synthetic.mp4"
        result = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i",
            "color=c=green:s=320x180:r=10:d=3", "-c:v", "libx264", "-threads", "1", str(source)],
            capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        app = create_app(Settings(root, threads=1), start_worker=False)
        self.client = self.enterContext(TestClient(app, base_url="http://127.0.0.1"))
        self.worker = app.state.service
        self.media = self.worker.import_local(source.name)

    def test_request_only_queues_then_worker_produces_served_jpeg(self):
        with patch("autoclip.service.run_tool", side_effect=AssertionError("decoding in handler")):
            response = self.client.post(f"/media/{self.media['id']}/frames", json={"time": 1})
        self.assertEqual(response.status_code, 202, response.text)
        job = response.json()
        self.assertEqual(job["kind"], "frame_preview")
        self.assertEqual(job["state"], "queued")
        self.assertEqual(self.client.get(f"/jobs/{job['id']}/frame").status_code, 404)
        self.worker.execute(self.worker.store.claim())
        completed = self.client.get(f"/jobs/{job['id']}").json()
        self.assertEqual(completed["state"], "completed", completed["error_message"])
        image = self.client.get(completed["frame_url"])
        self.assertEqual(image.status_code, 200)
        self.assertTrue(image.headers["content-type"].startswith("image/jpeg"))
        decoded = cv2.imdecode(np.frombuffer(image.content, np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape[:2], (180, 320))
        self.assertEqual(self.client.get(f"/jobs/{job['id']}/candidates").json(), [])

    def test_bad_timestamps_unknown_media_and_extra_paths_are_rejected(self):
        for payload in ({"time": -1}, {"time": 3}, {"time": True}, {"time": "1"}, {"time": 1,"path":"../secret"}):
            response = self.client.post(f"/media/{self.media['id']}/frames", json=payload)
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.client.post(f"/media/{'0'*32}/frames",json={"time":0}).status_code,404)
        self.assertEqual(self.worker.store.list_jobs(100,0), [])

    def test_cancelled_job_has_no_asset_and_manifest_cannot_select_arbitrary_file(self):
        response = self.client.post(f"/media/{self.media['id']}/frames",json={"time":0})
        job = response.json()
        self.client.post(f"/jobs/{job['id']}/cancel")
        self.assertEqual(self.client.get(f"/jobs/{job['id']}/frame").status_code,404)
        with self.worker.store.connection() as db:
            db.execute("UPDATE jobs SET state='completed', manifest_json=? WHERE id=?",
                       (json.dumps({"frame_file":"../secret"}),job["id"]))
        self.assertEqual(self.client.get(f"/jobs/{job['id']}/frame").status_code,404)
