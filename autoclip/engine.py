"""Validated media inspection, audio candidates, and atomic clip exports."""

from __future__ import annotations

import array
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import TYPE_CHECKING, Callable
import uuid
import wave

from . import __version__

if TYPE_CHECKING:
    from .ranking import RankingSettings
    from .reframing import FramingPlan, FramingSettings


class ClipError(Exception):
    """An actionable failure suitable for display to a user."""


class JobCancelled(ClipError):
    """Cooperative cancellation requested by a background job owner."""


_cancelled: ContextVar[Callable[[], bool] | None] = ContextVar("autoclip_cancelled", default=None)
_progress: ContextVar[Callable[[dict], None] | None] = ContextVar("autoclip_progress", default=None)


def check_cancelled() -> None:
    callback = _cancelled.get()
    if callback is not None and callback():
        raise JobCancelled("Cancelled by user or server shutdown.")


@contextmanager
def processing_control(cancelled, progress):
    cancel_token = _cancelled.set(cancelled)
    progress_token = _progress.set(progress)
    try:
        check_cancelled()
        yield
    finally:
        _cancelled.reset(cancel_token)
        _progress.reset(progress_token)


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    threads: int = 4
    max_bytes: int = 100 * 1024**3
    max_duration: int = 4 * 60 * 60

    @classmethod
    def from_environment(cls) -> Settings:
        try:
            threads = int(os.environ.get("AUTOCLIP_WORKER_THREADS", "4"))
        except ValueError as exc:
            raise ClipError("AUTOCLIP_WORKER_THREADS must be an integer.") from exc
        if not 1 <= threads <= 32:
            raise ClipError("Worker threads must be between 1 and 32.")
        return cls(
            Path(os.environ.get("AUTOCLIP_DATA_DIR", "local-data")).resolve(),
            os.environ.get("AUTOCLIP_FFMPEG_PATH", "ffmpeg"),
            os.environ.get("AUTOCLIP_FFPROBE_PATH", "ffprobe"),
            threads,
        )


@dataclass(frozen=True)
class Media:
    path: Path
    duration: float
    width: int
    height: int
    codec: str
    audio_present: bool
    size_bytes: int
    sample_aspect_ratio: str = "1:1"
    rotation: float | None = 0.0


@dataclass(frozen=True)
class Candidate:
    start: float
    end: float
    score: float
    evidence: dict[str, object]


