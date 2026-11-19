"""Synthetic media smoke tests. Run explicitly with unittest discovery."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from autoclip.engine import Settings, inspect_media, process, run_tool


class MediaIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ.get("AUTOCLIP_DATA_DIR", "local-data")).resolve() / "test-runs"
        cls.root.mkdir(parents=True, exist_ok=True)

    def test_audio_candidates_render_three_vertical_mp4s(self):
        with tempfile.TemporaryDirectory(prefix="clip spaces বাংলা-", dir=self.root) as directory:
            root = Path(directory)
            source = root / "owned synthetic sample.mkv"
            run_tool([
                "ffmpeg", "-nostdin", "-v", "error", "-n",
                "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=10:duration=70",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=70",
                "-af", "volume=0.01,volume=50:enable='between(t,8,10)+between(t,33,35)+between(t,58,60)'",
                "-c:v", "libx264", "-preset", "ultrafast", "-threads", "2",
                "-c:a", "aac", "-shortest", str(source),
            ])
            settings = Settings(root / "data", threads=2)
            manifest_path = process(source, settings, clip_length=15)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["state"], "completed")
            self.assertEqual(len(manifest["clips"]), 3)
            for clip in manifest["clips"]:
                output = manifest_path.parent / clip["file"]
                media = inspect_media(output, settings)
                self.assertEqual((media.width, media.height), (720, 1280))
                self.assertEqual(media.codec, "h264")
                self.assertTrue(media.audio_present)
                self.assertAlmostEqual(media.duration, 15, delta=0.15)
                run_tool(["ffmpeg", "-nostdin", "-v", "error", "-i", str(output), "-f", "null", "-"])

    def test_no_audio_and_manual_portrait_crop(self):
        with tempfile.TemporaryDirectory(prefix="silent-", dir=self.root) as directory:
            root = Path(directory)
            source = root / "portrait no audio.mp4"
            run_tool([
                "ffmpeg", "-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i",
                "color=c=blue:size=90x160:rate=15:duration=16", "-c:v", "libx264",
                "-threads", "2", "-pix_fmt", "yuv420p", str(source),
            ])
            settings = Settings(root / "data", threads=2)
            manifest = json.loads(process(source, settings).read_text(encoding="utf-8"))
            self.assertEqual(manifest["state"], "completed")
            self.assertEqual(manifest["clips"], [])
            path = process(source, settings, start=0, end=15, layout="crop", captions=True)
            manual = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(manual["caption_status"], "no_speech")
            output = path.parent / manual["clips"][0]["file"]
            media = inspect_media(output, settings)
            self.assertFalse(media.audio_present)
            self.assertEqual((media.width, media.height), (720, 1280))

    def test_cli_1080p60_and_silent_audio(self):
        with tempfile.TemporaryDirectory(prefix="1080p60-", dir=self.root) as directory:
            root = Path(directory)
            source = root / "1080p 60fps silent.mp4"
            run_tool([
                "ffmpeg", "-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i",
                "color=c=green:size=1920x1080:rate=60:duration=16",
                "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
                "-t", "16", "-c:v", "libx264", "-preset", "ultrafast",
                "-threads", "2", "-c:a", "aac", str(source),
            ])
            environment = os.environ.copy()
            environment["AUTOCLIP_DATA_DIR"] = str(root / "data")
            environment["AUTOCLIP_WORKER_THREADS"] = "2"
            automatic = subprocess.run(
                [sys.executable, "-m", "autoclip", "clip", str(source)],
                env=environment, capture_output=True, text=True, encoding="utf-8", timeout=120,
            )
            self.assertEqual(automatic.returncode, 0, automatic.stderr)
            auto_manifest = json.loads(Path(automatic.stdout.strip()).read_text(encoding="utf-8"))
            self.assertEqual(auto_manifest["clips"], [])
            self.assertEqual(auto_manifest["state"], "completed")
            manual = subprocess.run(
                [sys.executable, "-m", "autoclip", "clip", str(source),
                 "--start", "0", "--end", "15", "--resolution", "1080", "--fps", "60"],
                env=environment, capture_output=True, text=True, encoding="utf-8", timeout=180,
            )
            self.assertEqual(manual.returncode, 0, manual.stderr)
            manifest_path = Path(manual.stdout.strip())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            output = manifest_path.parent / manifest["clips"][0]["file"]
            media = inspect_media(output, Settings(root / "data"))
            self.assertEqual((media.width, media.height), (1080, 1920))
            streams = json.loads(run_tool([
                "ffprobe", "-v", "error", "-show_streams", "-of", "json", str(output),
            ]))["streams"]
            video = next(stream for stream in streams if stream["codec_type"] == "video")
            self.assertEqual(video["avg_frame_rate"], "60/1")
            run_tool(["ffmpeg", "-nostdin", "-v", "error", "-i", str(output), "-f", "null", "-"])


if __name__ == "__main__":
    unittest.main()
