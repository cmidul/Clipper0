"""Bounded, offline visual evidence for selected highlights, never semantic scoring."""
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import tempfile

from .engine import ClipError, Media, Settings, check_cancelled, run_tool
from .reframing import (CropKeyframe, FocusPoint, FramingPlan, FramingSettings, Region,
                        build_initial_plan, crop_for_focus, region_coverage)

ANALYSIS_VERSION = 1
SAMPLE_FPS = 3
MAX_WIDTH = 640


def scene_change(previous, current) -> float:
    import cv2
    import numpy as np
    histograms = []
    for image in (previous, current):
        hist = cv2.calcHist([image], [0], None, [32], [0, 256])
        histograms.append(cv2.normalize(hist, None))
    distance = cv2.compareHist(*histograms, cv2.HISTCMP_BHATTACHARYYA)
    difference = float(np.mean(cv2.absdiff(previous, current))) / 255
    return float(distance if difference > 0.12 else 0)


def motion_focus(previous, current, roi: Region | None = None):
    """Local activity after median camera-flow removal, supported by contrast.

    Motion is an activity cue only. Broad/global motion gets low confidence.
    """
    import cv2
    import numpy as np
    points = cv2.goodFeaturesToTrack(previous, maxCorners=100, qualityLevel=0.02, minDistance=8)
    if points is None or len(points) < 5:
        return None, 0.0, 0.0
    tracked, status, _ = cv2.calcOpticalFlowPyrLK(previous, current, points, None)
    if tracked is None or status is None:
        return None, 0.0, 0.0
    valid = status.reshape(-1).astype(bool)
    old, new = points.reshape(-1, 2)[valid], tracked.reshape(-1, 2)[valid]
    if len(new) < 5:
        return None, 0.0, 0.0
    residual = np.linalg.norm((new - old) - np.median(new - old, axis=0), axis=1)
    active = residual > max(1.0, float(np.percentile(residual, 65)))
    h, w = current.shape
    if roi is not None:
        active &= ((new[:, 0] >= roi.x * w) & (new[:, 0] <= (roi.x + roi.width) * w)
                   & (new[:, 1] >= roi.y * h) & (new[:, 1] <= (roi.y + roi.height) * h))
    if int(active.sum()) < 3:
        return None, 0.0, 0.0
    locations = new[active]
    center = np.median(locations, axis=0)
    spread = float(np.median(np.linalg.norm(locations - center, axis=1))) / max(w, h)
    # Contrast is a weak saliency proxy, not object recognition.
    contrast = float(current.std()) / 64
    confidence = min(0.62, max(0, (0.65 - spread) * min(1, contrast)))
    energy = min(1.0, float(np.median(residual[active])) / 15)
    return FocusPoint(float(np.clip(center[0] / w, 0, 1)), float(np.clip(center[1] / h, 0, 1))), confidence, energy


def smooth_track(samples: list[dict], width: int, height: int, intensity: float,
                 aspect_ratio: str = "9:16") -> tuple[CropKeyframe, ...]:
    """Bound pan speed with a dead zone, hold weak targets, reset at scene cuts."""
    output = []
    position = None
    previous_time, previous_scene, last_target_time = 0.0, -1, -10.0
    target = None
    for sample in samples:
        time, scene = sample["time"], sample["scene"]
        proposed = FocusPoint(sample["x"], sample["y"])
        if scene != previous_scene or position is None:
            position = proposed
            target = proposed
        elif sample["confidence"] >= 0.5 and (time - last_target_time >= 1 or
                math.hypot(proposed.x - target.x, proposed.y - target.y) < 0.15):
            target = proposed
            last_target_time = time
        if scene == previous_scene:
            dt = max(0, time - previous_time)
            dx, dy = target.x - position.x, target.y - position.y
            if math.hypot(dx, dy) > 0.015:
                alpha = 1 - math.exp(-dt * (0.6 + intensity * 2))
                distance = max(1e-9, math.hypot(dx, dy))
                movement = min(alpha, (0.035 + 0.12 * intensity) * dt / distance)
                position = FocusPoint(position.x + dx * movement, position.y + dy * movement)
        output.append(CropKeyframe(time, crop_for_focus(width, height, position, aspect_ratio=aspect_ratio),
                                   sample["confidence"], scene))
        previous_time, previous_scene = time, scene
    return tuple(output)


def _face_observation(gray, detector, previous_face):
    h, w = gray.shape
    faces = detector.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=6, minSize=(24, 24))
    if not len(faces):
        return None
    regions = [Region(float(x / w), float(y / h), float(fw / w), float(fh / h)) for x, y, fw, fh in faces]
    if previous_face is None:
        chosen = max(regions, key=lambda region: region.width * region.height)
    else:
        chosen = min(regions, key=lambda region: math.hypot(region.center.x - previous_face.center.x,
                                                            region.center.y - previous_face.center.y))
    return chosen, (0.88 if len(regions) == 1 else 0.55)