def run_tool(arguments: list[str], timeout: float = 3600, *, cwd: Path | None = None) -> str:
    """Use argument arrays, bounded diagnostics, and automatic child cleanup."""
    try:
        check_cancelled()
        with tempfile.TemporaryFile() as errors, tempfile.TemporaryFile() as output:
            with subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=output,
                                  stderr=errors, cwd=cwd) as child:
                deadline = time.monotonic() + timeout
                try:
                    while child.poll() is None:
                        check_cancelled()
                        if time.monotonic() >= deadline:
                            raise subprocess.TimeoutExpired(arguments, timeout)
                        try:
                            child.wait(timeout=0.2)
                        except subprocess.TimeoutExpired:
                            pass
                except BaseException:
                    child.kill()
                    child.wait()
                    raise
            check_cancelled()
            if child.returncode:
                errors.seek(0, os.SEEK_END)
                errors.seek(max(0, errors.tell() - 4000))
                detail = errors.read().decode("utf-8", errors="replace").strip()
                raise ClipError(f"{Path(arguments[0]).name} failed. {detail}")
            output.seek(0)
            return output.read().decode("utf-8", errors="replace")
    except FileNotFoundError as exc:
        raise ClipError(f"Missing executable: {arguments[0]}. Install it or configure its path.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ClipError(f"{Path(arguments[0]).name} exceeded its {timeout:g}s time limit.") from exc
    except OSError as exc:
        raise ClipError(f"Could not execute {arguments[0]}: {exc}") from exc


def inspect_media(path: Path, settings: Settings) -> Media:
    path = path.expanduser().resolve()
    if path.suffix.lower() not in {".mp4", ".mkv"}:
        raise ClipError("Choose an MP4 or MKV recording.")
    if not path.is_file():
        raise ClipError("The recording does not exist or is not a regular file.")
    size = path.stat().st_size
    if not 0 < size <= settings.max_bytes:
        raise ClipError("The recording is empty or exceeds the configured input size limit.")
    raw = run_tool([
        settings.ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe",
        "-show_format", "-show_streams", "-of", "json", str(path),
    ], timeout=30)
    try:
        metadata = json.loads(raw)
        container = metadata["format"]
        formats = container["format_name"].split(",")
        if not {"mov", "mp4", "matroska"}.intersection(formats):
            raise ClipError("The file contents must be an MP4 or Matroska container.")
        videos = [s for s in metadata["streams"] if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")]
        if not videos:
            raise ClipError("The recording has no video stream.")
        video = videos[0]
        duration = float(video.get("duration") or container["duration"])
        width, height = int(video["width"]), int(video["height"])
        if not math.isfinite(duration) or not 0 < duration <= settings.max_duration:
            raise ClipError("Recording duration must be positive and within the configured duration limit.")
        if not 0 < width <= 8192 or not 0 < height <= 8192:
            raise ClipError("Video dimensions must be between 1 and 8192 pixels.")
        tags = video.get("tags", {})
        tags = tags if isinstance(tags, dict) else {}
        side_data = video.get("side_data_list", [])
        side_data = side_data if isinstance(side_data, list) else []
        rotation_value = next((item["rotation"] for item in side_data
                               if isinstance(item, dict) and "rotation" in item), tags.get("rotate", 0))
        try:
            rotation = float(rotation_value)
        except (ValueError, TypeError, OverflowError):
            rotation = None
        # Unspecified SAR follows the existing square-pixel interpretation.
        sample_aspect_ratio = video.get("sample_aspect_ratio")
        if sample_aspect_ratio in {None, "N/A"}:
            sample_aspect_ratio = "1:1"
        return Media(path, duration, width, height, video.get("codec_name", "unknown"),
                     any(s.get("codec_type") == "audio" for s in metadata["streams"]), size,
                     str(sample_aspect_ratio), rotation)
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        raise ClipError("The recording has invalid or incomplete media metadata.") from exc


def extract_audio(media: Media, settings: Settings, audio: Path) -> None:
    run_tool([
        settings.ffmpeg, "-nostdin", "-v", "error", "-y",
        "-threads", str(settings.threads), "-protocol_whitelist", "file,pipe",
        "-i", str(media.path), "-t", str(media.duration), "-map", "0:a:0", "-vn", "-ac", "1",
        "-ar", "16000", "-c:a", "pcm_s16le", str(audio),
    ])


def audio_activity(media: Media, settings: Settings, temporary: Path) -> list[float]:
    if not media.audio_present:
        return []
    audio = temporary / "analysis.wav"
    extract_audio(media, settings, audio)
    activity = []
    with wave.open(str(audio), "rb") as source:
        while frames := source.readframes(16000):
            check_cancelled()
            samples = array.array("h", frames)
            if sys.byteorder != "little":
                samples.byteswap()
            rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768
            activity.append(rms)
    return activity


def select_candidates(activity: list[float], duration: float, clip_length: float = 30,
                      count: int = 3, *, segments: list[dict] | None = None,
                      language: str | None = None, config: RankingSettings | None = None) -> list[Candidate]:
    from .ranking import rank_candidates
    return rank_candidates(activity, duration, clip_length, count,
                           segments=segments, language=language, config=config)


ASPECT_RATIOS = {"9:16": (9, 16), "16:9": (16, 9), "1:1": (1, 1), "4:5": (4, 5)}
RESOLUTIONS = (480, 720, 1080)
COMPRESSION_CRF = {"higher_quality": 19, "balanced": 23, "smaller_file": 28}


def compression_crf(compression: str) -> int:
    try:
        return COMPRESSION_CRF[compression]
    except KeyError:
        raise ClipError("Choose Higher Quality, Balanced, or Smaller File compression.") from None


def output_dimensions(resolution: int, aspect_ratio: str = "9:16") -> tuple[int, int]:
    if resolution not in RESOLUTIONS or aspect_ratio not in ASPECT_RATIOS:
        raise ClipError("Choose 480/720/1080 resolution and a 9:16, 16:9, 1:1, or 4:5 aspect ratio.")
    ratio_width, ratio_height = ASPECT_RATIOS[aspect_ratio]
    short_component = min(ratio_width, ratio_height)
    long_component = max(ratio_width, ratio_height)
    # Round up to an even long side for H.264 with 4:2:0 chroma.
    long_side = (resolution * long_component + short_component - 1) // short_component
    long_side += long_side % 2
    return (resolution, long_side) if ratio_width <= ratio_height else (long_side, resolution)


def video_filter(layout: str, resolution: int, aspect_ratio: str = "9:16") -> str:
    if layout not in {"pad", "crop"}:
        raise ClipError("Choose pad or crop layout.")
    width, height = output_dimensions(resolution, aspect_ratio)
    center_crop = ""
    if layout == "crop":
        # Crop in source pixels before scaling, accounting for anamorphic input.
        center_crop = (f"crop=w='max(1,min(iw,ih*{width}/({height}*sar)))':"
                       f"h='max(1,min(ih,iw*sar*{height}/{width}))':exact=1,")
    return (f"{center_crop}scale=w='max(2,min(iw*sar,{width}))':"
            f"h='max(2,min(ih,{height}))':force_original_aspect_ratio=decrease:"
            f"force_divisible_by=2:reset_sar=1,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1")


def validate_framing_source(media: Media) -> None:
    try:
        sar_width, sar_height = (int(part) for part in media.sample_aspect_ratio.split(":"))
    except (ValueError, AttributeError):
        raise ClipError("Framing requires known square-pixel source geometry.") from None
    if sar_width <= 0 or sar_height <= 0 or sar_width != sar_height:
        raise ClipError("Framing currently requires square-pixel source video; normalize pixel aspect first.")
    if (media.rotation is None or not math.isfinite(media.rotation)
            or not math.isclose(math.remainder(media.rotation, 360), 0, rel_tol=0, abs_tol=1e-6)):
        raise ClipError("Framing currently requires unrotated source video; normalize orientation first.")


def render_clip(media: Media, candidate: Candidate, destination: Path, settings: Settings,
                layout: str = "pad", resolution: int = 720, fps: int = 30,
                subtitle_path: Path | None = None, *, aspect_ratio: str = "9:16",
                compression: str = "balanced",
                framing_plan: FramingPlan | None = None,
                framing_settings: FramingSettings | None = None) -> None:
    start, end = candidate.start, candidate.end
    if not all(math.isfinite(value) for value in (start, end)):
        raise ClipError("Clip timestamps must be finite.")
    if not 0 <= start < end <= media.duration or not 15 <= end - start <= 60:
        raise ClipError("Clip timestamps must stay inside the recording and span 15–60 seconds.")
    if fps not in {30, 60}:
        raise ClipError("Output FPS must be 30 or 60.")
    crf = compression_crf(compression)
    filters = video_filter(layout, resolution, aspect_ratio)
    composition = None
    if (framing_plan is None) != (framing_settings is None):
        raise ClipError("Framing rendering requires both a plan and settings.")
    if framing_plan is not None:
        from .composition import build_filtergraph
        from .reframing import FramingPlan
        if not isinstance(framing_plan, FramingPlan):
            raise ClipError("Framing plan must be a validated record.")
        validate_framing_source(media)
        if (framing_plan.source_width, framing_plan.source_height) != (media.width, media.height):
            raise ClipError("Framing plan dimensions do not match the source media.")
        if (not math.isclose(framing_plan.start, start, rel_tol=0, abs_tol=1e-6)
                or not math.isclose(framing_plan.end, end, rel_tol=0, abs_tol=1e-6)):
            raise ClipError("Framing plan interval does not match the selected clip.")
        composition = build_filtergraph(framing_plan, framing_settings,
                                       resolution=resolution, aspect_ratio=aspect_ratio)
        filters = composition.filtergraph
    video_mapping = composition.output_label if composition is not None else "0:V:0"
    destination = destination.resolve()
    tool_options = {}
    if subtitle_path is not None:
        subtitle_path = subtitle_path.resolve()
        if (subtitle_path.parent != destination.parent or not subtitle_path.is_file()
                or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
                       for character in subtitle_path.name)):
            raise ClipError("Subtitle files must use a safe generated name in the clip directory.")
        if composition is None:
            filters += f",ass=filename={subtitle_path.name}"
        else:
            filters += f";{composition.output_label}ass=filename={subtitle_path.name}[captioned]"
            video_mapping = "[captioned]"
        tool_options["cwd"] = destination.parent
    if destination.exists():
        raise ClipError("The output clip already exists. Choose a new destination.")
    partial = destination.with_name(f".{destination.stem}-{uuid.uuid4().hex}.partial.mp4")
    filter_options = (["-filter_threads", "1", "-vf", filters] if composition is None else
                      ["-filter_complex_threads", "1", "-filter_complex", filters])
    try:
        run_tool([
            settings.ffmpeg, "-nostdin", "-v", "error", "-n",
            "-threads", str(settings.threads), "-protocol_whitelist", "file,pipe",
            "-ss", f"{start:.6f}", "-i", str(media.path), "-t", f"{end - start:.6f}",
            "-map", video_mapping, "-map", "0:a:0?", "-sn", "-dn",
            "-map_metadata", "-1", "-map_chapters", "-1", *filter_options,
            "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast",
            "-crf", str(crf), "-pix_fmt", "yuv420p", "-threads", str(settings.threads),
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(partial),
        ], **tool_options)
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)


