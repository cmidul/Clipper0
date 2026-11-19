"""Deterministic audio/speech heuristics with inspectable score contributions."""

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import statistics
import unicodedata

from .engine import Candidate, ClipError


FEATURES = ("audio_peak", "audio_onset", "speech_activity", "transcript_cues")


@dataclass(frozen=True)
class RankingSettings:
    weights: dict[str, float] = field(default_factory=lambda: {
        "audio_peak": 0.45, "audio_onset": 0.20,
        "speech_activity": 0.10, "transcript_cues": 0.25,
    })
    min_score: float = 0.25
    min_gap_seconds: float = 2.0
    max_iou: float = 0.2
    cues: dict[str, list[str]] = field(default_factory=lambda: {
        "en": ["unbelievable", "no way", "let's go", "amazing", "help me"],
        "bn": ["অবিশ্বাস্য", "দারুণ", "বাঁচাও", "ওরে বাবা"],
        "hi": ["कमाल", "बचाओ", "अविश्वसनीय"],
        "es": ["increíble", "no puede ser", "vamos"],
        "ar": ["مستحيل", "رائع", "ساعدني"],
    })

    def validate(self) -> None:
        if not isinstance(self.weights, dict) or set(self.weights) != set(FEATURES):
            raise ClipError(f"Ranking weights must contain exactly: {', '.join(FEATURES)}.")
        numbers = [*self.weights.values(), self.min_score, self.min_gap_seconds, self.max_iou]
        if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
               for value in numbers):
            raise ClipError("Ranking settings must be finite, nonnegative numbers.")
        if (not math.isfinite(sum(self.weights.values())) or sum(self.weights.values()) <= 0
                or self.min_score > 1 or self.max_iou >= 1):
            raise ClipError("Ranking needs a positive total weight, score within 0–1 and IoU within [0, 1).")
        if not isinstance(self.cues, dict):
            raise ClipError("Ranking cues must map language codes to lists of phrases.")
        for language, phrases in self.cues.items():
            if (not isinstance(language, str) or not 2 <= len(language) <= 3
                    or not language.isascii() or not language.islower() or not language.isalpha()
                    or not isinstance(phrases, list)
                    or any(not isinstance(phrase, str) or not tokens(phrase) for phrase in phrases)):
                raise ClipError("Cue languages need lowercase codes and nonempty phrase lists.")

    @classmethod
    def from_file(cls, path: Path | None) -> "RankingSettings":
        defaults = cls()
        if path is None:
            return defaults
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(raw, dict) or set(raw) - {"weights", "min_score", "min_gap_seconds", "max_iou", "cues"}:
                raise ClipError("Ranking configuration contains unknown fields or is not a JSON object.")
            weights = {**defaults.weights, **raw.get("weights", {})}
            cues = {**defaults.cues, **raw.get("cues", {})}
            config = cls(weights, raw.get("min_score", defaults.min_score),
                         raw.get("min_gap_seconds", defaults.min_gap_seconds),
                         raw.get("max_iou", defaults.max_iou), cues)
            config.validate()
            return config
        except (ValueError, TypeError, OSError, OverflowError) as exc:
            raise ClipError(f"Could not read ranking configuration. {exc}") from exc


