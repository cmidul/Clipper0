"""Framing API validation and durable revision options without live servers."""

import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from autoclip.api import create_app
from autoclip.engine import Settings
from autoclip.reframing import FramingSettings


class FramingApiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="autoclip-framing-api-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.app = create_app(Settings(self.root), start_worker=False)
        self.client = self.enterContext(TestClient(self.app, base_url="http://127.0.0.1"))
        self.store = self.app.state.service.store
        self.media_id = "b" * 32
        self.store.add_media(self.media_id, "synthetic.mp4", "synthetic.mp4", "0" * 64,
                             {"duration": 90, "width": 640, "height": 360, "audio_present": False})

    def post_job(self, **options):
        return self.client.post("/jobs", json={"media_id": self.media_id, **options})

    def candidate(self, framing):
        response = self.post_job(framing=framing)
        self.assertEqual(response.status_code, 202, response.text)
        job = self.store.claim()
        self.assertEqual(job["id"], response.json()["id"])
        self.store.finish(job["id"], manifest={"state": "completed", "clips": [{
            "start": 10, "end": 25, "score": 1, "evidence": {}, "file": "mock.mp4",
        }]})
        return self.store.candidates(job["id"])[0]["id"]

    def test_supported_options_persist_and_convert_to_engine_settings(self):
        for framing in (
            {"mode": "full_gameplay", "background": "pad"},
            {"mode": "smart_crop", "focus_point": {"x": 0.8, "y": 0.5}},
            {"mode": "smart_crop", "focus_region": {"x": 0.4, "y": 0.3, "width": 0.1, "height": 0.2}},
            {"mode": "streamer_gameplay", "webcam_region": {"x": 0, "y": 0, "width": 0.2, "height": 0.2}},
            {"mode": "auto"},
        ):
            with self.subTest(framing=framing):
                response = self.post_job(framing=framing)
                self.assertEqual(response.status_code, 202, response.text)
                job = response.json()
                stored = json.loads(self.store.job(job["id"])["request_json"])
                self.assertEqual(stored["framing"], job["options"]["framing"])
                self.assertEqual(FramingSettings.from_dict(stored["framing"]).mode, framing["mode"])
                fetched = self.client.get(f"/jobs/{job['id']}")
                self.assertEqual(fetched.json()["options"]["framing"], stored["framing"])

    def test_malformed_coordinates_and_unimplemented_controls_are_rejected(self):
        for framing in (
            {"mode": "unknown"}, {"focus_point": {"x": 2, "y": 0.5}},
            {"focus_point": {"x": True, "y": 0.5}}, {"focus_point": {"x": "0.5", "y": 0.5}},
            {"focus_point": {"x": 0.5}}, {"focus_point": {"x": 0.5, "y": 0.5, "z": 0}},
            {"webcam_region": {"x": 0.9, "y": 0, "width": 0.2, "height": 0.2}},
            {"focus_region": {"x": 0, "y": 0, "width": 0, "height": 0.2}},
            {"focus_point": {"x": 0.5, "y": 0.5},
             "focus_region": {"x": 0, "y": 0, "width": 1, "height": 1}},
            {"tracking_intensity": 2}, {"emphasis_zoom": "yes"}, {"subtitle_position": "left"},
        ):
            with self.subTest(framing=framing):
                response = self.post_job(framing=framing)
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.store.list_jobs(100, 0), [])

    def test_absent_and_null_options_preserve_unframed_defaults(self):
        for options in ({}, {"framing": None}):
            response = self.post_job(**options)
            self.assertEqual(response.status_code, 202, response.text)
            self.assertNotIn("framing", response.json()["options"])
            self.assertEqual(response.json()["options"]["layout"], "pad")
            self.assertEqual(response.json()["options"]["aspect_ratio"], "9:16")

    def test_revisions_inherit_replace_or_explicitly_disable_framing(self):
        original = {"mode": "smart_crop", "focus_point": {"x": 0.8, "y": 0.5}}
        candidate = self.candidate(original)
        route = f"/candidates/{candidate}/render"
        interval = {"start": 12, "end": 27}
        inherited = self.client.post(route, json=interval)
        self.assertEqual(inherited.status_code, 202, inherited.text)
        self.assertEqual(inherited.json()["options"]["framing"]["focus_point"], original["focus_point"])
        self.assertEqual(inherited.json()["source_candidate_id"], candidate)
        replacement = self.client.post(route, json={**interval, "framing": {"mode": "full_gameplay"}})
        self.assertEqual(replacement.status_code, 202, replacement.text)
        self.assertEqual(replacement.json()["options"]["framing"]["mode"], "full_gameplay")
        self.assertIsNone(replacement.json()["options"]["framing"]["focus_point"])
        disabled = self.client.post(route, json={**interval, "framing": None})
        self.assertEqual(disabled.status_code, 202, disabled.text)
        self.assertNotIn("framing", disabled.json()["options"])
        malformed = self.client.post(route, json={**interval, "framing": {"focus_point": {"x": -1, "y": 0}}})
        self.assertEqual(malformed.status_code, 422)

    def test_split_is_available_for_all_shapes_and_inherited_by_revisions(self):
        split = {"mode": "streamer_gameplay", "webcam_region": {"x": 0, "y": 0, "width": 0.2, "height": 0.2}}
        candidate = self.candidate(split)
        route = f"/candidates/{candidate}/render"
        for ratio in ("9:16", "16:9", "1:1", "4:5"):
            with self.subTest(ratio=ratio):
                initial = self.post_job(framing=split, aspect_ratio=ratio, resolution=480)
                self.assertEqual(initial.status_code, 202, initial.text)
                revised = self.client.post(route, json={"start": 10, "end": 25, "aspect_ratio": ratio})
                self.assertEqual(revised.status_code, 202, revised.text)
                for response in (initial, revised):
                    options = response.json()["options"]
                    self.assertEqual(options["aspect_ratio"], ratio)
                    self.assertEqual(options["framing"]["mode"], "streamer_gameplay")
                    self.assertEqual(options["framing"]["webcam_region"], split["webcam_region"])

    def test_schema_exposes_only_implemented_framing_controls(self):
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        schemas = response.json()["components"]["schemas"]
        fields = schemas["FramingRequest"]["properties"]
        self.assertEqual(set(fields), {"mode", "focus_point", "focus_region", "webcam_region", "background",
            "tracking_intensity", "emphasis_zoom", "subtitle_position", "safe_margin_horizontal",
            "safe_margin_top", "safe_margin_bottom"})
        self.assertIn("framing", schemas["JobRequest"]["properties"])
        self.assertIn("framing", schemas["RenderRequest"]["properties"])


if __name__ == "__main__":
    unittest.main()
