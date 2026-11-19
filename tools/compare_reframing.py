"""Local acceptance aid: python -m tools.compare_reframing SOURCE_DIRECTORY.

Writes only ignored local-data/reframing-acceptance. Does not transcribe or
choose semantic highlights. The split example is a manual region demonstration.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import time
import uuid

from autoclip.engine import Candidate, Settings, inspect_media, render_clip
from autoclip.reframing import FramingSettings, Region
from autoclip.speech import digest_file, write_subtitles
from autoclip.vision import analyze_candidate, plan_from_analysis


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_directory", type=Path)
    parser.add_argument("--start", type=float, default=5)
    args = parser.parse_args()
    base = Path("local-data/reframing-acceptance").resolve()
    base.mkdir(parents=True, exist_ok=True)
    root = base / (time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
    root.mkdir()
    settings = Settings(base)
    print(f"Output: {root.relative_to(Path.cwd())}", flush=True)
    results = []
    files = sorted(p for p in args.source_directory.iterdir() if p.suffix.lower() in {".mp4", ".mkv"})[:3]
    for index, source in enumerate(files, 1):
        media = inspect_media(source, settings)
        candidate = Candidate(args.start, args.start + 15, 1, {})
        if candidate.end > media.duration:
            raise ValueError("Source must contain the selected 15-second interval.")
        before = time.perf_counter()
        analysis = analyze_candidate(media, candidate.start, candidate.end, settings, source_sha256=digest_file(source))
        analysis_seconds = time.perf_counter() - before
        modes = ["center", "auto", "smart_crop"]
        if index == 1:
            modes += ["full_gameplay", "streamer_gameplay"]
        for mode in modes:
            options = FramingSettings(mode=mode) if mode != "center" else None
            if mode == "streamer_gameplay":
                options = FramingSettings(mode=mode, webcam_region=Region(.35, .35, .3, .4))
            plan, effective = (None, None) if options is None else plan_from_analysis(
                media, candidate.start, candidate.end, options, analysis)
            destination = root / f"source-{index}-{mode}.mp4"
            subtitle = None
            if index == 1 and mode == "full_gameplay":
                subtitle = write_subtitles([{"start": candidate.start + 1, "end": candidate.start + 7,
                                            "text": "Caption placement demonstration: full gameplay remains visible."}],
                                           candidate.start, candidate.end, destination.with_suffix(""),
                                           framing=options, layout_mode="full_gameplay")
            reused = destination.exists()
            before = time.perf_counter()
            if not reused:
                render_clip(media, candidate, destination, settings, layout="crop", framing_plan=plan,
                            framing_settings=effective, subtitle_path=subtitle)
            seconds = None if reused else round(time.perf_counter() - before, 3)
            metadata = json.loads(subprocess.check_output([
                settings.ffprobe, "-v", "error", "-show_streams", "-of", "json", str(destination)]))
            video = next(s for s in metadata["streams"] if s["codec_type"] == "video")
            audio = next(s for s in metadata["streams"] if s["codec_type"] == "audio") if media.audio_present else None
            subprocess.run([settings.ffmpeg, "-nostdin", "-v", "error", "-i", str(destination),
                            "-f", "null", "-"], check=True, timeout=120)
            subprocess.run([settings.ffmpeg, "-nostdin", "-v", "error", "-y", "-ss", "3", "-i", str(destination),
                            "-frames:v", "1", "-vf", "scale=360:640", str(destination.with_suffix(".jpg"))],
                           check=True, timeout=60)
            row = {"source": index, "requested": mode, "selected": plan.selected_mode if plan else "center",
                   "analysis_seconds": round(analysis_seconds, 3), "analysis_cache_hit": analysis["cache_hit"],
                   "render_seconds": seconds, "reused_output": reused, "dimensions": [video["width"], video["height"]],
                   "duration": float(video["duration"]), "scenes": analysis["scene_count"],
                   "av_start_delta": abs(float(video.get("start_time", 0)) - float(audio.get("start_time", 0))) if audio else None,
                   "av_duration_delta": abs(float(video["duration"]) - float(audio["duration"])) if audio else None,
                   "plan": asdict(plan) if plan else None,
                   "note": "Manual region demonstration, not a detected webcam." if mode == "streamer_gameplay" else None}
            results.append(row)
            (root / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
            print(json.dumps({k: v for k, v in row.items() if k != "plan"}), flush=True)


if __name__ == "__main__":
    main()