def tokens(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    # Combining marks carry vowels in scripts such as Bengali and Hindi.
    words = "".join(character if unicodedata.category(character)[0] in "LNM" else " "
                    for character in normalized)
    return tuple(words.split())


def cue_matches(text: str, phrases: list[str]) -> list[str]:
    words = tokens(text)
    matches = []
    for phrase in phrases:
        cue = tokens(phrase)
        if cue and any(words[index:index + len(cue)] == cue
                       for index in range(len(words) - len(cue) + 1)):
            matches.append(phrase)
    return sorted(set(matches))


def interval_iou(first: Candidate, second: Candidate) -> float:
    intersection = max(0.0, min(first.end, second.end) - max(first.start, second.start))
    union = first.end - first.start + second.end - second.start - intersection
    return intersection / union if union > 0 else 0.0


def rank_candidates(activity: list[float], duration: float, clip_length: float = 30,
                    count: int = 3, *, segments: list[dict] | None = None,
                    language: str | None = None, config: RankingSettings | None = None) -> list[Candidate]:
    config = config or RankingSettings()
    config.validate()
    if not math.isfinite(duration) or duration <= 0:
        raise ClipError("Media duration must be finite and positive.")
    if not math.isfinite(clip_length) or not 15 <= clip_length <= 60 or not 1 <= count <= 10:
        raise ClipError("Choose 1–10 clips and a clip length between 15 and 60 seconds.")
    if any(not math.isfinite(level) or level < 0 for level in activity):
        raise ClipError("Audio activity must contain finite, nonnegative values.")
    if duration < 15:
        return []
    # Trim analysis padding and refuse transcript values outside the recording.
    activity = activity[:math.ceil(duration)]
    speech = []
    for segment in segments or []:
        try:
            start, end = float(segment["start"]), float(segment["end"])
            text = segment["text"]
            if not math.isfinite(start) or not math.isfinite(end) or not isinstance(text, str):
                raise ValueError("Invalid speech segment")
            start, end = max(0.0, start), min(duration, end)
            if start < end and text.strip():
                speech.append((start, end, cue_matches(text, config.cues.get(language, []))))
        except (KeyError, TypeError, ValueError) as exc:
            raise ClipError("Ranking received an invalid speech segment.") from exc
    maximum = max(activity, default=0.0)
    baseline = statistics.median(activity) if activity else 0.0
    average = sum(activity) / len(activity) if activity else 0.0
    events = set()
    if maximum >= 0.005 and maximum >= average * 1.25:
        events.update(min(duration, second + 0.5) for second, level in enumerate(activity)
                      if level >= max(0.005, average * 1.25))
    events.update((start + end) / 2 for start, end, matches in speech if matches)
    length = min(clip_length, duration)
    total_weight = sum(config.weights.values())
    ranked = []
    for event in sorted(events):
        start = max(0.0, min(event - length / 2, duration - length))
        end = start + length
        second = min(int(event), len(activity) - 1)
        level = activity[second] if second >= 0 else 0.0
        previous = activity[max(0, second - 1)] if second >= 0 else 0.0
        peak = max(0.0, level - baseline) / (maximum - baseline) if maximum > baseline else 0.0
        onset = max(0.0, level - previous) / maximum if maximum else 0.0
        intervals = sorted((max(start, left), min(end, right))
                           for left, right, _ in speech if left < end and right > start)
        covered, last_end = 0.0, start
        for left, right in intervals:
            covered += max(0.0, right - max(left, last_end))
            last_end = max(last_end, right)
        matches = sorted({phrase for left, right, phrases in speech
                          if left < end and right > start for phrase in phrases})
        features = {"audio_peak": peak, "audio_onset": onset,
                    "speech_activity": min(1.0, covered / length),
                    "transcript_cues": float(bool(matches))}
        contributions = {name: config.weights[name] * features[name] / total_weight for name in FEATURES}
        score = sum(contributions.values())
        if score < config.min_score or score <= 0:
            continue
        evidence = {
            **{name: round(value, 6) for name, value in features.items()},
            "audio_rms": round(level, 6), "normalized_peak": round(level / maximum, 6) if maximum else 0.0,
            "normalized_onset": round(onset, 6), "event_time": round(event, 3),
            "cue_matches": matches, "cue_language": language,
            "contributions": {name: round(value, 6) for name, value in contributions.items()},
            "score_kind": "heuristic",
        }
        ranked.append(Candidate(start, end, round(score, 6), evidence))
    # For long recordings (e.g. 10m+ or 2-3 hours) with multiple requested clips,
    # distribute candidates across temporal chunks so highlights span the full recording.
    chunk_count = min(count, int(duration // max(clip_length * 2, 60)))
    if chunk_count > 1 and duration >= 600:
        chunk_duration = duration / chunk_count
        chunk_candidates = []
        by_chunk = [[] for _ in range(chunk_count)]
        for candidate in sorted(ranked, key=lambda item: (-item.score, item.start)):
            idx = min(int(candidate.evidence["event_time"] // chunk_duration), chunk_count - 1)
            by_chunk[idx].append(candidate)

        # First pass: pick top candidate from each temporal chunk
        for chunk in by_chunk:
            for candidate in chunk:
                duplicate = any(
                    interval_iou(candidate, other) > config.max_iou
                    or max(0.0, candidate.start - other.end, other.start - candidate.end) < config.min_gap_seconds
                    for other in chunk_candidates
                )
                if not duplicate:
                    chunk_candidates.append(candidate)
                    break

        # Second pass: fill remaining slots with highest-scoring global candidates
        for candidate in sorted(ranked, key=lambda item: (-item.score, item.start, item.evidence["event_time"])):
            if len(chunk_candidates) >= count:
                break
            duplicate = any(
                interval_iou(candidate, other) > config.max_iou
                or max(0.0, candidate.start - other.end, other.start - candidate.end) < config.min_gap_seconds
                for other in chunk_candidates
            )
            if not duplicate:
                chunk_candidates.append(candidate)
        selected = chunk_candidates[:count]
    else:
        selected = []
        for candidate in sorted(ranked, key=lambda item: (-item.score, item.start, item.evidence["event_time"])):
            duplicate = any(
                interval_iou(candidate, other) > config.max_iou
                or max(0.0, candidate.start - other.end, other.start - candidate.end) < config.min_gap_seconds
                for other in selected
            )
            if not duplicate:
                selected.append(candidate)
            if len(selected) == count:
                break
    return selected
