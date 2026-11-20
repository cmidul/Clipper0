"""Visual heuristics, conservative decisions, smooth plans and real cache reuse."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from autoclip.engine import Media, Settings
from autoclip.reframing import CropKeyframe, FocusPoint, FramingPlan, FramingSettings, Region
from autoclip.vision import ANALYSIS_VERSION, analyze_candidate, analyze_frames, plan_from_analysis, scene_change, smooth_track


def evidence(kind="face", confidence=0.88):
    return {"version": ANALYSIS_VERSION, "scene_count": 1, "sample_count": 45, "webcam_confidence": 0,
            "samples": [{"time": float(t), "scene": 0, "x": 0.45 + t * 0.002, "y": 0.5,
                         "kind": kind, "confidence": confidence, "energy": 0.8,
                         "region": {"x": 0.42 + t*0.002, "y": 0.4, "width": 0.06, "height": 0.1}}
                        for t in range(15)]}


class VisualDecisionTests(unittest.TestCase):
    media = Media(Path("not read.mp4"), 30, 1920, 1080, "h264", False, 1)

    def test_scene_change_detects_cut_but_not_identical_frames(self):
        black, white = np.zeros((90, 160), np.uint8), np.full((90, 160), 255, np.uint8)
        self.assertEqual(scene_change(black, black), 0)
        self.assertGreater(scene_change(black, white), 0.55)

    def test_motion_alone_cannot_select_auto_crop(self):
        plan, _ = plan_from_analysis(self.media, 0, 15, FramingSettings(), evidence("activity", 0.62))
        self.assertEqual(plan.selected_mode, "full_gameplay")
        self.assertIsNotNone(plan.fallback_reason)

    def test_persistent_face_selects_crop_but_low_confidence_preserves(self):
        plan, _ = plan_from_analysis(self.media, 0, 15, FramingSettings(), evidence())
        self.assertEqual(plan.selected_mode, "focus_crop")
        self.assertEqual(len(plan.keyframes), 15)
        weak, _ = plan_from_analysis(self.media, 0, 15, FramingSettings(), evidence(confidence=0.3))
        self.assertEqual(weak.selected_mode, "full_gameplay")

    def test_frequent_cuts_and_large_subject_preserve_content(self):
        data = evidence()
        data["scene_count"] = 10
        plan, _ = plan_from_analysis(self.media, 0, 15, FramingSettings(), data)
        self.assertEqual(plan.selected_mode, "full_gameplay")
        data = evidence()
        for sample in data["samples"]:
            sample["region"] = {"x": 0, "y": 0, "width": 1, "height": 1}
        plan, _ = plan_from_analysis(self.media, 0, 15, FramingSettings(), data)
        self.assertEqual(plan.selected_mode, "full_gameplay")

    def test_webcam_requires_confident_boundary_and_manual_override_wins(self):
        data = evidence()
        data.update(webcam_region={"x": 0, "y": 0, "width": 0.2, "height": 0.2}, webcam_confidence=0.9)
        plan, effective = plan_from_analysis(self.media, 0, 15, FramingSettings(mode="streamer_gameplay"), data)
        self.assertEqual(plan.selected_mode, "streamer_gameplay")
        self.assertIsNotNone(effective.webcam_region)
        manual = FramingSettings(mode="smart_crop", focus_point=FocusPoint(1, 0.5))
        plan, _ = plan_from_analysis(self.media, 0, 15, manual, data)
        self.assertEqual(plan.selected_mode, "smart_crop")
        self.assertEqual(len(plan.keyframes), 1)
        self.assertEqual(plan.keyframes[0].crop.x + plan.keyframes[0].crop.width, 1920)

    def test_persistent_central_activity_uses_wider_crop_and_static_toggle(self):
        data = evidence("central_activity", 0.61)
        plan, _ = plan_from_analysis(self.media, 0, 15, FramingSettings(smooth_tracking=False), data)
        self.assertEqual(plan.selected_mode, "hybrid_focus")
        self.assertEqual(len(plan.keyframes), 1)
        weak, _ = plan_from_analysis(self.media, 0, 15, FramingSettings(mode="hybrid_focus"), evidence(confidence=0.3))
        self.assertEqual(weak.selected_mode, "hybrid_focus")
        self.assertEqual(len(weak.keyframes), 1)
        self.assertEqual(weak.confidence, 0)

    def test_roi_excludes_outside_targets_and_lock_bypasses_analysis(self):
        roi = Region(0.65, 0.4, 0.10, 0.15)
        framing = FramingSettings(mode="hybrid_focus", focus_region=roi, lock_position=True)
        locked, _ = plan_from_analysis(self.media, 0, 15, framing, {})
        self.assertEqual(len(locked.keyframes), 1)
        limited, _ = plan_from_analysis(self.media, 0, 15, replace(framing, lock_position=False), evidence())
        self.assertEqual(locked.keyframes, limited.keyframes)

    def test_smoothing_limits_pan_and_resets_at_scene_cut(self):
        data = evidence()["samples"]
        for index, sample in enumerate(data):
            sample["x"] = 0.15 if index % 2 == 0 else 0.85
        frames = smooth_track(data, 1920, 1080, 0.5)
        for left, right in zip(frames, frames[1:]):
            self.assertLessEqual(abs(right.crop.x-left.crop.x), 1920*0.095+2)
        data[5].update(scene=1, x=0.85)
        for sample in data[6:]:
            sample["scene"] = 1
        cut = smooth_track(data, 1920, 1080, 0.5)
        self.assertEqual(cut[5].scene_id, 1)
        self.assertGreater(cut[5].crop.x, cut[4].crop.x + 400)

    def test_emphasis_is_opt_in_confident_and_spaced(self):
        plain, _ = plan_from_analysis(self.media, 0, 15, FramingSettings(), evidence())
        self.assertEqual(plain.emphasis_times, ())
        zoom, _ = plan_from_analysis(self.media, 0, 15, FramingSettings(emphasis_zoom=True), evidence())
        self.assertTrue(zoom.emphasis_times)
        self.assertTrue(all(b-a >= 8 for a,b in zip(zoom.emphasis_times, zoom.emphasis_times[1:])))

    def test_uniform_frames_have_no_confident_target(self):
        frames = [(i/3, np.zeros((90, 160, 3), np.uint8)) for i in range(9)]
        data = analyze_frames(frames, FramingSettings())
        self.assertEqual(data["sample_count"], 9)
        self.assertTrue(all(sample["confidence"] == 0 for sample in data["samples"]))

    def test_real_selected_interval_analysis_cache_and_corruption_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mp4"
            result = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i",
                "color=c=gray:s=320x180:r=10:d=15", "-c:v", "libx264", "-threads", "1", str(source)],
                capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            media = replace(self.media, path=source, width=320, height=180, duration=15)
            first = analyze_candidate(media, 0, 15, Settings(root), source_sha256="a"*64)
            self.assertFalse(first["cache_hit"])
            self.assertEqual(first["sample_count"], 45)
            with patch("autoclip.vision.run_tool", side_effect=AssertionError("unexpected decode")):
                second = analyze_candidate(media, 0, 15, Settings(root), source_sha256="a"*64)
            self.assertTrue(second["cache_hit"])
            cache = next((root / "reframing").glob("*.json"))
            cache.write_text("broken", encoding="utf-8")
            recovered = analyze_candidate(media, 0, 15, Settings(root), source_sha256="a"*64)
            self.assertFalse(recovered["cache_hit"])