def analyze_frames(frames, settings: FramingSettings) -> dict:
    """Consume (clip-relative seconds, BGR frame) samples, retaining metadata only."""
    import cv2
    import numpy as np
    cv2.setNumThreads(1)
    detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if detector.empty():
        raise ClipError("The local face cascade is unavailable; use manual focus or Full gameplay.")
    previous = None
    previous_face = None
    samples, webcam_faces = [], []
    scene, count = 0, 0
    for time, image in frames:
        check_cancelled()
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        transition = previous is not None and scene_change(previous, gray) > 0.55
        if transition:
            scene += 1
            previous_face = None
        face = _face_observation(gray, detector, previous_face)
        point, confidence, energy = None, 0.0, 0.0
        kind, region = "none", None
        if face is not None:
            region, confidence = face
            point, kind, previous_face = region.center, "face", region
            # A face is only a webcam proposal when persistently small, stable
            # and near a corner; split selection additionally requires a border.
            if region.width * region.height < 0.06 and (point.x < 0.25 or point.x > 0.75):
                webcam_faces.append((region, gray.copy()))
        if previous is not None and not transition:
            motion, activity_confidence, energy = motion_focus(previous, gray, settings.focus_region)
            if point is None and motion is not None:
                point, confidence, kind = motion, activity_confidence, "activity"
        if point is None:
            point = FocusPoint(0.5, 0.5)
        sample = {"time": round(float(time), 4), "scene": scene, "x": point.x, "y": point.y,
                  "confidence": confidence, "kind": kind, "energy": energy,
                  "region": asdict(region) if region else None}
        # Keep at most ~one keyframe/second, plus scene changes. Detection still
        # samples at 3 FPS; metadata stays bounded for FFmpeg expressions.
        if not samples or transition or time - samples[-1]["time"] >= 0.99:
            samples.append(sample)
        previous = gray
        count += 1
    webcam, webcam_confidence = None, 0.0
    if count and len(webcam_faces) / count >= 0.8:
        centers = np.array([[region.center.x, region.center.y] for region, _ in webcam_faces])
        if float(centers.std(axis=0).max()) < 0.025:
            face = webcam_faces[-1][0]
            # Propose a padded rectangle; a strong rectangular boundary is
            # required before calling it an automatically usable webcam area.
            left, top = max(0, face.x - face.width * 0.6), max(0, face.y - face.height * 0.5)
            webcam = Region(left, top, min(1 - left, face.width * 2.2), min(1 - top, face.height * 2.5))
            gray = webcam_faces[-1][1]
            h, w = gray.shape
            x, y, rw, rh = int(left * w), int(top * h), int(webcam.width * w), int(webcam.height * h)
            edges = cv2.Canny(gray, 70, 150)[y:y+rh, x:x+rw]
            border = np.concatenate((edges[:2].ravel(), edges[-2:].ravel(), edges[:, :2].ravel(), edges[:, -2:].ravel()))
            webcam_confidence = 0.9 if len(border) and float((border > 0).mean()) > 0.3 else 0.45
    return {"version": ANALYSIS_VERSION, "samples": samples[:64], "sample_count": count,
            "scene_count": scene + 1 if count else 0,
            "webcam_region": asdict(webcam) if webcam else None, "webcam_confidence": webcam_confidence,
            "signals": ["scene histogram", "local residual optical flow", "contrast", "local Haar faces"],
            "warning": "Visual heuristics do not establish semantic importance."}


def analyze_candidate(media: Media, start: float, end: float, settings: Settings,
                      *, source_sha256: str | None = None) -> dict:
    from .speech import atomic_json, digest_file
    try:
        import cv2
    except ImportError as exc:
        raise ClipError("Visual dependencies are missing; install requirements-vision.txt or use Full gameplay.") from exc
    identity = {"version": ANALYSIS_VERSION, "sha256": source_sha256 or digest_file(media.path),
                "start": start, "end": end, "width": media.width, "height": media.height,
                "fps": SAMPLE_FPS, "max_width": MAX_WIDTH, "opencv": cv2.__version__}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    cache = settings.data_dir / "reframing" / f"{key}.json"
    if cache.is_file():
        try:
            payload = json.loads(cache.read_text(encoding="utf-8"))
            if payload["identity"] == identity and _valid_analysis(payload["analysis"], end - start):
                return {**payload["analysis"], "cache_hit": True, "cache_key": key}
        except (OSError, ValueError, KeyError, TypeError):
            pass
    with tempfile.TemporaryDirectory(prefix="vision-", dir=settings.data_dir) as temporary:
        decoded = Path(temporary) / "samples.mkv"
        run_tool([settings.ffmpeg, "-nostdin", "-v", "error", "-n", "-threads", str(settings.threads),
                  "-protocol_whitelist", "file,pipe", "-ss", f"{start:.6f}", "-i", str(media.path),
                  "-t", f"{end-start:.6f}", "-map", "0:V:0", "-an", "-sn", "-dn",
                  "-filter_threads", "1", "-vf", f"fps={SAMPLE_FPS},scale='min({MAX_WIDTH},iw)':-2",
                  "-c:v", "ffv1", "-threads", "1", str(decoded)])
        capture = cv2.VideoCapture(str(decoded))
        def frames():
            index = 0
            while index < math.ceil((end - start) * SAMPLE_FPS):
                check_cancelled()
                ok, frame = capture.read()
                if not ok:
                    break
                yield index / SAMPLE_FPS, frame
                index += 1
        try:
            # Analysis cache is independent of layout/ROI/intensity so revisions
            # can re-plan without decoding or rerunning the detectors.
            analysis = analyze_frames(frames(), FramingSettings())
        finally:
            capture.release()
    if not analysis["sample_count"]:
        raise ClipError("No visual samples could be decoded for this highlight.")
    atomic_json(cache, {"identity": identity, "analysis": analysis})
    return {**analysis, "cache_hit": False, "cache_key": key}


