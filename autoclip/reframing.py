"""Validated framing contracts and pure source-frame geometry.

Coordinates refer to the displayed, orientation-corrected source frame.
This module performs no decoding, detection, rendering, or network access.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
import math

from .engine import ASPECT_RATIOS, ClipError


PLAN_VERSION = 1
FRAMING_MODES = frozenset({"smart_crop", "streamer_gameplay", "full_gameplay", "auto"})
SUBTITLE_POSITIONS = frozenset({"auto", "top", "center", "bottom"})
SUPPORTED_ASPECT_RATIOS = frozenset(ASPECT_RATIOS)


def _number(value: object, name: str, minimum: float, maximum: float) -> None:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not minimum <= value <= maximum):
        raise ClipError(f"{name} must be a finite number between {minimum:g} and {maximum:g}.")


def _integer(value: object, name: str, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ClipError(f"{name} must be an integer of at least {minimum}.")


def _choice(value: object, choices: frozenset[str], name: str) -> None:
    if not isinstance(value, str) or value not in choices:
        raise ClipError(f"Unsupported {name}.")


@dataclass(frozen=True)
class FocusPoint:
    """Normalized source coordinates, including frame edges."""

    x: float
    y: float

    def __post_init__(self) -> None:
        _number(self.x, "Focus x", 0, 1)
        _number(self.y, "Focus y", 0, 1)


@dataclass(frozen=True)
class Region:
    """Normalized source rectangle with positive area wholly inside the frame."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        for name in ("x", "y", "width", "height"):
            _number(getattr(self, name), f"Region {name}", 0, 1)
        if self.width <= 0 or self.height <= 0:
            raise ClipError("Region width and height must be positive.")
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ClipError("Region must stay inside the source frame.")

    @property
    def center(self) -> FocusPoint:
        return FocusPoint(self.x + self.width / 2, self.y + self.height / 2)


@dataclass(frozen=True)
class FramingSettings:
    mode: str = "auto"
    focus_point: FocusPoint | None = None
    focus_region: Region | None = None
    webcam_region: Region | None = None
    tracking_intensity: float = 0.5
    subtitle_position: str = "auto"
    safe_margin_horizontal: float = 0.08
    safe_margin_top: float = 0.08
    safe_margin_bottom: float = 0.15
    background: str = "blur"
    emphasis_zoom: bool = False

    def __post_init__(self) -> None:
        _choice(self.mode, FRAMING_MODES, "framing mode")
        _choice(self.subtitle_position, SUBTITLE_POSITIONS, "subtitle position")
        _choice(self.background, frozenset({"blur", "pad"}), "background")
        _number(self.tracking_intensity, "Tracking intensity", 0, 1)
        for name in ("safe_margin_horizontal", "safe_margin_top", "safe_margin_bottom"):
            _number(getattr(self, name), name, 0, 0.4)
        if not isinstance(self.emphasis_zoom, bool):
            raise ClipError("Emphasis zoom must be a boolean.")
        if self.focus_point is not None and not isinstance(self.focus_point, FocusPoint):
            raise ClipError("Focus point must use validated source coordinates.")
        for name in ("focus_region", "webcam_region"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, Region):
                raise ClipError(f"{name} must use a validated source region.")
        if self.focus_point is not None and self.focus_region is not None:
            raise ClipError("Choose a focus point or focus region, not both.")

    @classmethod
    def from_dict(cls, payload: dict) -> FramingSettings:
        """Decode persisted JSON without accepting unknown fields or mutating it."""
        if not isinstance(payload, dict):
            raise ClipError("Framing settings must be a JSON object.")
        allowed = {field.name for field in fields(cls)}
        if any(not isinstance(key, str) or key not in allowed for key in payload):
            raise ClipError("Framing settings contain unsupported fields.")
        options = dict(payload)
        for name, record in (("focus_point", FocusPoint), ("focus_region", Region), ("webcam_region", Region)):
            value = options.get(name)
            if value is None:
                continue
            if not isinstance(value, dict):
                raise ClipError(f"{name} must be a JSON object with source coordinates.")
            expected = {field.name for field in fields(record)}
            if set(value) != expected:
                raise ClipError(f"{name} must contain exactly its required coordinate fields.")
            try:
                options[name] = record(**value)
            except TypeError:
                raise ClipError(f"{name} contains invalid coordinate fields.") from None
        try:
            return cls(**options)
        except TypeError:
            raise ClipError("Framing settings contain invalid fields.") from None


