"""Aspect-ratio validation, API persistence, captions, CLI and real renders."""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from autoclip.__main__ import main
from autoclip.api import create_app
from autoclip.engine import ClipError, Settings, output_dimensions, process, run_tool, video_filter
from autoclip.speech import write_subtitles


EXPECTED_OUTPUTS = {
    "9:16": {480: (480, 854), 720: (720, 1280), 1080: (1080, 1920)},
    "16:9": {480: (854, 480), 720: (1280, 720), 1080: (1920, 1080)},
    "1:1": {480: (480, 480), 720: (720, 720), 1080: (1080, 1080)},
    "4:5": {480: (480, 600), 720: (720, 900), 1080: (1080, 1350)},
}


class AspectRatioTests(unittest.TestCase):
    def test_dimensions_and_filters_for_all_export_sizes(self):
        for ratio, sizes in EXPECTED_OUTPUTS.items():
            for resolution, (width, height) in sizes.items():
                with self.subTest(ratio=ratio, resolution=resolution):
                    self.assertEqual(output_dimensions(resolution, ratio), (width, height))
                    for layout in ("pad", "crop"):
                        filters = video_filter(layout, resolution, ratio)
                        self.assertIn(f"pad={width}:{height}", filters)
                        self.assertEqual("crop=" in filters, layout == "crop")
        self.assertEqual(output_dimensions(720), (720, 1280))
        for resolution, ratio in ((360, "16:9"), (720, "5:4"), (1080, "invalid")):
            with self.subTest(resolution=resolution, ratio=ratio), self.assertRaises(ClipError):
                video_filter("pad", resolution, ratio)

    def test_captions_use_output_canvas_and_keep_srt_content(self):
        segments = [{"start": 1, "end": 3, "text": "Caption sample"}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference_srt = None
            for ratio, sizes in EXPECTED_OUTPUTS.items():
                for resolution, (width, height) in sizes.items():
                    with self.subTest(ratio=ratio, resolution=resolution):
                        stem = root / f"clip-{ratio.replace(':', '-')}-{resolution}"
                        path = write_subtitles(segments, 0, 15, stem, resolution=resolution, aspect_ratio=ratio)
                        text = path.read_text(encoding="utf-8")
                        self.assertIn(f"PlayResX: {width}\nPlayResY: {height}", text)
                        srt = path.with_suffix(".srt").read_text(encoding="utf-8")
                        if reference_srt is None:
                            reference_srt = srt
                        self.assertEqual(srt, reference_srt)

    def test_cli_passes_export_settings_to_engine(self):
        arguments = ["autoclip", "clip", "sample.mp4", "--aspect-ratio", "4:5",
                     "--resolution", "480", "--compression", "smaller_file"]
        with patch("sys.argv", arguments), \
                patch("autoclip.__main__.process", return_value=Path("manifest.json")) as render, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 0)
        self.assertEqual(render.call_args.kwargs["aspect_ratio"], "4:5")
        self.assertEqual(render.call_args.kwargs["resolution"], 480)
        self.assertEqual(render.call_args.kwargs["compression"], "smaller_file")


