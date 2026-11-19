"""Managed parent transcript reuse, including an actual framed revision."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from autoclip.engine import ClipError, Settings
from autoclip.service import Service


class RevisionReuseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="autoclip-revision-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.service = Service(Settings(self.root, threads=2), self.root / "db.sqlite3", self.root / "recordings")
        self.media = self.service.store.add_media("a" * 32, "source.mp4", "source.mp4", "b" * 64,
                                                 {"duration": 30, "audio_present": True})
        parent = self.service.store.create_job(self.media["id"], {"captions": True, "framing": {"mode": "full_gameplay"}})
        self.service.store.claim()
        self.parent_dir = self.root / "clips" / parent["id"]
        self.parent_dir.mkdir(parents=True)
        self.payload = {"schema_version": 1, "fingerprint": {"media_sha256": "b" * 64, "language": None},
                        "language": "en", "segments": [{"start": 2, "end": 4, "text": "reuse me"}]}
        (self.parent_dir / "transcript.json").write_text(json.dumps(self.payload), encoding="utf-8")
        self.service.store.finish(parent["id"], manifest={"state": "completed", "transcript_file": "transcript.json",
            "clips": [{"start": 0, "end": 15, "score": 1, "evidence": {}, "file": "mock.mp4"}]})
        candidate = self.service.store.candidates(parent["id"])[0]
        self.options = {"start": 1, "end": 16, "captions": True, "framing": {"mode": "full_gameplay"}}
        self.job = self.service.store.create_job(self.media["id"], self.options, candidate["id"])

    def test_parent_transcript_reused_and_disable_revision_also_reuses(self):
        result = self.service.revision_transcript(self.job, self.media, self.options)
        self.assertEqual(result["reuse_kind"], "saved_job")
        disabled = {**self.options, "framing": None}
        self.assertEqual(self.service.revision_transcript(self.job, self.media, disabled)["segments"], self.payload["segments"])

    def test_missing_corrupt_and_source_mismatch_fail_explicitly(self):
        asset = self.parent_dir / "transcript.json"
        for content in ("not json", json.dumps({**self.payload, "fingerprint": {"media_sha256": "c" * 64}})):
            asset.write_text(content, encoding="utf-8")
            with self.assertRaises(ClipError):
                self.service.revision_transcript(self.job, self.media, self.options)
        asset.unlink()
        with self.assertRaises(ClipError):
            self.service.revision_transcript(self.job, self.media, self.options)

    def test_parent_media_association_and_language_are_checked(self):
        with self.assertRaises(ClipError):
            self.service.revision_transcript(self.job, {**self.media, "id": "c" * 32}, self.options)
        with self.assertRaises(ClipError):
            self.service.revision_transcript(self.job, self.media, {**self.options, "language": "bn"})

    def test_no_audio_or_disabled_speech_uses_existing_path(self):
        self.assertIsNone(self.service.revision_transcript(self.job, self.media, {**self.options, "captions": False}))
        silent = {**self.media, "metadata_json": json.dumps({"duration": 30, "audio_present": False})}
        self.assertIsNone(self.service.revision_transcript(self.job, silent, self.options))

    def test_actual_worker_revision_keeps_captions_without_inference(self):
        recordings = self.root / "real-recordings"
        recordings.mkdir()
        source = recordings / "owned synthetic.mp4"
        result = subprocess.run([shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-nostdin", "-n",
            "-f", "lavfi", "-i", "color=c=gray:s=320x180:r=10:d=20",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=20", "-c:v", "libx264",
            "-preset", "ultrafast", "-threads", "2", "-c:a", "aac", "-shortest", str(source)],
            capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        worker = Service(Settings(self.root / "real", threads=2), self.root / "real/db.sqlite3", recordings)
        media = worker.import_local(source.name)
        saved = {**self.payload, "fingerprint": {"media_sha256": media["sha256"], "language": None}}
        first = worker.store.create_job(media["id"], {"start": 0, "end": 15, "captions": True,
                                                     "framing": {"mode": "full_gameplay", "background": "pad"}})
        with patch("autoclip.speech.transcribe_media", return_value=saved):
            worker.execute(worker.store.claim())
        self.assertEqual(worker.store.job(first["id"])["state"], "completed")
        candidate = worker.store.candidates(first["id"])[0]
        revision = worker.store.create_job(media["id"], {"start": 1, "end": 16, "captions": True,
            "framing": {"mode": "smart_crop", "focus_point": {"x": 0.5, "y": 0.5}}}, candidate["id"])
        with patch("autoclip.speech.transcribe_media", side_effect=AssertionError("repeated inference")), \
                patch("autoclip.engine.select_candidates", side_effect=AssertionError("repeated selection")):
            worker.execute(worker.store.claim())
        final = worker.store.job(revision["id"])
        self.assertEqual(final["state"], "completed", final["error_message"])
        manifest = json.loads(final["manifest_json"])
        self.assertEqual(manifest["transcript_reuse_kind"], "saved_job")
        output = self.root / "real/clips" / revision["id"] / manifest["clips"][0]["file"]
        self.assertTrue(output.is_file())
        srt = output.with_suffix(".srt").read_text(encoding="utf-8")
        self.assertIn("00:00:01,000 --> 00:00:03,000", srt)
