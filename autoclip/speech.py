"""Offline multilingual CPU transcription and clip-relative subtitles."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import re
import textwrap
import unicodedata
import uuid

from .engine import ClipError, Media, Settings, check_cancelled, extract_audio, output_dimensions


@dataclass(frozen=True)
class SpeechSettings:
    model_dir: Path
    model_size: str = "base"
    language: str | None = None

    @classmethod
    def from_environment(cls, settings: Settings, language: str = "auto") -> SpeechSettings:
        size = os.environ.get("AUTOCLIP_MODEL_SIZE", "base")
        if size not in {"tiny", "base", "small"}:
            raise ClipError("AUTOCLIP_MODEL_SIZE must be tiny, base or small (multilingual).")
        if language != "auto" and not re.fullmatch(r"[a-z]{2,3}", language):
            raise ClipError("Language must be auto or a Whisper language code such as en or bn.")
        root = Path(os.environ.get("AUTOCLIP_MODEL_CACHE_DIR", str(settings.data_dir / "models")))
        return cls(root.expanduser().resolve() / size, size, None if language == "auto" else language)


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            check_cancelled()
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.stem}-{uuid.uuid4().hex}.partial.json")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_model(config: SpeechSettings) -> Path:
    """This explicit preparation command is the only model network operation."""
    try:
        from huggingface_hub import HfApi, snapshot_download
        repository = f"Systran/faster-whisper-{config.model_size}"
        revision = HfApi().model_info(repository).sha
        snapshot_download(
            repo_id=repository, revision=revision, local_dir=str(config.model_dir),
            allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.*",
                            "preprocessor_config.json"],
        )
        atomic_json(config.model_dir / "source.json", {
            "repository": repository, "revision": revision, "license": "MIT",
        })
        return config.model_dir
    except ImportError as exc:
        raise ClipError("Install requirements-speech.txt in the project virtual environment first.") from exc
    except Exception as exc:
        raise ClipError(f"Model preparation failed. Check the connection and retry. {exc}") from exc


def model_fingerprint(config: SpeechSettings) -> dict[str, str]:
    required = ("model.bin", "config.json", "tokenizer.json")
    if any(not (config.model_dir / name).is_file() for name in required):
        raise ClipError("Speech model is missing or incomplete. Run python -m autoclip prepare-model first.")
    files = [path for path in config.model_dir.iterdir()
             if path.name in required or path.name.startswith("vocabulary.")
             or path.name == "preprocessor_config.json"]
    return {path.name: digest_file(path) for path in sorted(files)}


def normalize_segments(segments: list[dict], duration: float) -> list[dict]:
    """Clamp timestamps and remove overlaps without changing transcript wording."""
    normalized = []
    previous_end = 0.0
    for segment in sorted(segments, key=lambda item: float(item["start"])):
        start, end = float(segment["start"]), float(segment["end"])
        if not math.isfinite(start) or not math.isfinite(end):
            raise ValueError("Nonfinite transcript timestamp")
        text = unicodedata.normalize("NFC", " ".join(str(segment["text"]).split()))
        start = round(max(previous_end, min(duration, max(0, start))), 3)
        end = round(min(duration, max(0, end)), 3)
        if text and end > start:
            normalized.append({"start": start, "end": end, "text": text})
            previous_end = end
    return normalized


def transcribe_media(media: Media, settings: Settings, config: SpeechSettings,
                     temporary: Path) -> dict:
    if not media.audio_present:
        return {"schema_version": 1, "language": None, "segments": [], "cache_hit": False}
    try:
        from faster_whisper import WhisperModel
        fingerprint = {
            "media_sha256": digest_file(media.path), "model": model_fingerprint(config),
            "language": config.language, "device": "cpu", "compute_type": "int8",
            "threads": settings.threads, "beam_size": 1, "vad_filter": True,
            "condition_on_previous_text": False,
            "faster_whisper": version("faster-whisper"), "ctranslate2": version("ctranslate2"),
            "onnxruntime": version("onnxruntime"), "av": version("av"), "schema_version": 1,
        }
        key = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
        cache = settings.data_dir / "transcripts" / f"{key}.json"
        if cache.is_file():
            try:
                cached = json.loads(cache.read_text(encoding="utf-8"))
                if cached["fingerprint"] == fingerprint and isinstance(cached["segments"], list):
                    cached["segments"] = normalize_segments(cached["segments"], media.duration)
                    cached["cache_hit"] = True
                    return cached
            except (ValueError, KeyError, TypeError, AttributeError):
                pass  # An incomplete or corrupt cache is regenerated.
        audio = temporary / "analysis.wav"
        if not audio.is_file():
            extract_audio(media, settings, audio)
        check_cancelled()
        model = WhisperModel(
            str(config.model_dir), device="cpu", compute_type="int8",
            cpu_threads=settings.threads, num_workers=1, local_files_only=True,
        )
        segments, info = model.transcribe(
            str(audio), language=config.language, beam_size=1, vad_filter=True,
            condition_on_previous_text=False, word_timestamps=False,
        )
        recognized = []
        for segment in segments:
            check_cancelled()
            recognized.append({"start": segment.start, "end": segment.end, "text": segment.text})
        check_cancelled()
        payload = {
            "schema_version": 1, "fingerprint": fingerprint,
            "language": info.language if recognized else None,
            "language_probability": info.language_probability if recognized else None,
            "segments": normalize_segments(recognized, media.duration), "cache_hit": False,
        }
        atomic_json(cache, payload)
        return payload
    except ImportError as exc:
        raise ClipError("Speech dependencies are missing. Use .venv and install requirements-speech.txt.") from exc
    except ClipError:
        raise
    except Exception as exc:
        raise ClipError(f"Local speech transcription failed. {exc}") from exc


def clip_segments(segments: list[dict], start: float, end: float) -> list[dict]:
    relative = [{"start": max(0, segment["start"] - start),
                 "end": min(end, segment["end"]) - start, "text": segment["text"]}
                for segment in segments if segment["start"] < end and segment["end"] > start]
    return normalize_segments(relative, end - start)


def validate_saved_transcript(payload: dict, expected_sha256: str, duration: float, *,
                              language: str = "auto") -> dict:
    """Validate a saved job transcript for revision reuse without model access.

    The worker supplies the managed import's recorded content hash. This helper
    neither hashes recordings/model weights nor loads paths supplied by clients.
    """
    if (not isinstance(expected_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)):
        raise ClipError("Saved transcript reuse requires a valid source content hash.")
    if (isinstance(duration, bool) or not isinstance(duration, (int, float))
            or not math.isfinite(duration) or duration <= 0):
        raise ClipError("Saved transcript reuse requires a valid media duration.")
    if not isinstance(language, str) or not re.fullmatch(r"auto|[a-z]{2,3}", language):
        raise ClipError("Saved transcript language setting is invalid.")
    if (not isinstance(payload, dict) or type(payload.get("schema_version")) is not int
            or payload["schema_version"] != 1):
        raise ClipError("Saved transcript has an unsupported or missing schema version.")
    fingerprint = payload.get("fingerprint")
    if not isinstance(fingerprint, dict) or fingerprint.get("media_sha256") != expected_sha256:
        raise ClipError("Saved transcript does not match the imported recording.")
    requested_language = None if language == "auto" else language
    if "language" not in fingerprint or fingerprint["language"] != requested_language:
        raise ClipError("Saved transcript language settings do not match this revision.")
    detected_language = payload.get("language")
    if detected_language is not None and (
            not isinstance(detected_language, str) or not re.fullmatch(r"[a-z]{2,3}", detected_language)):
        raise ClipError("Saved transcript contains an invalid detected language.")
    segments = payload.get("segments")
    if not isinstance(segments, list):
        raise ClipError("Saved transcript segments must be a list.")
    for segment in segments:
        if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
            raise ClipError("Saved transcript contains an invalid speech segment.")
        for name in ("start", "end"):
            value = segment.get(name)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value)):
                raise ClipError("Saved transcript contains invalid segment timestamps.")
        if not 0 <= segment["start"] < segment["end"] <= duration:
            raise ClipError("Saved transcript timestamps extend outside the recording.")
    return {**payload, "fingerprint": dict(fingerprint),
            "segments": normalize_segments(segments, duration),
            "cache_hit": True, "reuse_kind": "saved_job"}


def subtitle_time(seconds: float, *, ass: bool = False) -> str:
    scale = 100 if ass else 1000
    units = max(0, round(seconds * scale))
    whole, fraction = divmod(units, scale)
    minutes, second = divmod(whole, 60)
    hours, minute = divmod(minutes, 60)
    if ass:
        return f"{hours}:{minute:02}:{second:02}.{fraction:02}"
    return f"{hours:02}:{minute:02}:{second:02},{fraction:03}"


def write_subtitles(segments: list[dict], start: float, end: float, stem: Path, *,
                    resolution: int = 720, aspect_ratio: str = "9:16",
                    framing=None, layout_mode: str | None = None, framing_plan=None) -> Path | None:
    width, height = output_dimensions(resolution, aspect_ratio)
    relative = clip_segments(segments, start, end)
    if not relative:
        return None
    srt = []
    font = os.environ.get("AUTOCLIP_CAPTION_FONT", "Arial")
    if any(character in font for character in ",\n\r"):
        raise ClipError("Caption font must be a font family name without commas or newlines.")
    scale = resolution / 720
    font_size = round((44 if aspect_ratio == "9:16" else 32) * scale)
    margin_horizontal = round(50 * scale)
    margin_vertical = round((100 if aspect_ratio == "9:16" else 56) * scale)
    outline, shadow = round(3 * scale), max(1, round(scale))
    position_override = ""
    if framing is not None:
        from .reframing import FramingSettings
        if not isinstance(framing, FramingSettings):
            raise ClipError("Subtitle placement requires validated framing settings.")
        margin_horizontal = max(margin_horizontal, round(width * framing.safe_margin_horizontal))
        top = max(font_size * 1.5, height * framing.safe_margin_top + font_size)
        bottom = min(height - font_size * 1.5, height * (1 - framing.safe_margin_bottom) - font_size)
        position = framing.subtitle_position
        if position == "top":
            y = top
        elif position == "center":
            y = (top + bottom) / 2
        elif position == "auto" and layout_mode == "streamer_gameplay":
            from .composition import split_panel_heights
            panel_boundary, _ = split_panel_heights(height)
            y = max(top, min(bottom, panel_boundary + font_size))
        elif position == "auto" and layout_mode == "full_gameplay" and aspect_ratio == "9:16":
            y = max(top, min(bottom, height * 0.78))
        elif position == "auto" and layout_mode == "hybrid_focus" and framing_plan is not None:
            crop = framing_plan.keyframes[0].crop
            foreground_height = min(height, width * crop.height / crop.width)
            if top + font_size <= (height - foreground_height) / 2 and bottom - font_size < (height + foreground_height) / 2:
                y = top
            else:
                y = bottom
        else:
            y = bottom
        position_override = f"{{\\an5\\pos({width // 2},{round(y)})}}"
    ass = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 0", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{font},{font_size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,{outline},{shadow},2,{margin_horizontal},{margin_horizontal},{margin_vertical},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for index, segment in enumerate(relative, 1):
        text = segment["text"]
        srt.append(f"{index}\n{subtitle_time(segment['start'])} --> {subtitle_time(segment['end'])}\n"
                   f"{html.escape(text, quote=False)}\n")
        # ASS interprets backslashes and braces as commands. Fullwidth glyphs keep
        # transcript content readable while preventing caption style injection.
        safe = text.translate(str.maketrans({"\\": "＼", "{": "｛", "}": "｝"}))
        chunks = [safe]
        if framing is not None:
            # Keep at most two lines visible; narrow safe areas need shorter lines.
            characters = max(6, min(32 if aspect_ratio == "9:16" else 56,
                                   int((width - 2 * margin_horizontal) / (font_size * 0.7))))
            lines = textwrap.wrap(safe, width=characters) or [safe]
            chunks = [r"\N".join(lines[offset:offset + 2]) for offset in range(0, len(lines), 2)]
        total = sum(len(chunk) for chunk in chunks)
        elapsed = 0
        for chunk in chunks:
            chunk_start = segment["start"] + (segment["end"] - segment["start"]) * elapsed / total
            elapsed += len(chunk)
            chunk_end = segment["start"] + (segment["end"] - segment["start"]) * elapsed / total
            ass_start = subtitle_time(chunk_start, ass=True)
            ass_end = subtitle_time(chunk_end, ass=True)
            if ass_start != ass_end:
                ass.append(f"Dialogue: 0,{ass_start},{ass_end},Default,,0,0,0,,{position_override}{chunk}")
    stem.with_suffix(".srt").write_text("\n".join(srt), encoding="utf-8")
    ass_path = stem.with_suffix(".ass")
    ass_path.write_text("\n".join(ass) + "\n", encoding="utf-8")
    return ass_path
