"""Real CPU inference smoke test using locally synthesized Windows speech."""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import uuid

from autoclip.engine import Candidate, Settings, inspect_media, render_clip, run_tool
from autoclip.speech import SpeechSettings, write_subtitles


class SpeechIntegrationTests(unittest.TestCase):
    def test_multilingual_subtitle_render(self):
        settings = Settings.from_environment()
        root = settings.data_dir / "speech-smoke"
        root.mkdir(parents=True, exist_ok=True)
        source = root / "font-test.mp4"
        run_tool([
            "ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
            "color=c=black:size=160x90:rate=10:duration=16", "-c:v", "libx264",
            "-threads", "2", str(source),
        ])
        output = root / f"font-test-{uuid.uuid4().hex}.mp4"
        subtitle = write_subtitles([
            {"start": 0, "end": 15, "text": "Caption test বাংলা পরীক্ষা العربية"},
        ], 0, 15, output.with_suffix(""))
        render_clip(inspect_media(source, settings), Candidate(0, 15, 0, {}), output,
                    settings, subtitle_path=subtitle)
        run_tool(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", "2", "-i", str(output),
                  "-frames:v", "1", str(root / "multilingual-preview.png")])

    def test_silent_audio_completes_without_caption_overlay(self):
        settings = Settings.from_environment()
        config = SpeechSettings.from_environment(settings)
        if not (config.model_dir / "model.bin").is_file():
            self.skipTest("Run prepare-model before the real speech test")
        root = settings.data_dir / "speech-smoke"
        root.mkdir(parents=True, exist_ok=True)
        source = root / "silent-audio.mp4"
        run_tool([
            "ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
            "color=c=black:size=160x90:rate=10", "-f", "lavfi", "-i",
            "anullsrc=r=16000:cl=mono", "-t", "16", "-c:v", "libx264",
            "-threads", "2", "-c:a", "aac", str(source),
        ])
        environment = os.environ.copy()
        environment.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        result = subprocess.run(
            [sys.executable, "-m", "autoclip", "clip", str(source), "--captions",
             "--start", "0", "--end", "15"],
            env=environment, capture_output=True, text=True, encoding="utf-8", timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        path = Path(result.stdout.strip())
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["state"], "completed")
        self.assertEqual(manifest["caption_status"], "no_speech")
        self.assertIsNone(manifest["clips"][0]["subtitle_file"])
        self.assertFalse(list(path.parent.glob("*.ass")))

    @unittest.skipUnless(os.name == "nt", "Windows built-in voice fixture")
    def test_offline_cli_captions_and_cached_rerender(self):
        settings = Settings.from_environment()
        config = SpeechSettings.from_environment(settings)
        if not (config.model_dir / "model.bin").is_file():
            self.skipTest("Run prepare-model before the real speech test")
        root = settings.data_dir / "speech-smoke"
        root.mkdir(parents=True, exist_ok=True)
        voice = root / "synthetic-speech.wav"
        fixture_script = Path(__file__).with_name("generate_speech_fixture.ps1").resolve()
        if not voice.is_file() or voice.stat().st_size <= 44:
            run_tool(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                      str(fixture_script), "-OutputPath", str(voice)])
        source = root / "synthetic-speech.mp4"
        run_tool([
            "ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
            "color=c=0x152030:size=320x180:rate=15", "-i", str(voice),
            "-af", "apad", "-t", "20", "-c:v", "libx264", "-preset", "ultrafast",
            "-threads", "2", "-c:a", "aac", str(source),
        ])
        environment = os.environ.copy()
        environment.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
        command = [sys.executable, "-m", "autoclip", "clip", str(source),
                   "--start", "0", "--end", "20", "--captions"]
        manifests = []
        for _ in range(2):
            result = subprocess.run(command, env=environment, capture_output=True,
                                    text=True, encoding="utf-8", timeout=240)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest_path = Path(result.stdout.strip())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["state"], "completed")
            self.assertEqual(manifest["caption_status"], "ready")
            self.assertEqual(manifest["language"], "en")
            transcript = json.loads((manifest_path.parent / "transcript.json").read_text(encoding="utf-8"))
            words = " ".join(segment["text"] for segment in transcript["segments"]).lower()
            self.assertIn("video", words)
            self.assertIn("subtitles", words)
            clip = manifest["clips"][0]
            self.assertTrue((manifest_path.parent / clip["srt_file"]).is_file())
            output = manifest_path.parent / clip["file"]
            media = inspect_media(output, settings)
            self.assertEqual((media.width, media.height), (720, 1280))
            run_tool(["ffmpeg", "-nostdin", "-v", "error", "-i", str(output), "-f", "null", "-"])
            manifests.append(manifest)
        self.assertTrue(manifests[-1]["transcript_cache_hit"])
        ranking_config = root / "ranking-custom.json"
        ranking_config.write_text(json.dumps({
            "weights": {"audio_peak": 0, "audio_onset": 0, "speech_activity": 0, "transcript_cues": 1},
            "cues": {"en": ["subtitles"]}, "min_score": 0.5,
        }), encoding="utf-8")
        ranked = subprocess.run(
            [sys.executable, "-m", "autoclip", "clip", str(source), "--speech-ranking",
             "--ranking-config", str(ranking_config), "--count", "1", "--length", "15"],
            env=environment, capture_output=True, text=True, encoding="utf-8", timeout=240,
        )
        self.assertEqual(ranked.returncode, 0, ranked.stderr)
        ranked_path = Path(ranked.stdout.strip())
        ranked_manifest = json.loads(ranked_path.read_text(encoding="utf-8"))
        self.assertEqual(ranked_manifest["state"], "completed")
        self.assertEqual(ranked_manifest["caption_status"], "disabled")
        self.assertTrue(ranked_manifest["transcript_cache_hit"])
        self.assertEqual(len(ranked_manifest["clips"]), 1)
        self.assertEqual(ranked_manifest["clips"][0]["score"], 1)
        self.assertEqual(ranked_manifest["clips"][0]["evidence"]["cue_matches"], ["subtitles"])
        run_tool(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", "2", "-i", str(output),
                  "-frames:v", "1", str(root / "caption-preview.png")])


if __name__ == "__main__":
    unittest.main()