class AspectRatioApiTests(unittest.TestCase):
    defaults = {"aspect_ratio": "9:16", "resolution": 720, "compression": "balanced"}

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        env = patch.dict(os.environ, {"AUTOCLIP_DB_PATH": str(self.root / "queue.sqlite3")})
        env.start()
        self.addCleanup(env.stop)
        self.app = create_app(Settings(self.root), start_worker=False)
        self.client = TestClient(self.app, base_url="http://127.0.0.1")
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.store = self.app.state.service.store
        self.media_id = "a" * 32
        self.store.add_media(self.media_id, "sample.mp4", "sample.mp4", "hash", {"duration": 90})

    def assert_export_options(self, options, expected):
        self.assertEqual({key: options[key] for key in self.defaults}, expected)

    def test_new_jobs_default_and_validate_export_settings(self):
        for options in ({}, {"aspect_ratio": "1:1", "resolution": 480, "compression": "higher_quality"}):
            response = self.client.post("/jobs", json={"media_id": self.media_id, **options})
            self.assertEqual(response.status_code, 202, response.text)
            self.assert_export_options(response.json()["options"], self.defaults | options)
            persisted = self.client.get(f"/jobs/{response.json()['id']}")
            self.assert_export_options(persisted.json()["options"], self.defaults | options)
        for invalid in ({"aspect_ratio": "16/9"}, {"aspect_ratio": None}, {"resolution": 360}, {"compression": "lossless"}):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.client.post("/jobs", json={"media_id": self.media_id, **invalid}).status_code, 422)

    def test_revisions_inherit_or_override_and_legacy_jobs_use_defaults(self):
        for original in ({}, {"aspect_ratio": "16:9", "resolution": 1080, "compression": "higher_quality"}):
            job = self.store.create_job(self.media_id, original)
            self.store.claim()
            self.store.finish(job["id"], manifest={"state": "completed", "clips": [
                {"start": 0, "end": 15, "score": 0, "evidence": {}, "file": "clip-01.mp4"},
            ]})
            saved = self.defaults | original
            self.assert_export_options(self.client.get(f"/jobs/{job['id']}").json()["options"], saved)
            candidate = self.client.get(f"/jobs/{job['id']}/candidates").json()[0]
            route = f"/candidates/{candidate['id']}/render"
            for requested in ({}, {"aspect_ratio": "4:5", "resolution": 480, "compression": "smaller_file"}):
                response = self.client.post(route, json={"start": 1, "end": 16, **requested})
                self.assertEqual(response.status_code, 202, response.text)
                self.assert_export_options(response.json()["options"], saved | requested)
                self.store.cancel(response.json()["id"])
            response = self.client.post(route, json={"start": 1, "end": 16, "aspect_ratio": "5:4"})
            self.assertEqual(response.status_code, 422)


class ExportRenderTests(unittest.TestCase):
    def test_actual_exports_have_expected_canvas_captions_and_stream_timing(self):
        with tempfile.TemporaryDirectory(prefix="autoclip-ratio-") as directory:
            root = Path(directory)
            source = root / "portrait.mp4"
            run_tool(["ffmpeg", "-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i",
                      "color=c=blue:size=90x160:rate=10:duration=16", "-f", "lavfi", "-i",
                      "sine=frequency=440:sample_rate=48000:duration=16", "-c:v", "libx264",
                      "-threads", "2", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)])
            settings = Settings(root / "data", threads=2)
            transcript = {"segments": [{"start": 1, "end": 14, "text": "Export caption sample"}], "language": "en"}
            choices = {480: ("smaller_file", 28), 720: ("balanced", 23), 1080: ("higher_quality", 19)}
            for ratio, sizes in EXPECTED_OUTPUTS.items():
                for resolution, (width, height) in sizes.items():
                    layout = "crop" if ratio in {"16:9", "4:5"} else "pad"
                    compression, crf = choices[resolution]
                    with self.subTest(ratio=ratio, resolution=resolution, layout=layout), \
                            patch("autoclip.speech.transcribe_media", return_value=transcript):
                        manifest_path = process(source, settings, start=0, end=15, layout=layout,
                                                aspect_ratio=ratio, resolution=resolution, captions=True,
                                                compression=compression)
                        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                        self.assertEqual(manifest["settings"]["aspect_ratio"], ratio)
                        self.assertEqual(manifest["settings"]["compression"], compression)
                        self.assertEqual(manifest["settings"]["crf"], crf)
                        clip = manifest["clips"][0]
                        output = manifest_path.parent / clip["file"]
                        streams = json.loads(run_tool([settings.ffprobe, "-v", "error", "-show_streams",
                                                      "-of", "json", str(output)]))["streams"]
                        video = next(stream for stream in streams if stream["codec_type"] == "video")
                        audio = next(stream for stream in streams if stream["codec_type"] == "audio")
                        self.assertEqual((video["width"], video["height"]), (width, height))
                        self.assertEqual(video["codec_name"], "h264")
                        self.assertAlmostEqual(float(video["start_time"]), float(audio["start_time"]), delta=0.1)
                        for stream in (video, audio):
                            self.assertAlmostEqual(float(stream["duration"]), 15, delta=0.15)
                        self.assertTrue((manifest_path.parent / clip["srt_file"]).is_file())
                        ass = (manifest_path.parent / clip["subtitle_file"]).read_text(encoding="utf-8")
                        self.assertIn(f"PlayResX: {width}\nPlayResY: {height}", ass)
                        run_tool(["ffmpeg", "-nostdin", "-v", "error", "-i", str(output), "-f", "null", "-"])


if __name__ == "__main__":
    unittest.main()