@dataclass(frozen=True)
class CropRect:
    """Even pixel geometry suitable for chroma-subsampled FFmpeg crops."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        for name in ("x", "y", "width", "height"):
            value = getattr(self, name)
            _integer(value, f"Crop {name}", 2 if name in {"width", "height"} else 0)
            if value % 2:
                raise ClipError("Crop coordinates and dimensions must be even pixels.")


def _source_dimensions(width: int, height: int) -> None:
    _integer(width, "Source width", 2)
    _integer(height, "Source height", 2)


def crop_for_focus(source_width: int, source_height: int,
                   focus: FocusPoint | None = None, *, aspect_ratio: str = "9:16") -> CropRect:
    """Largest exact-ratio even crop, centered on focus and clamped to source.

    An even multiple of the ratio's integer components avoids chroma rounding
    changing the intended aspect ratio. Very small inputs may not fit a crop.
    """
    _source_dimensions(source_width, source_height)
    _choice(aspect_ratio, SUPPORTED_ASPECT_RATIOS, "aspect ratio")
    focus = FocusPoint(0.5, 0.5) if focus is None else focus
    if not isinstance(focus, FocusPoint):
        raise ClipError("Focus must be a validated focus point.")
    ratio_width, ratio_height = ASPECT_RATIOS[aspect_ratio]
    units = min(source_width // (2 * ratio_width), source_height // (2 * ratio_height))
    if units < 1:
        raise ClipError("Source frame is too small for an exact-ratio even crop.")
    width, height = 2 * ratio_width * units, 2 * ratio_height * units
    max_x, max_y = (source_width - width) // 2 * 2, (source_height - height) // 2 * 2
    x = round((focus.x * source_width - width / 2) / 2) * 2
    y = round((focus.y * source_height - height / 2) / 2) * 2
    return CropRect(max(0, min(max_x, x)), max(0, min(max_y, y)), width, height)


def region_coverage(crop: CropRect, region: Region,
                    source_width: int, source_height: int) -> float:
    """Fraction of a specified region visible in a crop; not semantic importance."""
    _source_dimensions(source_width, source_height)
    if not isinstance(crop, CropRect) or not isinstance(region, Region):
        raise ClipError("Coverage requires a validated crop and region.")
    if crop.x + crop.width > source_width or crop.y + crop.height > source_height:
        raise ClipError("Crop must stay inside the source frame.")
    left, top = region.x * source_width, region.y * source_height
    width, height = region.width * source_width, region.height * source_height
    intersection_width = max(0.0, min(crop.x + crop.width, left + width) - max(crop.x, left))
    intersection_height = max(0.0, min(crop.y + crop.height, top + height) - max(crop.y, top))
    return min(1.0, max(0.0, intersection_width * intersection_height / (width * height)))


@dataclass(frozen=True)
class CropKeyframe:
    """Clip-relative time; scene identity permits a discontinuity at a cut."""

    time: float
    crop: CropRect
    confidence: float
    scene_id: int = 0

    def __post_init__(self) -> None:
        _number(self.time, "Keyframe time", 0, 60)
        _number(self.confidence, "Keyframe confidence", 0, 1)
        _integer(self.scene_id, "Scene identifier", 0)
        if not isinstance(self.crop, CropRect):
            raise ClipError("Keyframe crop must be validated pixel geometry.")


@dataclass(frozen=True)
class FramingPlan:
    source_width: int
    source_height: int
    start: float
    end: float
    requested_mode: str
    selected_mode: str
    confidence: float
    keyframes: tuple[CropKeyframe, ...] = ()
    fallback_reason: str | None = None
    version: int = PLAN_VERSION
    emphasis_times: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        _source_dimensions(self.source_width, self.source_height)
        _number(self.start, "Interval start", 0, float("1e12"))
        _number(self.end, "Interval end", 0, float("1e12"))
        if not 15 <= self.end - self.start <= 60:
            raise ClipError("Framing intervals must span 15–60 seconds.")
        _choice(self.requested_mode, FRAMING_MODES, "requested framing mode")
        _choice(self.selected_mode, FRAMING_MODES - {"auto"}, "selected framing mode")
        _number(self.confidence, "Plan confidence", 0, 1)
        _integer(self.version, "Plan version", 1)
        if self.version != PLAN_VERSION:
            raise ClipError("Unsupported framing plan version.")
        if self.fallback_reason is not None and (
                not isinstance(self.fallback_reason, str) or not self.fallback_reason.strip()
                or len(self.fallback_reason) > 500):
            raise ClipError("Fallback reason must be nonempty text of at most 500 characters.")
        if not isinstance(self.keyframes, tuple):
            raise ClipError("Plan keyframes must be an immutable tuple.")
        if len(self.keyframes) > 64:
            raise ClipError("Framing plans are limited to 64 keyframes per highlight.")
        if not isinstance(self.emphasis_times, tuple) or len(self.emphasis_times) > 3:
            raise ClipError("Emphasis events must be an immutable tuple of at most three times.")
        previous_emphasis = -10.0
        for time in self.emphasis_times:
            _number(time, "Emphasis time", 0, self.end - self.start)
            if time - previous_emphasis < 8:
                raise ClipError("Emphasis events must be at least eight seconds apart.")
            previous_emphasis = time
        previous_time, previous_scene = -1.0, -1
        previous_size = None
        for frame in self.keyframes:
            if not isinstance(frame, CropKeyframe):
                raise ClipError("Plan keyframes must be validated records.")
            if not previous_time < frame.time <= self.end - self.start:
                raise ClipError("Keyframes must be strictly ordered inside the clip interval.")
            if frame.scene_id < previous_scene:
                raise ClipError("Scene identifiers must not move backwards.")
            crop = frame.crop
            if crop.x + crop.width > self.source_width or crop.y + crop.height > self.source_height:
                raise ClipError("Keyframe crop must stay inside the source frame.")
            size = (crop.width, crop.height)
            if previous_size is not None and size != previous_size:
                raise ClipError("Initial framing plans require a fixed crop size.")
            previous_time, previous_scene, previous_size = frame.time, frame.scene_id, size
        if self.selected_mode == "smart_crop" and (
                not self.keyframes or self.keyframes[0].time != 0):
            raise ClipError("Smart crop plans must begin with a keyframe at clip time zero.")


def build_initial_plan(source_width: int, source_height: int, start: float, end: float,
                       settings: FramingSettings, *, aspect_ratio: str = "9:16") -> FramingPlan:
    """Resolve explicit manual settings, preserving content without visual evidence.

    This is not automatic detection. Confidence 1 denotes an explicit manual
    selection, not measured subject recognition or a guarantee of good framing.
    A focus point specifies a center only; a region additionally permits checking
    retention. At least 98% of a requested focus region must fit in the crop.
    """
    if not isinstance(settings, FramingSettings):
        raise ClipError("Planning requires validated framing settings.")
    _choice(aspect_ratio, SUPPORTED_ASPECT_RATIOS, "aspect ratio")

    def result(mode: str, confidence: float, *, frames: tuple[CropKeyframe, ...] = (),
               reason: str | None = None) -> FramingPlan:
        return FramingPlan(source_width, source_height, start, end, settings.mode,
                           mode, confidence, keyframes=frames, fallback_reason=reason)

    # Validate the interval and source before any coordinate arithmetic, even
    # when the eventual path will choose another layout.
    preserving = result("full_gameplay", 0)
    if settings.mode == "full_gameplay":
        return preserving
    if settings.mode == "streamer_gameplay":
        if settings.webcam_region is None:
            return result("full_gameplay", 0, reason="No webcam region was supplied; preserving the full frame.")
        return result("streamer_gameplay", 1)
    if settings.mode == "auto" and settings.webcam_region is not None:
        return result("streamer_gameplay", 1)

    focus = settings.focus_point
    if settings.focus_region is not None:
        focus = settings.focus_region.center
    if focus is None:
        return result("full_gameplay", 0, reason=(
            "Automatic visual analysis is not implemented yet and no manual focus was supplied; "
            "preserving the full frame."
        ))
    try:
        crop = crop_for_focus(source_width, source_height, focus, aspect_ratio=aspect_ratio)
    except ClipError:
        # Source/ratio/selection were already validated. Tiny frames cannot
        # support exact-ratio even crops, but may still be fitted safely.
        return result("full_gameplay", 0, reason="Source is too small for the requested crop; preserving the full frame.")
    if settings.focus_region is not None:
        coverage = region_coverage(crop, settings.focus_region, source_width, source_height)
        if coverage < 0.98:
            return result("full_gameplay", 0, reason=(
                "The requested focus region cannot fit safely in one crop; preserving the full frame."
            ))
    return result("smart_crop", 1, frames=(CropKeyframe(0, crop, 1),))
