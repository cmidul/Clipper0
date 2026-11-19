"""Actual CPU FFmpeg composition checks using temporary synthetic media."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from autoclip.composition import build_filtergraph
from autoclip.reframing import (
    CropKeyframe, FocusPoint, FramingPlan, FramingSettings, Region, crop_for_focus,
)


class CompositionIntegrationTests(unittest.TestCase):
    @classmethod
    def command(cls, arguments):
        result = subprocess.run(arguments, stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
        if result.returncode:
            raise AssertionError(result.stderr.decode("utf-8", errors="replace")[-4000:])
        return result.stdout

    @classmethod
    def setUpClass(cls):
        cls.ffmpeg = shutil.which("ffmpeg")
        cls.ffprobe = shutil.which("ffprobe")
        if not cls.ffmpeg or not cls.ffprobe:
            raise RuntimeError("FFmpeg and ffprobe are required for composition integration tests.")
        cls.temporary = tempfile.TemporaryDirectory(prefix="autoclip-composition-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        cls.source = cls.directory / "synthetic source.mp4"
        # Red/blue side markers reveal unwanted gameplay cropping. A green
        # top-left rectangle stands in for a manually selected webcam region.
        cls.command([
            cls.ffmpeg, "-nostdin", "-v", "error", "-n",
            "-f", "lavfi", "-i", "color=c=gray:s=640x360:r=5:d=15",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=15",
            "-vf", "drawbox=x=0:y=0:w=32:h=360:color=red:t=fill,"
            "drawbox=x=608:y=0:w=32:h=360:color=blue:t=fill,"
            "drawbox=x=0:y=0:w=128:h=72:color=green:t=fill",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-threads", "2", "-c:a", "aac", "-shortest", str(cls.source),
        ])

    def render(self, mode, *, background="pad", webcam=None, focus=None, track=None, emphasis=False,
               aspect_ratio="9:16", resolution=720, expected_size=(720, 1280)):
        frames = ()
        if mode == "smart_crop":
            frames = (CropKeyframe(0, crop_for_focus(640, 360, focus, aspect_ratio=aspect_ratio), 1),)
        if track is not None:
            frames = track
        plan = FramingPlan(640, 360, 0, 15, mode, mode, 1, keyframes=frames,
                           emphasis_times=(2, 10) if emphasis else ())
        composition = build_filtergraph(
            plan, FramingSettings(mode=mode, background=background, webcam_region=webcam, emphasis_zoom=emphasis),
            aspect_ratio=aspect_ratio, resolution=resolution,
        )
        name = self._testMethodName
        if (aspect_ratio, resolution) != ("9:16", 720):
            name += f"-{mode}-{aspect_ratio.replace(':', 'x')}-{resolution}"
        destination = self.directory / f"{name}.mp4"
        self.command([
            self.ffmpeg, "-nostdin", "-v", "error", "-n", "-i", str(self.source),
            "-filter_complex_threads", "1", "-filter_complex", composition.filtergraph,
            "-map", composition.output_label, "-map", "0:a:0", "-t", "15",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-threads", "2",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(destination),
        ])
        metadata = json.loads(self.command([
            self.ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(destination),
        ]))
        video = next(stream for stream in metadata["streams"] if stream["codec_type"] == "video")
        audio = next(stream for stream in metadata["streams"] if stream["codec_type"] == "audio")
        self.assertEqual((video["width"], video["height"]), expected_size)
        self.assertEqual(video["sample_aspect_ratio"], "1:1")
        self.assertEqual(video["codec_name"], "h264")
        self.assertEqual(audio["codec_name"], "aac")
        self.assertAlmostEqual(float(video["duration"]), 15, delta=0.21)
        self.assertAlmostEqual(float(audio["duration"]), 15, delta=0.1)
        self.assertAlmostEqual(float(video["start_time"]), float(audio["start_time"]), delta=0.05)
        self.assertAlmostEqual(float(video["duration"]), float(audio["duration"]), delta=0.21)
        # Decode every stream to catch corruption beyond the sampled frame.
        self.command([
            self.ffmpeg, "-nostdin", "-v", "error", "-i", str(destination),
            "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-",
        ])
        pixels = self.command([
            self.ffmpeg, "-nostdin", "-v", "error", "-ss", "1", "-i", str(destination),
            "-map", "0:v:0", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ])
        width, height = expected_size
        self.assertEqual(len(pixels), width * height * 3)
        return pixels

    def pixel(self, pixels, x, y):
        offset = (y * 720 + x) * 3
        return tuple(pixels[offset:offset + 3])

    def assert_red(self, pixel):
        red, green, blue = pixel
        self.assertGreater(red, 150)
        self.assertGreater(red, green + 90)
        self.assertGreater(red, blue + 90)

    def assert_blue(self, pixel):
        red, green, blue = pixel
        self.assertGreater(blue, 150)
        self.assertGreater(blue, red + 90)
        self.assertGreater(blue, green + 90)

    def test_full_gameplay_padding_preserves_both_edges(self):
        pixels = self.render("full_gameplay")
        self.assert_red(self.pixel(pixels, 56, 640))
        self.assert_blue(self.pixel(pixels, 664, 640))
        self.assertLess(max(self.pixel(pixels, 20, 640)), 10)
        self.assertLess(max(self.pixel(pixels, 360, 100)), 10)

    def test_full_gameplay_blur_preserves_foreground_edges(self):
        pixels = self.render("full_gameplay", background="blur")
        self.assert_red(self.pixel(pixels, 56, 640))
        self.assert_blue(self.pixel(pixels, 664, 640))
        self.assertGreater(max(self.pixel(pixels, 360, 100)), 30)

    def test_manual_webcam_split_preserves_gameplay_and_camera(self):
        pixels = self.render("streamer_gameplay", webcam=Region(0, 0, 0.2, 0.2))
        red, green, blue = self.pixel(pixels, 360, 192)
        self.assertGreater(green, 80)
        self.assertGreater(green, red + 50)
        self.assertGreater(green, blue + 50)
        self.assert_red(self.pixel(pixels, 56, 832))
        self.assert_blue(self.pixel(pixels, 664, 832))

    def test_manual_static_focus_reaches_right_edge(self):
        pixels = self.render("smart_crop", focus=FocusPoint(1, 0.5))
        self.assert_blue(self.pixel(pixels, 442, 640))
        red, green, blue = self.pixel(pixels, 277, 640)
        self.assertLess(max(red, green, blue) - min(red, green, blue), 15)

    def test_moving_crop_reaches_both_sides_without_retiming(self):
        frames = (CropKeyframe(0, crop_for_focus(640, 360, FocusPoint(0, 0.5)), 1),
                  CropKeyframe(10, crop_for_focus(640, 360, FocusPoint(1, 0.5)), 1))
        early = self.render("smart_crop", track=frames)
        self.assert_red(self.pixel(early, 277, 640))
        destination = self.directory / f"{self._testMethodName}.mp4"
        late = self.command([self.ffmpeg, "-nostdin", "-v", "error", "-ss", "12", "-i", str(destination),
                             "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
        self.assert_blue(self.pixel(late, 442, 640))

    def test_optional_emphasis_keeps_dimensions_duration_and_audio(self):
        self.render("smart_crop", focus=FocusPoint(0.5, 0.5), emphasis=True)

    def test_actual_framing_modes_render_all_four_480p_canvases(self):
        canvases = {"9:16": (480, 854), "16:9": (854, 480), "1:1": (480, 480), "4:5": (480, 600)}
        layouts = {
            "full_gameplay": {"background": "blur"},
            "streamer_gameplay": {"webcam": Region(0, 0, 0.2, 0.2)},
            "smart_crop": {"focus": FocusPoint(1, 0.5)},
        }
        for ratio, size in canvases.items():
            for mode, options in layouts.items():
                with self.subTest(ratio=ratio, mode=mode):
                    self.render(mode, aspect_ratio=ratio, resolution=480, expected_size=size, **options)


if __name__ == "__main__":
    unittest.main()