@contextmanager
def worker_lock(data_dir: Path, filename: str = ".worker.lock"):
    """An OS lock is released even when a worker exits unexpectedly."""
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / filename).open("a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            label = "server" if filename == ".server.lock" else "clipping job"
            raise ClipError(f"Another {label} is running in this data directory.") from exc
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def write_manifest(directory: Path, manifest: dict) -> None:
    temporary = directory / "manifest.partial.json"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(directory / "manifest.json")
    callback = _progress.get()
    if callback is not None:
        callback(manifest)


def process(path: Path, settings: Settings, *, count: int = 3, clip_length: float = 30,
            layout: str = "pad", resolution: int = 720, fps: int = 30,
            aspect_ratio: str = "9:16", compression: str = "balanced",
            framing: FramingSettings | None = None,
            start: float | None = None, end: float | None = None,
            captions: bool = False, language: str = "auto", speech_ranking: bool = False,
            saved_transcript: dict | None = None, source_sha256: str | None = None,
            ranking_config: Path | None = None, output_id: str | None = None,
            cancelled: Callable[[], bool] | None = None,
            progress_callback: Callable[[dict], None] | None = None) -> Path:
    from .ranking import RankingSettings
    if framing is not None:
        from .reframing import FramingSettings
        if not isinstance(framing, FramingSettings):
            raise ClipError("Processing requires validated framing settings.")
    ranking = RankingSettings.from_file(ranking_config)
    video_filter(layout, resolution, aspect_ratio)
    crf = compression_crf(compression)
    if not math.isfinite(clip_length) or not 15 <= clip_length <= 60 or not 1 <= count <= 10:
        raise ClipError("Choose 1–10 clips and a clip length between 15 and 60 seconds.")
    if fps not in {30, 60}:
        raise ClipError("Output FPS must be 30 or 60.")
    if (start is None) != (end is None):
        raise ClipError("Manual trimming requires both --start and --end.")
    if saved_transcript is not None and (start is None or not (captions or speech_ranking)):
        raise ClipError("Saved transcript reuse requires an explicit interval and enabled speech processing.")
    if output_id is not None and (len(output_id) != 32 or any(c not in "0123456789abcdef" for c in output_id)):
        raise ClipError("Output identifier must be a lowercase UUID hex string.")
    with processing_control(cancelled, progress_callback), worker_lock(settings.data_dir):
        media = inspect_media(path, settings)
        if shutil.disk_usage(settings.data_dir).free < 512 * 1024**2 + media.duration * 32000:
            raise ClipError("Insufficient free space for temporary audio and clip output.")
        job_dir = settings.data_dir / "clips" / (output_id or uuid.uuid4().hex)
        job_dir.mkdir(parents=True)
        manifest = {"schema_version": 1, "app_version": __version__, "state": "running", "phase": "analysis", "progress_pct": 5,
                    "input_filename": media.path.name, "duration_seconds": media.duration,
                    "audio_present": media.audio_present, "clips": [],
                    "settings": {"layout": layout, "resolution": resolution, "fps": fps,
                                 "aspect_ratio": aspect_ratio, "compression": compression, "crf": crf,
                                 "threads": settings.threads, "clip_length": clip_length,
                                 "max_clips": count, "speech_ranking": speech_ranking or captions,
                                 "ranking": asdict(ranking)},
                    "caption_status": "requested" if captions else "disabled"}
        if framing is not None:
            manifest["settings"]["framing"] = asdict(framing)
        started = time.perf_counter()
        write_manifest(job_dir, manifest)
        try:
            transcript = {"segments": []}
            with tempfile.TemporaryDirectory(prefix="analysis-", dir=settings.data_dir) as temporary:
                activity = []
                if start is not None:
                    candidates = [Candidate(start, end, 0.0, {})]
                else:
                    activity = audio_activity(media, settings, Path(temporary))
                if captions or speech_ranking:
                    from .speech import SpeechSettings, atomic_json, transcribe_media, validate_saved_transcript
                    if saved_transcript is not None:
                        manifest.update(phase="reusing_transcript", progress_pct=20)
                        write_manifest(job_dir, manifest)
                        transcript = validate_saved_transcript(saved_transcript, source_sha256,
                                                               media.duration, language=language)
                        manifest["transcript_reuse_kind"] = "saved_job"
                        print("Reusing saved transcript", file=sys.stderr, flush=True)
                    else:
                        config = SpeechSettings.from_environment(settings, language)
                        manifest.update(phase="transcribing", progress_pct=20)
                        write_manifest(job_dir, manifest)
                        print("Transcribing locally on CPU", file=sys.stderr, flush=True)
                        transcript = transcribe_media(media, settings, config, Path(temporary))
                    atomic_json(job_dir / "transcript.json", transcript)
                    manifest["transcript_file"] = "transcript.json"
                    manifest["transcript_cache_hit"] = transcript.get("cache_hit", False)
                    manifest["language"] = transcript.get("language")
                    if captions:
                        manifest["caption_status"] = "ready" if transcript["segments"] else "no_speech"
                if start is None:
                    check_cancelled()
                    manifest.update(phase="ranking", progress_pct=65)
                    write_manifest(job_dir, manifest)
                    candidates = select_candidates(
                        activity, media.duration, clip_length, count,
                        segments=transcript["segments"], language=transcript.get("language"), config=ranking,
                    )
            check_cancelled()
            manifest.update(phase="rendering", progress_pct=75)
            write_manifest(job_dir, manifest)
            visual_source_hash = source_sha256
            for index, candidate in enumerate(candidates, 1):
                check_cancelled()
                framing_plan = None
                effective_framing = framing
                visual_analysis = None
                if framing is not None:
                    from .reframing import uses_visual_analysis
                    from .vision import plan_candidate_framing
                    manifest["phase"] = "framing"
                    write_manifest(job_dir, manifest)
                    if visual_source_hash is None and uses_visual_analysis(framing):
                        from .speech import digest_file
                        try:
                            visual_source_hash = digest_file(media.path)
                        except OSError:
                            pass  # The planner reports unavailable analysis and uses its static fallback.
                    framing_plan, effective_framing, visual_analysis = plan_candidate_framing(
                        media, candidate.start, candidate.end, framing, settings, aspect_ratio=aspect_ratio,
                        source_sha256=visual_source_hash)
                    check_cancelled()
                    manifest["phase"] = "rendering"
                    write_manifest(job_dir, manifest)
                filename = f"clip-{index:02d}.mp4"
                print(f"Rendering clip {index}/{len(candidates)}", file=sys.stderr, flush=True)
                subtitle_path = None
                if captions:
                    from .speech import write_subtitles
                    subtitle_path = write_subtitles(transcript["segments"], candidate.start,
                                                    candidate.end, (job_dir / filename).with_suffix(""),
                                                    resolution=resolution, aspect_ratio=aspect_ratio,
                                                    **({"framing": effective_framing,
                                                        "layout_mode": framing_plan.selected_mode,
                                                        **({"framing_plan": framing_plan}
                                                           if framing_plan.selected_mode == "hybrid_focus" else {})}
                                                       if framing_plan else {}))
                framing_options = ({"framing_plan": framing_plan, "framing_settings": effective_framing}
                                   if framing_plan is not None else {})
                render_clip(media, candidate, job_dir / filename, settings, layout, resolution, fps,
                            subtitle_path=subtitle_path, aspect_ratio=aspect_ratio,
                            compression=compression, **framing_options)
                manifest["clips"].append({**asdict(candidate), "file": filename,
                                          "subtitle_file": subtitle_path.name if subtitle_path else None,
                                          "srt_file": subtitle_path.with_suffix(".srt").name if subtitle_path else None,
                                          "review_state": "proposed"})
                if framing_plan is not None:
                    manifest["clips"][-1]["framing"] = asdict(framing_plan)
                    manifest["clips"][-1]["effective_framing"] = asdict(effective_framing)
                    if visual_analysis is not None:
                        manifest["clips"][-1]["visual_analysis"] = {
                            key: value for key, value in visual_analysis.items() if key != "samples"}
                manifest["progress_pct"] = 75 + int(20 * index / len(candidates))
                write_manifest(job_dir, manifest)
            check_cancelled()
            manifest["state"] = "completed"
            manifest["phase"] = "done"
            manifest["progress_pct"] = 100
            if not candidates:
                manifest["diagnostic"] = "No candidate met the configured ranking threshold, or media is shorter than 15s."
        except (KeyboardInterrupt, JobCancelled):
            manifest.update(state="cancelled", phase="cancelled", error="Cancelled by user.")
            raise
        except (ClipError, OSError) as exc:
            manifest.update(state="failed", error=str(exc))
            raise
        finally:
            manifest["elapsed_seconds"] = round(time.perf_counter() - started, 3)
            write_manifest(job_dir, manifest)
        return job_dir / "manifest.json"
