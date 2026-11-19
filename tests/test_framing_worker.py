"""Persisted framing conversion at the durable worker/engine boundary."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from autoclip.engine import Settings
from autoclip.reframing import FocusPoint, FramingSettings
from autoclip.service import Service


class FramingWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="autoclip-framing-worker-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.service = Service(Settings(self.root), self.root / "queue.sqlite3", self.root / "recordings")
        self.media_id = "a" * 32
        self.service.store.add_media(self.media_id, "synthetic.mp4", "synthetic.mp4", "0" * 64,
                                     {"duration": 90, "width": 640, "height": 360, "audio_present": False})

    def enqueue(self, options):
        job = self.service.store.create_job(self.media_id, {"start": 10, "end": 25, **options})
        claimed = self.service.store.claim()
        self.assertEqual(claimed["id"], job["id"])
        return claimed

    def complete(self, source, settings, **options):
        # No real media processing: only a minimal completed manifest is needed
        # to exercise worker conversion and transactional job finalization.
        directory = self.root / "clips" / options["output_id"]
        directory.mkdir(parents=True)
        manifest = directory / "manifest.json"
        manifest.write_text(json.dumps({"state": "completed", "clips": []}), encoding="utf-8")
        return manifest

    def test_valid_json_becomes_records_without_mutating_persisted_options(self):
        job = self.enqueue({"framing": {"mode": "smart_crop", "focus_point": {"x": 0.8, "y": 0.5}}})
        original = job["request_json"]
        with patch("autoclip.service.process", side_effect=self.complete) as engine:
            self.service.execute(job)
        engine.assert_called_once()
        framing = engine.call_args.kwargs["framing"]
        self.assertIsInstance(framing, FramingSettings)
        self.assertEqual(framing.focus_point, FocusPoint(0.8, 0.5))
        self.assertEqual(engine.call_args.kwargs["output_id"], job["id"])
        self.assertTrue(callable(engine.call_args.kwargs["cancelled"]))
        self.assertTrue(callable(engine.call_args.kwargs["progress_callback"]))
        stored = self.service.store.job(job["id"])
        self.assertEqual(stored["request_json"], original)
        self.assertEqual(stored["state"], "completed")

    def test_absent_and_null_settings_keep_legacy_engine_options(self):
        for options in ({}, {"framing": None}):
            with self.subTest(options=options):
                job = self.enqueue(options)
                with patch("autoclip.service.process", side_effect=self.complete) as engine:
                    self.service.execute(job)
                if "framing" in options:
                    self.assertIsNone(engine.call_args.kwargs["framing"])
                else:
                    self.assertNotIn("framing", engine.call_args.kwargs)
                self.assertEqual(self.service.store.job(job["id"])["state"], "completed")

    def test_invalid_stored_settings_fail_before_engine_execution(self):
        for framing in ({"unexpected": True}, {"focus_point": {"x": 2, "y": 0.5}}, ["auto"]):
            with self.subTest(framing=framing):
                job = self.enqueue({"framing": framing})
                with patch("autoclip.service.process") as engine, self.assertLogs("autoclip.service", level="ERROR"):
                    self.service.execute(job)
                engine.assert_not_called()
                stored = self.service.store.job(job["id"])
                self.assertEqual(stored["state"], "failed")
                self.assertEqual(stored["error_code"], "processing_failed")
                self.assertTrue(stored["error_message"])
                self.assertEqual(self.service.store.candidates(job["id"]), [])

    def test_failed_conversion_does_not_prevent_next_job_execution(self):
        bad = self.enqueue({"framing": {"tracking_intensity": -1}})
        with self.assertLogs("autoclip.service", level="ERROR"):
            self.service.execute(bad)
        good = self.enqueue({"framing": {"mode": "full_gameplay"}})
        with patch("autoclip.service.process", side_effect=self.complete):
            self.service.execute(good)
        self.assertEqual(self.service.store.job(bad["id"])["state"], "failed")
        self.assertEqual(self.service.store.job(good["id"])["state"], "completed")


if __name__ == "__main__":
    unittest.main()
