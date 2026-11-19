"""Framing integration through the existing atomic export function."""

import json
from dataclasses import replace
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from autoclip.engine import Candidate, ClipError, Settings, inspect_media, process, render_clip
from autoclip.reframing import FocusPoint, FramingSettings, Region, build_initial_plan
from autoclip.speech import write_subtitles


class FramingRenderTests(unittest.TestCase):
    @classmethod
    def command(cls, arguments):
        result = subprocess.run(arguments, stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
        if result.returncode:
            raise AssertionError(result.stderr.decode("utf-8", errors="replace")[-4000:])
        return result.stdout

    @classmethod
    def setUpClass(cls):
        ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            raise RuntimeError("FFmpeg and ffprobe are required for framing renderer tests.")
        cls.temporary = tempfile.TemporaryDirectory(prefix="autoclip-framing-render-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        cls.settings = Settings(cls.directory, ffmpeg=ffmpeg, ffprobe=ffprobe, threads=2)
        cls.source = cls.directory / "source with audio.mp4"
        cls.silent = cls.directory / "silent source.mp4"
        cls.command([
            ffmpeg, "-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i",
            "testsrc2=s=640x360:r=10:d=20", "-f", "lavfi", "-i",
            "sine=frequency=660:sample_rate=48000:duration=20", "-c:v", "libx264",
            "-preset", "ultrafast", "-threads", "2", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(cls.source),
        ])
        cls.command([
            ffmpeg, "-nostdin", "-v", "error", "-n", "-i", str(cls.source),
            "-map", "0:v:0", "-c:v", "copy", "-an", str(cls.silent),
        ])
        cls.media = inspect_media(cls.source, cls.settings)
        cls.silent_media = inspect_media(cls.silent, cls.settings)

    def destination(self):
        return self.directory / f"{self._testMethodName}.mp4"

    def candidate(self):
        return Candidate(2, 17, 1, {})

    def plan(self, settings, **overrides):
        options = dict(source_width=640, source_height=360, start=2, end=17, settings=settings)
        options.update(overrides)
        return build_initial_plan(**options)

    def probe_and_decode(self, path, *, audio):
        metadata = json.loads(self.command([
            self.settings.ffprobe, "-v", "error", "-show_streams", "-of", "json", str(path),
        ]))
        video = next(stream for stream in metadata["streams"] if stream["codec_type"] == "video")
        audio_streams = [stream for stream in metadata["streams"] if stream["codec_type"] == "audio"]
        self.assertEqual((video["width"], video["height"]), (720, 1280))
        self.assertEqual(video["avg_frame_rate"], "30/1")
        self.assertAlmostEqual(float(video["duration"]), 15, delta=0.05)
        self.assertEqual(bool(audio_streams), audio)
        if audio:
            self.assertAlmostEqual(float(video["start_time"]), float(audio_streams[0]["start_time"]), delta=0.05)
            self.assertAlmostEqual(float(video["duration"]), float(audio_streams[0]["duration"]), delta=0.1)
        self.command([
            self.settings.ffmpeg, "-nostdin", "-v", "error", "-i", str(path), "-f", "null", "-",
        ])
        self.assertFalse(list(self.directory.glob(f".{path.stem}-*.partial.mp4")))

    def test_captioned_blurred_gameplay_exports_audio_and_video(self):
        settings = FramingSettings(mode="full_gameplay", background="blur")
        destination = self.destination()
        subtitles = write_subtitles(
            [{"start": 3, "end": 8, "text": "Framing caption test"}], 2, 17,
            destination.with_suffix(""),
        )
        self.assertIsNotNone(subtitles)
        render_clip(self.media, self.candidate(), destination, self.settings,
                    subtitle_path=subtitles, framing_plan=self.plan(settings), framing_settings=settings)
        self.probe_and_decode(destination, audio=True)
        self.assertTrue(destination.with_suffix(".srt").is_file())

    def test_manual_split_exports_without_audio(self):
        settings = FramingSettings(mode="streamer_gameplay", webcam_region=Region(0, 0, 0.2, 0.2))
        destination = self.destination()
        render_clip(self.silent_media, self.candidate(), destination, self.settings,
                    framing_plan=self.plan(settings), framing_settings=settings)
        self.probe_and_decode(destination, audio=False)

    def test_process_publishes_actual_framed_export_and_plan_manifest(self):
        phases = []
        framing = FramingSettings(mode="smart_crop", focus_point=FocusPoint(0.9, 0.5))
        manifest_path = process(
            self.source, self.settings, start=2, end=17, framing=framing,
            progress_callback=lambda value: phases.append(value["phase"]),
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["state"], "completed")
        self.assertEqual(manifest["progress_pct"], 100)
        self.assertIn("framing", phases)
        self.assertEqual(phases[-1], "done")
        self.assertEqual(manifest["settings"]["framing"]["focus_point"], {"x": 0.9, "y": 0.5})
        self.assertEqual(len(manifest["clips"]), 1)
        clip = manifest["clips"][0]
        self.assertEqual((clip["start"], clip["end"]), (2, 17))
        self.assertEqual(clip["framing"]["selected_mode"], "smart_crop")
        self.assertEqual(clip["framing"]["keyframes"][0]["time"], 0)
        destination = manifest_path.parent / clip["file"]
        self.probe_and_decode(destination, audio=True)
        self.assertFalse(list(manifest_path.parent.glob("*.partial*")))

    def test_mismatched_plan_rejected_before_ffmpeg(self):
        settings = FramingSettings(mode="full_gameplay")
        for overrides in ({"source_width": 1280}, {"start": 3, "end": 18}):
            with self.subTest(overrides=overrides), patch("autoclip.engine.run_tool") as tool:
                with self.assertRaisesRegex(ClipError, "do not match|does not match"):
                    render_clip(self.media, self.candidate(), self.destination(), self.settings,
                                framing_plan=self.plan(settings, **overrides), framing_settings=settings)
                tool.assert_not_called()
        self.assertFalse(self.destination().exists())

    def test_plan_and_settings_must_be_supplied_together(self):
        settings = FramingSettings(mode="full_gameplay")
        for options in ({"framing_plan": self.plan(settings)}, {"framing_settings": settings}):
            with self.subTest(options=options), patch("autoclip.engine.run_tool") as tool:
                with self.assertRaisesRegex(ClipError, "both"):
                    render_clip(self.media, self.candidate(), self.destination(), self.settings, **options)
                tool.assert_not_called()

    def test_failed_framed_export_removes_partial_and_never_publishes(self):
        settings = FramingSettings(mode="full_gameplay")
        destination = self.destination()

        def fail(arguments, **options):
            Path(arguments[-1]).write_bytes(b"incomplete test output")
            raise ClipError("Synthetic renderer failure")

        with patch("autoclip.engine.run_tool", side_effect=fail):
            with self.assertRaisesRegex(ClipError, "Synthetic renderer failure"):
                render_clip(self.media, self.candidate(), destination, self.settings,
                            framing_plan=self.plan(settings), framing_settings=settings)
        self.assertFalse(destination.exists())
        self.assertFalse(list(self.directory.glob(f".{destination.stem}-*.partial.mp4")))

    def test_inspection_retains_rotation_and_pixel_aspect_metadata(self):
        for video_fields, expected_rotation, expected_sar in (
            ({}, 0, "1:1"),
            ({"tags": {"rotate": "90"}}, 90, "1:1"),
            ({"side_data_list": [{"rotation": -90}], "tags": {"rotate": "90"}}, -90, "1:1"),
            ({"sample_aspect_ratio": "4:3"}, 0, "4:3"),
            ({"sample_aspect_ratio": "N/A"}, 0, "1:1"),
            ({"tags": {"rotate": "unknown"}}, None, "1:1"),
        ):
            metadata = {"format": {"format_name": "mov,mp4", "duration": "20"},
                        "streams": [{"codec_type": "video", "width": 640, "height": 360,
                                     "codec_name": "h264", **video_fields}]}
            with self.subTest(fields=video_fields), patch(
                    "autoclip.engine.run_tool", return_value=json.dumps(metadata)):
                media = inspect_media(self.source, self.settings)
                self.assertEqual(media.rotation, expected_rotation)
                self.assertEqual(media.sample_aspect_ratio, expected_sar)

    def test_unsupported_geometry_never_launches_framed_encoder(self):
        settings = FramingSettings(mode="full_gameplay")
        for changes in (
            {"rotation": 90}, {"rotation": -90}, {"rotation": 180},
            {"rotation": None}, {"rotation": float("nan")}, {"rotation": float("inf")},
            {"sample_aspect_ratio": "4:3"}, {"sample_aspect_ratio": "0:1"},
            {"sample_aspect_ratio": "unknown"}, {"sample_aspect_ratio": "1:1:1"},
        ):
            with self.subTest(changes=changes), patch("autoclip.engine.run_tool") as tool:
                with self.assertRaisesRegex(ClipError, "source geometry|square-pixel|unrotated"):
                    render_clip(replace(self.media, **changes), self.candidate(), self.destination(),
                                self.settings, framing_plan=self.plan(settings), framing_settings=settings)
                tool.assert_not_called()
        self.assertFalse(self.destination().exists())

    def test_equivalent_square_geometry_passes_guard(self):
        settings = FramingSettings(mode="full_gameplay")

        def simulate_encode(arguments, **options):
            Path(arguments[-1]).write_bytes(b"mock encoder output for geometry guard only")
            return ""

        for index, rotation in enumerate((0, 360, -360)):
            destination = self.directory / f"geometry-{index}.mp4"
            with self.subTest(rotation=rotation), patch("autoclip.engine.run_tool", side_effect=simulate_encode) as tool:
                render_clip(replace(self.media, rotation=rotation, sample_aspect_ratio="2:2"),
                            self.candidate(), destination, self.settings,
                            framing_plan=self.plan(settings), framing_settings=settings)
                tool.assert_called_once()
                self.assertTrue(destination.is_file())


if __name__ == "__main__":
    unittest.main()
