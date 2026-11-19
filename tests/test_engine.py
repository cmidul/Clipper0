import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from autoclip.engine import (
    Candidate, ClipError, Media, Settings, inspect_media, process, render_clip,
    run_tool, select_candidates, video_filter, worker_lock,
)


class CandidateTests(unittest.TestCase):
    def test_silence_constant_and_missing_audio_have_no_candidates(self):
        for activity in ([], [0.0] * 90, [0.2] * 90):
            with self.subTest(activity=activity[:2]):
                self.assertEqual(select_candidates(activity, 90), [])

    def test_boundary_events_stay_inside_recording(self):
        activity = [0.001] * 120
        activity[0] = 1.0
        activity[60] = 0.9
        activity[-1] = 0.8
        candidates = select_candidates(activity, 120)
        self.assertEqual(len(candidates), 3)
        for candidate in candidates:
            self.assertGreaterEqual(candidate.start, 0)
            self.assertLessEqual(candidate.end, 120)
            self.assertAlmostEqual(candidate.end - candidate.start, 30)

    def test_candidates_are_deterministic_and_separated(self):
        activity = [0.001] * 120
        for second in (10, 11, 12, 45, 46, 85):
            activity[second] = 1.0
        first = select_candidates(activity, 120, 15)
        self.assertEqual(first, select_candidates(activity, 120, 15))
        ordered = sorted(first, key=lambda c: c.start)
        for left, right in zip(ordered, ordered[1:]):
            self.assertGreaterEqual(right.start - left.end, 2)

    def test_short_recording_has_no_auto_candidates(self):
        self.assertEqual(select_candidates([1.0, 0], 10), [])

    def test_invalid_settings_are_rejected(self):
        for length in (0, 14, 61, float("nan")):
            with self.subTest(length=length), self.assertRaises(ClipError):
                select_candidates([0, 1], 90, length)
        with self.assertRaises(ClipError):
            select_candidates([0, float("inf")], 90)


class SafetyTests(unittest.TestCase):
    def test_bad_extension_and_missing_file_are_rejected(self):
        settings = Settings(Path("local-data"))
        for filename in ("invalid.txt", "missing.mp4"):
            with self.assertRaises(ClipError):
                inspect_media(Path(filename), settings)

    def test_missing_binary_has_friendly_error(self):
        with self.assertRaisesRegex(ClipError, "Missing executable"):
            run_tool(["autoclip-nonexistent-executable-72638"])

    def test_nonvideo_and_nonfinite_duration_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.mp4"
            path.write_bytes(b"fixture")
            metadata = {"format": {"format_name": "mov,mp4", "duration": "nan"},
                        "streams": [{"codec_type": "video", "width": 100, "height": 100}]}
            with patch("autoclip.engine.run_tool", return_value=json.dumps(metadata)):
                with self.assertRaises(ClipError):
                    inspect_media(path, Settings(Path(directory)))
            metadata["streams"] = [{"codec_type": "audio"}]
            with patch("autoclip.engine.run_tool", return_value=json.dumps(metadata)):
                with self.assertRaisesRegex(ClipError, "no video"):
                    inspect_media(path, Settings(Path(directory)))

    def test_manual_invalid_bounds_never_launch_ffmpeg(self):
        media = Media(Path("input.mp4"), 90, 1920, 1080, "h264", False, 100)
        for start, end in ((-1, 20), (70, 95), (10, 12), (float("nan"), 40)):
            with patch("autoclip.engine.run_tool") as tool:
                with self.assertRaises(ClipError):
                    render_clip(media, Candidate(start, end, 0, {}), Path("output.mp4"), Settings(Path("data")))
                tool.assert_not_called()

    def test_layout_validation(self):
        self.assertIn("pad=720:1280", video_filter("pad", 720))
        crop = video_filter("crop", 1080)
        self.assertTrue(crop.startswith("crop="))
        self.assertIn("pad=1080:1920", crop)
        with self.assertRaises(ClipError):
            video_filter("invalid", 720)

    def test_compression_profiles_set_crf_without_changing_preset(self):
        def simulate_encoder(arguments, **kwargs):
            Path(arguments[-1]).touch()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = Media(root / "source.mp4", 16, 1920, 1080, "h264", False, 1)
            candidate = Candidate(0, 15, 0, {})
            for profile, crf in (("higher_quality", "19"), ("balanced", "23"), ("smaller_file", "28")):
                with self.subTest(profile=profile), patch("autoclip.engine.run_tool", side_effect=simulate_encoder) as tool:
                    render_clip(media, candidate, root / f"{profile}.mp4", Settings(root), compression=profile)
                    arguments = tool.call_args.args[0]
                    self.assertEqual(arguments[arguments.index("-crf") + 1], crf)
                    self.assertEqual(arguments[arguments.index("-preset") + 1], "veryfast")

    def test_failed_render_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "clip.mp4"
            media = Media(Path("input.mp4"), 30, 1920, 1080, "h264", False, 100)

            def fail(arguments):
                Path(arguments[-1]).write_bytes(b"unfinished")
                raise ClipError("Encoder failed")

            with patch("autoclip.engine.run_tool", side_effect=fail):
                with self.assertRaises(ClipError):
                    render_clip(media, Candidate(0, 15, 0, {}), destination, Settings(Path(directory)))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_lock_releases_and_prevents_concurrent_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with worker_lock(root):
                with self.assertRaises(ClipError):
                    with worker_lock(root):
                        self.fail("Second worker acquired lock")
            with worker_lock(root):
                pass

    def test_failed_and_cancelled_jobs_preserve_status(self):
        for failure, expected in ((ClipError("Failed analysis"), "failed"),
                                  (KeyboardInterrupt(), "cancelled")):
            with self.subTest(state=expected), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                media = Media(root / "input.mp4", 30, 1920, 1080, "h264", True, 100)
                with patch("autoclip.engine.inspect_media", return_value=media):
                    with patch("autoclip.engine.audio_activity", side_effect=failure):
                        with self.assertRaises(type(failure)):
                            process(media.path, Settings(root))
                manifests = list(root.glob("clips/*/manifest.json"))
                self.assertEqual(len(manifests), 1)
                self.assertEqual(json.loads(manifests[0].read_text(encoding="utf-8"))["state"], expected)
                self.assertFalse(list(root.glob("analysis-*")))


if __name__ == "__main__":
    unittest.main()
