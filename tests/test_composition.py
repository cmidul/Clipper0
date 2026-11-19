"""Composition contract checks; actual FFmpeg validation is a separate step."""

import unittest

from autoclip.composition import build_filtergraph, split_panel_heights
from autoclip.engine import ClipError, output_dimensions
from autoclip.reframing import (
    CropKeyframe, FocusPoint, FramingPlan, FramingSettings, Region, crop_for_focus,
)


CANVASES_480 = {"9:16": (480, 854), "16:9": (854, 480), "1:1": (480, 480), "4:5": (480, 600)}


class CompositionTests(unittest.TestCase):
    def plan(self, mode="full_gameplay", *, width=1920, height=1080, keyframes=()):
        return FramingPlan(width, height, 0, 15, mode, mode, 1, keyframes=keyframes)

    def test_preserving_layouts_support_all_output_ratios_and_resolutions(self):
        for ratio in CANVASES_480:
            for resolution in (480, 720, 1080):
                for background in ("pad", "blur"):
                    with self.subTest(ratio=ratio, resolution=resolution, background=background):
                        result = build_filtergraph(
                            self.plan(), FramingSettings(mode="full_gameplay", background=background),
                            resolution=resolution, aspect_ratio=ratio,
                        )
                        expected = output_dimensions(resolution, ratio)
                        self.assertEqual((result.width, result.height), expected)
                        self.assertEqual(result.output_label, "[framed]")
                        self.assertTrue(result.filtergraph.endswith("[framed]"))

    def test_split_accepts_contained_webcam_at_frame_edges(self):
        for width, height in ((1920, 1080), (1919, 1079)):
            for region in (Region(0, 0, 0.2, 0.2), Region(0.8, 0.8, 0.2, 0.2)):
                with self.subTest(source=(width, height), region=region):
                    result = build_filtergraph(
                        self.plan("streamer_gameplay", width=width, height=height),
                        FramingSettings(mode="streamer_gameplay", webcam_region=region),
                    )
                    self.assertEqual((result.width, result.height), (720, 1280))

    def test_split_uses_even_panels_for_all_shapes_and_requires_webcam(self):
        plan = self.plan("streamer_gameplay")
        with self.assertRaisesRegex(ClipError, "webcam region"):
            build_filtergraph(plan, FramingSettings(mode="streamer_gameplay"))
        settings = FramingSettings(mode="streamer_gameplay", webcam_region=Region(0, 0, 0.2, 0.2))
        for ratio, (width, height) in CANVASES_480.items():
            with self.subTest(ratio=ratio):
                result = build_filtergraph(plan, settings, aspect_ratio=ratio, resolution=480)
                top, bottom = split_panel_heights(height)
                self.assertEqual((result.width, result.height), (width, height))
                self.assertEqual(top + bottom, height)
                self.assertEqual((top % 2, bottom % 2), (0, 0))
                self.assertIn(f"pad={width}:{top}", result.filtergraph)
                self.assertIn(f"pad={width}:{bottom}", result.filtergraph)
        with self.assertRaisesRegex(ClipError, "too small"):
            build_filtergraph(
                self.plan("streamer_gameplay", width=1919, height=1079),
                FramingSettings(mode="streamer_gameplay", webcam_region=Region(0.9999, 0.9999, 0.0001, 0.0001)),
            )

    def test_nominal_focus_crop_matches_each_even_480p_canvas(self):
        for ratio, (width, height) in CANVASES_480.items():
            with self.subTest(ratio=ratio):
                crop = crop_for_focus(1920, 1080, FocusPoint(0.9, 0.5), aspect_ratio=ratio)
                result = build_filtergraph(
                    self.plan("smart_crop", keyframes=(CropKeyframe(0, crop, 1),)),
                    FramingSettings(mode="smart_crop"), aspect_ratio=ratio, resolution=480,
                )
                self.assertEqual((result.width, result.height), (width, height))
                self.assertIn(f"pad={width}:{height}", result.filtergraph)

    def test_static_crop_rejects_output_ratio_mismatch(self):
        crop = crop_for_focus(1920, 1080)
        with self.assertRaisesRegex(ClipError, "aspect ratio"):
            build_filtergraph(
                self.plan("smart_crop", keyframes=(CropKeyframe(0, crop, 1),)),
                FramingSettings(mode="smart_crop"), aspect_ratio="16:9",
            )

    def test_motion_uses_easing_and_zoom_requires_confident_events(self):
        crop = crop_for_focus(1920, 1080)
        second = crop_for_focus(1920, 1080, FocusPoint(0.9, 0.5))
        result = build_filtergraph(
            self.plan("smart_crop", keyframes=(CropKeyframe(0, crop, 1), CropKeyframe(5, second, 1))),
            FramingSettings(mode="smart_crop"))
        self.assertIn("cos(PI", result.filtergraph)
        unzoomed = build_filtergraph(self.plan(), FramingSettings(mode="full_gameplay", emphasis_zoom=True))
        self.assertNotIn("eval=frame", unzoomed.filtergraph)

    def test_settings_mismatch_and_invalid_output_fail(self):
        for options in ({"resolution": 360}, {"aspect_ratio": "5:4"}):
            with self.subTest(options=options), self.assertRaises(ClipError):
                build_filtergraph(self.plan(), FramingSettings(mode="full_gameplay"), **options)
        with self.assertRaisesRegex(ClipError, "requested mode"):
            build_filtergraph(self.plan(), FramingSettings(mode="smart_crop"))
        with self.assertRaises(ClipError):
            build_filtergraph(None, FramingSettings())
        with self.assertRaises(ClipError):
            build_filtergraph(self.plan(), None)

    def test_nontracking_layouts_reject_unused_crop_tracks(self):
        frames = (CropKeyframe(0, crop_for_focus(1920, 1080), 1),)
        for mode in ("full_gameplay", "streamer_gameplay"):
            with self.subTest(mode=mode), self.assertRaisesRegex(ClipError, "keyframes"):
                build_filtergraph(
                    self.plan(mode, keyframes=frames),
                    FramingSettings(mode=mode, webcam_region=Region(0, 0, 0.2, 0.2)),
                )


if __name__ == "__main__":
    unittest.main()
