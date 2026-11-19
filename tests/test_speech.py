import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from autoclip.engine import ClipError, Media, Settings, process
from autoclip.speech import (
    SpeechSettings, clip_segments, model_fingerprint, normalize_segments,
    subtitle_time, transcribe_media, write_subtitles,
)


class SubtitleTests(unittest.TestCase):
    def test_framed_caption_positions_respect_safe_area_and_split_seam(self):
        from autoclip.reframing import FramingSettings
        with tempfile.TemporaryDirectory() as directory:
            positions = []
            for position, layout in (("top", "smart_crop"), ("center", "smart_crop"),
                                     ("bottom", "smart_crop"), ("auto", "streamer_gameplay")):
                path = write_subtitles([{"start": 0, "end": 5, "text": "Readable caption"}],
                                      0, 15, Path(directory) / position,
                                      framing=FramingSettings(subtitle_position=position), layout_mode=layout)
                import re
                positions.append(int(re.search(r"\\pos\(360,(\d+)\)", path.read_text(encoding="utf-8")).group(1)))
            self.assertLess(positions[0], positions[1])
            self.assertLess(positions[1], positions[2])
            self.assertLess(positions[2], 1280 * .85)
            self.assertAlmostEqual(positions[3], 1280 * .3 + 44, delta=1)

    def test_long_framed_caption_has_two_lines_per_event_and_preserves_srt(self):
        from autoclip.reframing import FramingSettings
        with tempfile.TemporaryDirectory() as directory:
            stem = Path(directory) / "long"
            text = "Long readable caption with many words " * 12
            path = write_subtitles([{"start": 0, "end": 12, "text": text}], 0, 15, stem,
                                  framing=FramingSettings(safe_margin_horizontal=.35))
            events = [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("Dialogue:")]
            self.assertGreater(len(events), 1)
            self.assertTrue(all(event.count(r"\N") <= 1 for event in events))
            self.assertIn(text.strip(), stem.with_suffix(".srt").read_text(encoding="utf-8"))
            self.assertIn("0:00:12.00", events[-1])

    def test_clipping_rebases_and_bounds_subtitle_timestamps(self):
        segments = [{"start": 5, "end": 12, "text": "first"},
                    {"start": 14, "end": 30, "text": "second"},
                    {"start": 40, "end": 42, "text": "outside"}]
        self.assertEqual(clip_segments(segments, 10, 25), [
            {"start": 0.0, "end": 2.0, "text": "first"},
            {"start": 4.0, "end": 15.0, "text": "second"},
        ])

    def test_normalization_removes_overlap_and_empty_text(self):
        segments = [{"start": -1, "end": 3, "text": "one"},
                    {"start": 2, "end": 5, "text": "two"},
                    {"start": 5, "end": 6, "text": "  "}]
        self.assertEqual(normalize_segments(segments, 4), [
            {"start": 0.0, "end": 3.0, "text": "one"},
            {"start": 3.0, "end": 4.0, "text": "two"},
        ])

    def test_timestamp_rounding_carries_across_minutes(self):
        self.assertEqual(subtitle_time(59.9999), "00:01:00,000")
        self.assertEqual(subtitle_time(59.9999, ass=True), "0:01:00.00")

    def test_multilingual_special_characters_and_ass_injection(self):
        with tempfile.TemporaryDirectory() as directory:
            stem = Path(directory) / "clip-01"
            text = r"Hello বাংলা العربية <world> {\pos(0,0)}"
            ass = write_subtitles([{"start": 0, "end": 3, "text": text}], 0, 15, stem)
            rendered = ass.read_text(encoding="utf-8")
            self.assertIn("বাংলা العربية", rendered)
            self.assertNotIn(r"{\pos", rendered)
            self.assertIn("&lt;world&gt;", stem.with_suffix(".srt").read_text(encoding="utf-8"))

    def test_no_speech_creates_no_subtitles(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(write_subtitles([], 0, 15, Path(directory) / "clip-01"))
            self.assertEqual(list(Path(directory).iterdir()), [])


class TranscriptionTests(unittest.TestCase):
    def test_missing_model_has_actionable_message(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ClipError, "prepare-model"):
                model_fingerprint(SpeechSettings(Path(directory)))

    def test_no_audio_needs_no_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = Media(root / "input.mp4", 30, 100, 100, "h264", False, 1)
            transcript = transcribe_media(media, Settings(root), SpeechSettings(root / "missing"), root)
            self.assertEqual(transcript["segments"], [])

    def test_model_and_language_configuration_are_validated(self):
        with patch.dict("os.environ", {"AUTOCLIP_MODEL_SIZE": "base"}):
            config = SpeechSettings.from_environment(Settings(Path("data")), "bn")
            self.assertEqual(config.language, "bn")
            with self.assertRaises(ClipError):
                SpeechSettings.from_environment(Settings(Path("data")), "../../bad")
        with patch.dict("os.environ", {"AUTOCLIP_MODEL_SIZE": "base.en"}):
            with self.assertRaises(ClipError):
                SpeechSettings.from_environment(Settings(Path("data")))

    def test_cache_reuse_corruption_recovery_and_content_invalidation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.mp4"
            source.write_bytes(b"first media content")
            model_dir = root / "model"
            model_dir.mkdir()
            for filename in ("model.bin", "config.json", "tokenizer.json"):
                (model_dir / filename).write_bytes(b"model")
            (root / "analysis.wav").write_bytes(b"mock audio")
            settings = Settings(root)
            config = SpeechSettings(model_dir)
            media = Media(source, 30, 100, 100, "h264", True, 19)
            fake_model = SimpleNamespace(transcribe=lambda *args, **kwargs: (
                iter([SimpleNamespace(start=1, end=3, text=" hello ")]),
                SimpleNamespace(language="en", language_probability=0.99),
            ))
            module = SimpleNamespace(WhisperModel=lambda *args, **kwargs: fake_model)
            with patch.dict("sys.modules", {"faster_whisper": module}), patch("autoclip.speech.version", return_value="test"):
                first = transcribe_media(media, settings, config, root)
                self.assertFalse(first["cache_hit"])
                second = transcribe_media(media, settings, config, root)
                self.assertTrue(second["cache_hit"])
                cache = next((root / "transcripts").glob("*.json"))
                cache.write_text("broken json", encoding="utf-8")
                self.assertFalse(transcribe_media(media, settings, config, root)["cache_hit"])
                source.write_bytes(b"changed media content")
                self.assertFalse(transcribe_media(media, settings, config, root)["cache_hit"])
                (model_dir / "model.bin").write_bytes(b"changed weights")
                self.assertFalse(transcribe_media(media, settings, config, root)["cache_hit"])
                self.assertEqual(len(list((root / "transcripts").glob("*.json"))), 3)

    def test_speech_failure_is_persisted_in_job_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = Media(root / "input.mp4", 30, 100, 100, "h264", True, 1)
            with patch("autoclip.engine.inspect_media", return_value=media), \
                    patch("autoclip.speech.transcribe_media", side_effect=ClipError("Speech failed")):
                with self.assertRaisesRegex(ClipError, "Speech failed"):
                    process(media.path, Settings(root), captions=True, start=0, end=15)
            manifest = json.loads(next(root.glob("clips/*/manifest.json")).read_text(encoding="utf-8"))
            self.assertEqual(manifest["state"], "failed")


if __name__ == "__main__":
    unittest.main()
