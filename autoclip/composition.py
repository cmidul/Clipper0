"""Pure, validated FFmpeg composition graphs; no subprocess execution.

The caller maps ``[framed]`` as video and preserves the existing audio mapping.
Input dimensions must describe the orientation-corrected square-pixel frame.
No timing filters are inserted, so composition does not retime either stream.
"""

from dataclasses import dataclass
import math

from .engine import ASPECT_RATIOS, ClipError, output_dimensions
from .reframing import CropRect, FramingPlan, FramingSettings, Region


@dataclass(frozen=True)
class Composition:
    filtergraph: str
    width: int
    height: int
    output_label: str = "[framed]"


def _scale_down(width: int, height: int) -> str:
    return (f"scale=w='min(iw,{width})':h='min(ih,{height})':"
            "force_original_aspect_ratio=decrease:force_divisible_by=2:reset_sar=1")


def _fit(width: int, height: int) -> str:
    return (f"{_scale_down(width, height)},"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1")


def _fill(width: int, height: int) -> str:
    return (f"scale={width}:{height}:force_original_aspect_ratio=increase:"
            "force_divisible_by=2:reset_sar=1,"
            f"crop={width}:{height},setsar=1")


def _crop_filter(crop: CropRect) -> str:
    return f"crop={crop.width}:{crop.height}:{crop.x}:{crop.y}"


def split_panel_heights(height: int) -> tuple[int, int]:
    top = round(height * 0.30 / 2) * 2
    return top, height - top


def position_expression(plan: FramingPlan, axis: str) -> str:
    """Cosine ease between validated samples; hard reset only at scene cuts."""
    if axis not in {"x", "y"} or not plan.keyframes:
        raise ClipError("A crop position expression requires an axis and keyframes.")
    expression = str(getattr(plan.keyframes[0].crop, axis))
    for previous, current in zip(plan.keyframes, plan.keyframes[1:]):
        delta = getattr(current.crop, axis) - getattr(previous.crop, axis)
        if not delta:
            continue
        if current.scene_id != previous.scene_id:
            factor = f"gte(t,{current.time:.4f})"
        else:
            factor = (f"(0.5-0.5*cos(PI*clip((t-{previous.time:.4f})/"
                      f"{current.time-previous.time:.4f},0,1)))")
        expression += f"+({delta})*{factor}"
    return f"2*floor(({expression})/2)"


def _region_pixels(region: Region, width: int, height: int) -> CropRect:
    """Expand to even pixel boundaries where possible, clipped to source."""
    left = math.floor(region.x * width / 2) * 2
    top = math.floor(region.y * height / 2) * 2
    right = min(width // 2 * 2, math.ceil((region.x + region.width) * width / 2) * 2)
    bottom = min(height // 2 * 2, math.ceil((region.y + region.height) * height / 2) * 2)
    if right - left < 2 or bottom - top < 2:
        raise ClipError("Webcam region is too small to render at source resolution.")
    return CropRect(left, top, right - left, bottom - top)


def build_filtergraph(plan: FramingPlan, settings: FramingSettings, *,
                      resolution: int = 720, aspect_ratio: str = "9:16") -> Composition:
    """Build a labeled graph for a resolved layout before captions are applied."""
    if not isinstance(plan, FramingPlan) or not isinstance(settings, FramingSettings):
        raise ClipError("Composition requires a validated framing plan and settings.")
    if settings.mode != plan.requested_mode:
        raise ClipError("Framing settings do not match the plan's requested mode.")
    width, height = output_dimensions(resolution, aspect_ratio)
    mode = plan.selected_mode
    if mode == "full_gameplay":
        if plan.keyframes:
            raise ClipError("Full-gameplay composition must not contain crop keyframes.")
        if settings.background == "pad":
            graph = f"[0:V:0]{_fit(width, height)},format=yuv420p[framed]"
        else:
            # Blur at reduced resolution to limit CPU cost; only the background
            # is cropped. The foreground retains the complete original frame.
            small_width, small_height = width // 4 // 2 * 2, height // 4 // 2 * 2
            graph = (
                "[0:V:0]split=2[bgsrc][fgsrc];"
                f"[bgsrc]{_fill(small_width, small_height)},boxblur=8:2,"
                f"scale={width}:{height},setsar=1[bg];"
                f"[fgsrc]{_scale_down(width, height)},setsar=1[fg];"
                "[bg][fg]overlay=x=(W-w)/2:y=(H-h)/2:shortest=1,"
                "format=yuv420p,setsar=1[framed]"
            )
    elif mode == "streamer_gameplay":
        if settings.webcam_region is None:
            raise ClipError("Select a webcam region before rendering split screen.")
        if plan.keyframes:
            raise ClipError("Initial split-screen composition does not support tracking keyframes.")
        webcam = _region_pixels(settings.webcam_region, plan.source_width, plan.source_height)
        top_height, bottom_height = split_panel_heights(height)
        graph = (
            "[0:V:0]split=2[camsrc][gamesrc];"
            f"[camsrc]{_crop_filter(webcam)},{_fit(width, top_height)}[cam];"
            f"[gamesrc]{_fit(width, bottom_height)}[game];"
            "[cam][game]vstack=inputs=2:shortest=1,format=yuv420p,setsar=1[framed]"
        )
    elif mode == "smart_crop":
        crop = plan.keyframes[0].crop
        ratio_width, ratio_height = ASPECT_RATIOS[aspect_ratio]
        if crop.width * ratio_height != crop.height * ratio_width:
            raise ClipError("Planned crop aspect ratio must match the output aspect ratio.")
        graph = (f"[0:V:0]crop={crop.width}:{crop.height}:"
                 f"x='{position_expression(plan, 'x')}':y='{position_expression(plan, 'y')}',"
                 f"{_fit(width, height)},format=yuv420p[framed]")
    else:
        raise ClipError("The framing plan has no supported resolved layout.")
    if settings.emphasis_zoom and mode == "smart_crop" and plan.confidence >= 0.85 and plan.emphasis_times:
        # A <=3% smooth, two-second pulse, no frame duplication or retiming.
        pulses = "+".join(f"if(between(t,{time-1:.4f},{time+1:.4f}),"
                          f"(1+cos(PI*(t-{time:.4f})))/2,0)" for time in plan.emphasis_times)
        graph = graph.removesuffix("[framed]") + (
            f"[composed];[composed]scale=w='ceil({width}*(1+0.03*({pulses}))/2)*2':"
            f"h='ceil({height}*(1+0.03*({pulses}))/2)*2':eval=frame,"
            f"crop={width}:{height},setsar=1[framed]"
        )
    return Composition(graph, width, height)
