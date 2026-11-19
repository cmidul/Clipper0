"""Pure framing geometry and contract checks; no media or models required."""

import math
import copy
from dataclasses import asdict
import json
import unittest

from autoclip.engine import ClipError
from autoclip.reframing import (
    CropKeyframe, CropRect, FocusPoint, FramingPlan, FramingSettings, Region,
    build_initial_plan, crop_for_focus, region_coverage,
)


class FramingGeometryTests(unittest.TestCase):
    def test_crop_preserves_ratio_bounds_and_even_pixels(self):
        ratios = (("9:16", 9, 16), ("16:9", 16, 9), ("1:1", 1, 1), ("4:5", 4, 5))
        for width, height in ((1920, 1080), (1080, 1920), (1919, 1079), (640, 640)):
            for ratio, numerator, denominator in ratios:
                for x in (0, 0.25, 0.5, 0.75, 1):
                    for y in (0, 0.5, 1):
                        with self.subTest(source=(width, height), ratio=ratio, focus=(x, y)):
                            crop = crop_for_focus(width, height, FocusPoint(x, y), aspect_ratio=ratio)
                            self.assertEqual(crop.width * denominator, crop.height * numerator)
                            self.assertGreater(crop.width, 0)
                            self.assertGreater(crop.height, 0)
                            self.assertGreaterEqual(crop.x, 0)
                            self.assertGreaterEqual(crop.y, 0)
                            self.assertLessEqual(crop.x + crop.width, width)
                            self.assertLessEqual(crop.y + crop.height, height)
                            self.assertTrue(all(value % 2 == 0 for value in (
                                crop.x, crop.y, crop.width, crop.height)))

    def test_focus_moves_crop_and_clamps_at_edges(self):
        left = crop_for_focus(1920, 1080, FocusPoint(0, 0.5))
        center = crop_for_focus(1920, 1080)
        right = crop_for_focus(1920, 1080, FocusPoint(1, 0.5))
        self.assertEqual(left.x, 0)
        self.assertLess(left.x, center.x)
        self.assertLess(center.x, right.x)
        self.assertEqual(right.x + right.width, 1920)
        self.assertEqual((left.width, left.height), (right.width, right.height))

    def test_invalid_source_or_ratio_fails(self):
        for width, height in ((0, 1080), (1920, -1), (True, 1080), (1920.0, 1080), (16, 16)):
            with self.subTest(source=(width, height)), self.assertRaises(ClipError):
                crop_for_focus(width, height)
        with self.assertRaises(ClipError):
            crop_for_focus(1920, 1080, aspect_ratio="5:4")
        with self.assertRaises(ClipError):
            crop_for_focus(1920, 1080, focus={"x": 0.5, "y": 0.5})

    def test_coverage_measures_actual_region_intersection(self):
        crop = CropRect(0, 0, 100, 100)
        self.assertEqual(region_coverage(crop, Region(0, 0, 0.5, 1), 200, 100), 1)
        self.assertEqual(region_coverage(crop, Region(0.5, 0, 0.5, 1), 200, 100), 0)
        self.assertAlmostEqual(region_coverage(crop, Region(0.25, 0, 0.5, 1), 200, 100), 0.5)
        with self.assertRaises(ClipError):
            region_coverage(CropRect(150, 0, 100, 100), Region(0, 0, 1, 1), 200, 100)


