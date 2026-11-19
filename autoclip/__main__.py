"""Run with python -m autoclip."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from .engine import ClipError, Settings, inspect_media, process, run_tool


def main() -> int:
    parser = argparse.ArgumentParser(description="Local CPU video candidate clipping.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("health", help="Verify FFmpeg, FFprobe and required encoding filters.")
    commands.add_parser("prepare-model", help="Download the configured multilingual model once.")
    server = commands.add_parser("serve", help="Run the local API and durable job worker.")
    server.add_argument("--port", type=int, default=8000)
    inspect = commands.add_parser("inspect", help="Validate an MP4/MKV and display metadata.")
    inspect.add_argument("input", type=Path)
    from .engine import ASPECT_RATIOS, COMPRESSION_CRF, RESOLUTIONS

    clip = commands.add_parser("clip", help="Find audio candidates and render MP4 clips.")
    clip.add_argument("input", type=Path)
    clip.add_argument("--count", type=int, choices=range(1, 11), default=3)
    clip.add_argument("--length", type=float, default=30, help="Candidate length in seconds, 15–60.")
    clip.add_argument("--layout", choices=["pad", "crop"], default="pad")
    clip.add_argument("--aspect-ratio", choices=tuple(ASPECT_RATIOS), default="9:16",
                      help="Output video shape.")
    clip.add_argument("--resolution", type=int, choices=RESOLUTIONS, default=720,
                      help="Output resolution tier.")
    clip.add_argument("--compression", choices=tuple(COMPRESSION_CRF), default="balanced",
                      help="H.264 compression profile.")
    clip.add_argument("--fps", type=int, choices=[30, 60], default=30)
    clip.add_argument("--start", type=float, help="Manual trim start in seconds.")
    clip.add_argument("--end", type=float, help="Manual trim end in seconds.")
    clip.add_argument("--captions", action="store_true", help="Transcribe locally and burn in captions.")
    clip.add_argument("--language", default="auto", help="auto or a Whisper language code such as en or bn.")
    clip.add_argument("--speech-ranking", action="store_true", help="Use local speech for ranking without requiring captions.")
    clip.add_argument("--ranking-config", type=Path, help="JSON overrides for ranking weights, thresholds and cue phrases.")
    args = parser.parse_args()
    try:
        settings = Settings.from_environment()
        if args.command == "health":
            ffmpeg = run_tool([settings.ffmpeg, "-version"], timeout=15).splitlines()[0]
            ffprobe = run_tool([settings.ffprobe, "-version"], timeout=15).splitlines()[0]
            encoders = run_tool([settings.ffmpeg, "-v", "error", "-encoders"], timeout=15)
            filters = run_tool([settings.ffmpeg, "-v", "error", "-filters"], timeout=15)
            if "libx264" not in encoders or " aac " not in encoders:
                raise ClipError("FFmpeg needs libx264 and AAC encoders.")
            if any(name not in filters for name in ("scale", "pad", "crop", "subtitles")):
                raise ClipError("FFmpeg needs scale, pad, crop and subtitles filters.")
            print(json.dumps({"status": "ok", "ffmpeg": ffmpeg, "ffprobe": ffprobe,
                              "threads": settings.threads}, indent=2))
        elif args.command == "serve":
            if not 1 <= args.port <= 65535:
                raise ClipError("Server port must be between 1 and 65535.")
            try:
                import uvicorn
                from .api import create_app
            except ImportError as exc:
                raise ClipError("Install requirements-backend.txt in the project virtual environment first.") from exc
            uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port,
                        workers=1, proxy_headers=False)
        elif args.command == "prepare-model":
            from .engine import worker_lock
            from .speech import SpeechSettings, prepare_model
            with worker_lock(settings.data_dir):
                print(prepare_model(SpeechSettings.from_environment(settings)))
        elif args.command == "inspect":
            print(json.dumps(asdict(inspect_media(args.input, settings)), default=str, indent=2))
        else:
            manifest = process(args.input, settings, count=args.count, clip_length=args.length,
                               layout=args.layout, resolution=args.resolution, fps=args.fps,
                               aspect_ratio=args.aspect_ratio, compression=args.compression,
                               start=args.start, end=args.end,
                               captions=args.captions, language=args.language,
                               speech_ranking=args.speech_ranking, ranking_config=args.ranking_config)
            print(manifest)
        return 0
    except (ClipError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Cancelled. Any unfinished clip was removed.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
