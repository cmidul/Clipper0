"""Saved-transcript revision validation without model loading or inference."""

import copy
import math
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from autoclip.engine import ClipError, Media, Settings, process
from autoclip.reframing import FramingSettings
from autoclip.speech import validate_saved_transcript


class SavedTranscriptTests(unittest.TestCase):
    source_hash = "a" * 64

    def payload(self):
        return {"schema_version": 1, "fingerprint": {"media_sha256": self.source_hash, "language": None},
                "language": "en", "segments": [{"start": 1, "end": 3, "text": "Saved speech"}],
                "cache_hit": False}

    def test_matching_transcript_is_marked_reused(self):
        result = validate_saved_transcript(self.payload(), self.source_hash, 10)
        self.assertTrue(result["cache_hit"])
        self.assertEqual(result["reuse_kind"], "saved_job")
        self.assertEqual(result["segments"][0]["text"], "Saved speech")
        self.assertEqual(result["language"], "en")

    def test_empty_transcript_is_valid_without_speech(self):
        payload = self.payload()
        payload.update(segments=[], language=None)
        result = validate_saved_transcript(payload, self.source_hash, 10)
        self.assertEqual(result["segments"], [])
        self.assertIsNone(result["language"])
        self.assertTrue(result["cache_hit"])

    def test_source_and_requested_language_must_match(self):
        payload = self.payload()
        with self.assertRaisesRegex(ClipError, "imported recording"):
            validate_saved_transcript(payload, "b" * 64, 10)
        with self.assertRaisesRegex(ClipError, "language settings"):
            validate_saved_transcript(payload, self.source_hash, 10, language="en")
        payload["fingerprint"]["language"] = "en"
        self.assertTrue(validate_saved_transcript(payload, self.source_hash, 10, language="en")["cache_hit"])
        with self.assertRaisesRegex(ClipError, "language settings"):
            validate_saved_transcript(payload, self.source_hash, 10)

    def test_invalid_schema_identity_and_language_metadata_are_rejected(self):
        cases = [None, [], {}, {**self.payload(), "schema_version": True},
                 {**self.payload(), "schema_version": 2}, {**self.payload(), "fingerprint": []},
                 {**self.payload(), "fingerprint": {"media_sha256": self.source_hash}},
                 {**self.payload(), "language": "invalid-language"},
                 {**self.payload(), "language": True}]
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(ClipError):
                validate_saved_transcript(payload, self.source_hash, 10)

    def test_malformed_or_out_of_bounds_segments_are_rejected(self):
        for segments in (None, {}, [None], [{"start": 1, "end": 2, "text": 42}],
                         [{"start": True, "end": 2, "text": "x"}],
                         [{"start": "1", "end": 2, "text": "x"}],
                         [{"start": math.nan, "end": 2, "text": "x"}],
                         [{"start": 1, "end": math.inf, "text": "x"}],
                         [{"start": -1, "end": 2, "text": "x"}],
                         [{"start": 1, "end": 11, "text": "x"}],
                         [{"start": 2, "end": 2, "text": "x"}]):
            payload = self.payload()
            payload["segments"] = segments
            with self.subTest(segments=segments), self.assertRaises(ClipError):
                validate_saved_transcript(payload, self.source_hash, 10)

    def test_normalization_does_not_mutate_saved_data(self):
        payload = self.payload()
        payload["segments"] = [{"start": 2, "end": 4, "text": " second  phrase "},
                               {"start": 1, "end": 3, "text": " first phrase "}]
        original = copy.deepcopy(payload)
        result = validate_saved_transcript(payload, self.source_hash, 10)
        self.assertEqual(payload, original)
        self.assertEqual(result["segments"], [
            {"start": 1, "end": 3, "text": "first phrase"},
            {"start": 3, "end": 4, "text": "second phrase"},
        ])
        self.assertIsNot(result, payload)
        self.assertIsNot(result["fingerprint"], payload["fingerprint"])
        self.assertIsNot(result["segments"], payload["segments"])

    def test_invalid_expected_identity_duration_and_language_are_rejected(self):
        for source_hash, duration, language in (
            ("short", 10, "auto"), (None, 10, "auto"),
            (self.source_hash, 0, "auto"), (self.source_hash, True, "auto"),
            (self.source_hash, math.inf, "auto"), (self.source_hash, 10, "english"),
            (self.source_hash, 10, None),
        ):
            with self.subTest(source_hash=source_hash, duration=duration, language=language), self.assertRaises(ClipError):
                validate_saved_transcript(self.payload(), source_hash, duration, language=language)


class SavedTranscriptEngineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="autoclip-saved-transcript-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = Settings(self.root)
        self.media = Media(self.root / "mock.mp4", 90, 640, 360, "h264", True, 1)
        self.source_hash = "c" * 64
        self.saved = {"schema_version": 1,
                      "fingerprint": {"media_sha256": self.source_hash, "language": None},
                      "language": "en", "segments": [{"start": 11, "end": 13, "text": "Saved caption"}]}

    def run_process(self, **overrides):
        options = dict(start=10, end=25, captions=True, saved_transcript=self.saved,
                       source_sha256=self.source_hash, framing=FramingSettings(mode="full_gameplay"))
        options.update(overrides)

        def encode(media, candidate, destination, settings, *arguments, **keywords):
            destination.write_bytes(b"mock encoder output")

        with patch("autoclip.engine.inspect_media", return_value=self.media), \
                patch("autoclip.engine.render_clip", side_effect=encode):
            return process(self.media.path, self.settings, **options)

    def test_reuse_skips_model_inference_audio_analysis_and_selection(self):
        phases = []
        with patch("autoclip.speech.SpeechSettings.from_environment") as config, \
                patch("autoclip.speech.transcribe_media") as transcribe, \
                patch("autoclip.engine.extract_audio") as extract, \
                patch("autoclip.engine.audio_activity") as activity, \
                patch("autoclip.engine.select_candidates") as select:
            manifest_path = self.run_process(progress_callback=lambda value: phases.append(value["phase"]))
            for operation in (config, transcribe, extract, activity, select):
                operation.assert_not_called()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["state"], "completed")
        self.assertEqual(manifest["transcript_reuse_kind"], "saved_job")
        self.assertTrue(manifest["transcript_cache_hit"])
        self.assertIn("reusing_transcript", phases)
        reused = json.loads((manifest_path.parent / manifest["transcript_file"]).read_text(encoding="utf-8"))
        self.assertEqual(reused["segments"], self.saved["segments"])
        self.assertEqual(reused["reuse_kind"], "saved_job")
        captions = (manifest_path.parent / manifest["clips"][0]["srt_file"]).read_text(encoding="utf-8")
        self.assertIn("00:00:01,000 --> 00:00:03,000", captions)
        self.assertIn("Saved caption", captions)

    def test_speech_only_revision_reuses_without_generating_subtitles(self):
        with patch("autoclip.speech.transcribe_media") as transcribe, \
                patch("autoclip.speech.write_subtitles") as subtitles:
            path = self.run_process(captions=False, speech_ranking=True)
            transcribe.assert_not_called()
            subtitles.assert_not_called()
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(manifest["transcript_cache_hit"])
        self.assertIsNone(manifest["clips"][0]["srt_file"])

    def test_source_mismatch_fails_without_falling_back_to_inference(self):
        with patch("autoclip.speech.transcribe_media") as transcribe:
            with self.assertRaisesRegex(ClipError, "imported recording"):
                self.run_process(source_sha256="d" * 64)
            transcribe.assert_not_called()
        manifests = list((self.root / "clips").glob("*/manifest.json"))
        self.assertEqual(len(manifests), 1)
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        self.assertEqual(manifest["state"], "failed")
        self.assertEqual(manifest["clips"], [])

    def test_missing_trusted_hash_fails_without_inference(self):
        with patch("autoclip.speech.transcribe_media") as transcribe:
            with self.assertRaisesRegex(ClipError, "content hash"):
                self.run_process(source_sha256=None)
            transcribe.assert_not_called()

    def test_saved_reuse_cannot_trigger_automatic_selection_or_disable_speech(self):
        for options in ({"start": None, "end": None}, {"captions": False, "speech_ranking": False}):
            with self.subTest(options=options), patch("autoclip.engine.inspect_media") as inspect:
                with self.assertRaisesRegex(ClipError, "explicit interval"):
                    process(self.media.path, self.settings, saved_transcript=self.saved,
                            source_sha256=self.source_hash, **{"captions": True, **options})
                inspect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