class FramingContractTests(unittest.TestCase):
    def test_focus_rejects_nonfinite_out_of_bounds_and_boolean_values(self):
        for value in (-0.01, 1.01, math.nan, math.inf, -math.inf, True, "0.5", None):
            for coordinates in ((value, 0.5), (0.5, value)):
                with self.subTest(coordinates=coordinates), self.assertRaises(ClipError):
                    FocusPoint(*coordinates)
        self.assertEqual(FocusPoint(0, 1).y, 1)

    def test_regions_require_positive_contained_area(self):
        for values in ((0, 0, 0, 1), (0, 0, 1, 0), (0.8, 0, 0.3, 1),
                       (0, 0.8, 1, 0.3), (-0.1, 0, 0.5, 0.5), (0, 0, math.nan, 1)):
            with self.subTest(values=values), self.assertRaises(ClipError):
                Region(*values)
        self.assertEqual(Region(0.2, 0.1, 0.4, 0.6).center, FocusPoint(0.4, 0.4))

    def test_settings_validate_overrides_and_controls(self):
        for mode in ("smart_crop", "streamer_gameplay", "full_gameplay", "auto"):
            self.assertEqual(FramingSettings(mode=mode).mode, mode)
        for options in (
            {"mode": "unknown"}, {"tracking_intensity": -0.1}, {"tracking_intensity": math.nan},
            {"tracking_intensity": True}, {"subtitle_position": "left"}, {"background": "remote"},
            {"safe_margin_bottom": 0.5}, {"safe_margin_top": -0.01}, {"emphasis_zoom": 1},
            {"focus_point": [0.5, 0.5]}, {"webcam_region": {"x": 0}},
            {"focus_point": FocusPoint(0.5, 0.5), "focus_region": Region(0, 0, 1, 1)},
        ):
            with self.subTest(options=options), self.assertRaises(ClipError):
                FramingSettings(**options)
        self.assertFalse(FramingSettings().emphasis_zoom)

    def test_crop_pixel_contract(self):
        for values in ((-2, 0, 100, 100), (1, 0, 100, 100), (0, 0, 0, 100),
                       (0, 0, 99, 100), (0, 0, 100.0, 100), (False, 0, 100, 100)):
            with self.subTest(values=values), self.assertRaises(ClipError):
                CropRect(*values)

    def plan(self, **overrides):
        options = dict(source_width=1920, source_height=1080, start=10, end=40,
                       requested_mode="auto", selected_mode="smart_crop", confidence=0.8,
                       keyframes=(CropKeyframe(0, CropRect(0, 0, 594, 1056), 0.8),))
        options.update(overrides)
        return FramingPlan(**options)

    def test_plan_accepts_ordered_scene_change_and_preserving_fallback(self):
        plan = self.plan(keyframes=(
            CropKeyframe(0, CropRect(0, 0, 594, 1056), 0.8),
            CropKeyframe(10, CropRect(400, 0, 594, 1056), 0.9, scene_id=1),
            CropKeyframe(30, CropRect(600, 0, 594, 1056), 0.9, scene_id=1),
        ))
        self.assertEqual(plan.keyframes[-1].time, 30)
        fallback = self.plan(selected_mode="full_gameplay", keyframes=(), confidence=0.1,
                             fallback_reason="Competing regions cannot fit in one crop.")
        self.assertEqual(fallback.selected_mode, "full_gameplay")

    def test_plan_rejects_invalid_intervals_modes_and_metadata(self):
        for options in ({"end": 24}, {"end": 71}, {"start": math.nan}, {"version": 2},
                        {"version": True}, {"confidence": 1.1}, {"selected_mode": "auto"},
                        {"requested_mode": "unknown"}, {"fallback_reason": " "},
                        {"fallback_reason": "x" * 501}, {"keyframes": []}):
            with self.subTest(options=options), self.assertRaises(ClipError):
                self.plan(**options)

    def test_plan_rejects_invalid_keyframe_sequences(self):
        crop = CropRect(0, 0, 594, 1056)
        sequences = (
            (), (CropKeyframe(1, crop, 0.5),),
            (CropKeyframe(0, crop, 0.5), CropKeyframe(0, crop, 0.5)),
            (CropKeyframe(0, crop, 0.5), CropKeyframe(31, crop, 0.5)),
            (CropKeyframe(0, crop, 0.5, 1), CropKeyframe(1, crop, 0.5, 0)),
            (CropKeyframe(0, CropRect(1500, 0, 594, 1056), 0.5),),
            (CropKeyframe(0, crop, 0.5), CropKeyframe(1, CropRect(0, 0, 576, 1024), 0.5)),
        )
        for sequence in sequences:
            with self.subTest(sequence=sequence), self.assertRaises(ClipError):
                self.plan(keyframes=sequence)

    def test_keyframe_rejects_invalid_time_confidence_and_scene(self):
        crop = CropRect(0, 0, 594, 1056)
        for options in ({"time": -1}, {"time": 61}, {"confidence": math.inf},
                        {"scene_id": -1}, {"scene_id": True}, {"crop": None}):
            values = dict(time=0, crop=crop, confidence=0.5)
            values.update(options)
            with self.subTest(options=options), self.assertRaises(ClipError):
                CropKeyframe(**values)