def _valid_analysis(analysis, duration):
    try:
        samples = analysis["samples"]
        if analysis["version"] != ANALYSIS_VERSION or not isinstance(samples, list) or not 1 <= len(samples) <= 64:
            return False
        previous = -1
        for sample in samples:
            if not previous < sample["time"] < duration:
                return False
            FocusPoint(sample["x"], sample["y"])
            if not 0 <= sample["confidence"] <= 1 or not 0 <= sample["energy"] <= 1:
                return False
            if not isinstance(sample["scene"], int) or sample["scene"] < 0:
                return False
            previous = sample["time"]
        return samples[0]["time"] == 0
    except (KeyError, TypeError, ValueError, ClipError):
        return False


def plan_from_analysis(media: Media, start: float, end: float, settings: FramingSettings,
                       analysis: dict, *, aspect_ratio="9:16") -> tuple[FramingPlan, FramingSettings]:
    """Conservative, explainable decisions; motion-only evidence never selects Auto crop."""
    if settings.focus_point is not None or settings.focus_region is not None or settings.webcam_region is not None or settings.mode == "full_gameplay":
        return build_initial_plan(media.width, media.height, start, end, settings, aspect_ratio=aspect_ratio), settings
    samples = analysis["samples"]
    if not _valid_analysis(analysis, end-start):
        raise ClipError("Cached visual evidence is invalid.")
    webcam = analysis.get("webcam_region")
    if (settings.mode in {"auto", "streamer_gameplay"}
            and webcam is not None and analysis.get("webcam_confidence", 0) >= 0.85):
        effective = replace(settings, webcam_region=Region(**webcam))
        return FramingPlan(media.width, media.height, start, end, settings.mode, "streamer_gameplay", 0.85), effective
    def preserve(reason):
        return FramingPlan(media.width, media.height, start, end, settings.mode, "full_gameplay", 0,
                           fallback_reason=reason), settings
    if settings.mode == "streamer_gameplay":
        return preserve("No confident webcam boundary found. Select its region manually or use Full gameplay.")
    if analysis.get("scene_count", 0) > 8:
        return preserve("Frequent scene changes make tracking unreliable; preserving all content.")
    reliable = [sample for sample in samples if sample["confidence"] >= (0.8 if settings.mode == "auto" else 0.5)]
    if len(reliable) < len(samples) * 0.75:
        return preserve("Target confidence or persistence is insufficient; preserving all content.")
    if settings.mode == "auto" and any(sample["kind"] != "face" for sample in reliable):
        return preserve("Activity alone does not establish an important subject; preserving all content.")
    frames = smooth_track(samples, media.width, media.height, settings.tracking_intensity, aspect_ratio)
    # Do not sacrifice the detected subject merely to keep a moving crop.
    for frame, sample in zip(frames, samples):
        if sample.get("region") and region_coverage(frame.crop, Region(**sample["region"]), media.width, media.height) < 0.98:
            return preserve("The detected subject would leave the smoothed crop; preserving all content.")
    confidence = sum(sample["confidence"] for sample in reliable) / len(reliable)
    emphasis = []
    if settings.emphasis_zoom and confidence >= 0.85:
        for sample in reliable:
            if sample["energy"] >= 0.6 and sample["time"] >= 1 and (not emphasis or sample["time"] - emphasis[-1] >= 8):
                emphasis.append(sample["time"])
                if len(emphasis) == 3:
                    break
    return FramingPlan(media.width, media.height, start, end, settings.mode, "smart_crop", confidence,
                       keyframes=frames, emphasis_times=tuple(emphasis)), settings