class FramingSerializationTests(unittest.TestCase):
    def test_empty_object_uses_validated_defaults(self):
        self.assertEqual(FramingSettings.from_dict({}), FramingSettings())

    def test_json_round_trip_preserves_nested_records(self):
        for settings in (
            FramingSettings(mode="smart_crop", focus_point=FocusPoint(0.2, 0.7), tracking_intensity=0),
            FramingSettings(mode="auto", focus_region=Region(0.1, 0.2, 0.3, 0.4)),
            FramingSettings(mode="streamer_gameplay", webcam_region=Region(0, 0, 0.2, 0.2),
                            background="pad", subtitle_position="top", safe_margin_bottom=0.2),
        ):
            with self.subTest(settings=settings):
                restored = FramingSettings.from_dict(json.loads(json.dumps(asdict(settings))))
                self.assertEqual(restored, settings)

    def test_unknown_missing_and_malformed_structures_are_rejected(self):
        for payload in (
            None, [], "auto", 1, {"unexpected": True}, {1: "auto"},
            {"focus_point": [0.5, 0.5]}, {"focus_point": {"x": 0.5}},
            {"focus_point": {"x": 0.5, "y": 0.5, "z": 0}},
            {"focus_region": {"x": 0, "y": 0, "width": 0.2}},
            {"webcam_region": "0,0,0.2,0.2"},
        ):
            with self.subTest(payload=payload), self.assertRaises(ClipError):
                FramingSettings.from_dict(payload)

    def test_nested_values_and_control_values_are_validated(self):
        for payload in (
            {"focus_point": {"x": math.nan, "y": 0.5}},
            {"focus_point": {"x": "0.5", "y": 0.5}},
            {"webcam_region": {"x": 0.9, "y": 0, "width": 0.2, "height": 0.2}},
            {"tracking_intensity": True}, {"emphasis_zoom": "false"}, {"mode": "remote"},
            {"focus_point": {"x": 0.5, "y": 0.5},
             "focus_region": {"x": 0, "y": 0, "width": 1, "height": 1}},
        ):
            with self.subTest(payload=payload), self.assertRaises(ClipError):
                FramingSettings.from_dict(payload)

    def test_conversion_does_not_mutate_input_on_success_or_failure(self):
        for payload in (
            {"mode": "smart_crop", "focus_point": {"x": 0.5, "y": 0.5}},
            {"focus_point": {"x": 0.5, "y": 0.5}, "tracking_intensity": -1},
        ):
            original = copy.deepcopy(payload)
            try:
                FramingSettings.from_dict(payload)
            except ClipError:
                pass
            self.assertEqual(payload, original)
            self.assertIsInstance(payload["focus_point"], dict)


class InitialPlanTests(unittest.TestCase):
    def plan(self, settings, **options):
        values = dict(source_width=1920, source_height=1080, start=10, end=40)
        values.update(options)
        return build_initial_plan(settings=settings, **values)

    def test_missing_automatic_evidence_preserves_frame(self):
        for mode in ("auto", "smart_crop"):
            with self.subTest(mode=mode):
                plan = self.plan(FramingSettings(mode=mode))
                self.assertEqual(plan.selected_mode, "full_gameplay")
                self.assertEqual(plan.confidence, 0)
                self.assertEqual(plan.keyframes, ())
                self.assertIn("not implemented", plan.fallback_reason)

    def test_explicit_full_gameplay_needs_no_fallback_explanation(self):
        plan = self.plan(FramingSettings(mode="full_gameplay"))
        self.assertEqual(plan.selected_mode, "full_gameplay")
        self.assertIsNone(plan.fallback_reason)

    def test_manual_focus_produces_static_crop_for_each_ratio(self):
        for mode in ("auto", "smart_crop"):
            for ratio in ("9:16", "16:9", "1:1", "4:5"):
                with self.subTest(mode=mode, ratio=ratio):
                    focus = FocusPoint(1, 0.5)
                    plan = self.plan(FramingSettings(mode=mode, focus_point=focus), aspect_ratio=ratio)
                    self.assertEqual(plan.selected_mode, "smart_crop")
                    self.assertEqual(plan.keyframes[0].time, 0)
                    self.assertEqual(plan.keyframes[0].crop,
                                     crop_for_focus(1920, 1080, focus, aspect_ratio=ratio))
                    self.assertEqual(len(plan.keyframes), 1)

    def test_region_retention_decides_crop_or_preservation(self):
        fitting = Region(0.4, 0.3, 0.1, 0.2)
        plan = self.plan(FramingSettings(mode="smart_crop", focus_region=fitting))
        self.assertEqual(plan.selected_mode, "smart_crop")
        self.assertGreaterEqual(region_coverage(plan.keyframes[0].crop, fitting, 1920, 1080), 0.98)
        oversized = self.plan(FramingSettings(mode="smart_crop", focus_region=Region(0, 0, 1, 1)))
        self.assertEqual(oversized.selected_mode, "full_gameplay")
        self.assertIn("cannot fit", oversized.fallback_reason)
        self.assertEqual(oversized.keyframes, ())

    def test_explicit_webcam_selects_split_and_missing_webcam_falls_back(self):
        for mode in ("auto", "streamer_gameplay"):
            plan = self.plan(FramingSettings(mode=mode, webcam_region=Region(0, 0, 0.2, 0.2)))
            self.assertEqual(plan.selected_mode, "streamer_gameplay")
            self.assertEqual(plan.confidence, 1)
            self.assertEqual(plan.keyframes, ())
        missing = self.plan(FramingSettings(mode="streamer_gameplay"))
        self.assertEqual(missing.selected_mode, "full_gameplay")
        self.assertIn("No webcam region", missing.fallback_reason)

    def test_webcam_allows_explicit_and_auto_split_for_all_shapes(self):
        webcam = Region(0, 0, 0.2, 0.2)
        for mode in ("streamer_gameplay", "auto"):
            for ratio in ("9:16", "16:9", "1:1", "4:5"):
                with self.subTest(mode=mode, ratio=ratio):
                    plan = self.plan(FramingSettings(mode=mode, webcam_region=webcam), aspect_ratio=ratio)
                    self.assertEqual(plan.selected_mode, "streamer_gameplay")

    def test_tiny_source_uses_preserving_fallback(self):
        plan = self.plan(FramingSettings(mode="smart_crop", focus_point=FocusPoint(0.5, 0.5)),
                         source_width=16, source_height=16)
        self.assertEqual(plan.selected_mode, "full_gameplay")
        self.assertIn("too small", plan.fallback_reason)

    def test_invalid_settings_source_interval_and_ratio_are_rejected(self):
        with self.assertRaises(ClipError):
            self.plan(None)
        for options in ({"source_width": 0}, {"start": -1}, {"end": 20},
                        {"end": math.inf}, {"aspect_ratio": "5:4"}):
            with self.subTest(options=options), self.assertRaises(ClipError):
                self.plan(FramingSettings(mode="smart_crop", focus_point=FocusPoint(0.5, 0.5)), **options)


if __name__ == "__main__":
    unittest.main()
