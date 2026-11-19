"""Pipeline orchestration checks; synthetic encoder output is explicitly mocked."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from autoclip.engine import Candidate, ClipError, JobCancelled, Media, Settings, process
from autoclip.reframing import FocusPoint, FramingSettings, build_initial_plan


class FramingPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="autoclip-framing-pipeline-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.settings = Settings(self.root)
        self.media = Media(self.root / "mock source.mkv", 90, 640, 360, "h264", False, 1)
        self.candidate = Candidate(15, 30, 0.8, {"test": "mock selection"})

    def encode(self, media, candidate, destination, settings, *arguments, **options):
        # This is not a valid MP4 and is only used to test orchestration and
        # manifests. Actual encoding is covered by renderer integration tests.
        destination.write_bytes(b"mock encoder output")

    def manifest(self):
        files = list((self.root / "clips").glob("*/manifest.json"))
        self.assertEqual(len(files), 1)
        return json.loads(files[0].read_text(encoding="utf-8"))

    def test_planning_runs_only_for_selected_intervals_after_selection(self):
        events, phases = [], []
        selected = [self.candidate, Candidate(45, 60, 0.7, {})]

        def select(*arguments, **options):
            events.append("selection")
            return selected

        def plan(width, height, start, end, settings, **options):
            events.append(("plan", start, end))
            return build_initial_plan(width, height, start, end, settings, **options)

        def encode(*arguments, **options):
            events.append(("render", arguments[1].start, arguments[1].end))
            self.encode(*arguments, **options)

        framing = FramingSettings(mode="smart_crop", focus_point=FocusPoint(0.9, 0.5))
        with patch("autoclip.engine.inspect_media", return_value=self.media), \
                patch("autoclip.engine.audio_activity", return_value=[]), \
                patch("autoclip.engine.select_candidates", side_effect=select), \
                patch("autoclip.reframing.build_initial_plan", side_effect=plan), \
                patch("autoclip.engine.render_clip", side_effect=encode):
            process(self.media.path, self.settings, framing=framing,
                    progress_callback=lambda value: phases.append(value["phase"]))
        self.assertEqual(events, ["selection", ("plan", 15, 30), ("render", 15, 30),
                                  ("plan", 45, 60), ("render", 45, 60)])
        manifest = self.manifest()
        self.assertEqual(manifest["state"], "completed")
        self.assertEqual(manifest["settings"]["framing"]["focus_point"], {"x": 0.9, "y": 0.5})
        self.assertEqual([clip["framing"]["start"] for clip in manifest["clips"]], [15, 45])
        self.assertEqual(phases.count("framing"), 2)
        self.assertEqual(phases[-1], "done")

    def test_manual_interval_bypasses_selection_and_preserves_requested_times(self):
        framing = FramingSettings(mode="full_gameplay")
        with patch("autoclip.engine.inspect_media", return_value=self.media), \
                patch("autoclip.engine.select_candidates") as select, \
                patch("autoclip.engine.audio_activity") as activity, \
                patch("autoclip.engine.render_clip", side_effect=self.encode) as render:
            process(self.media.path, self.settings, start=10, end=25, framing=framing)
            select.assert_not_called()
            activity.assert_not_called()
            plan = render.call_args.kwargs["framing_plan"]
            self.assertEqual((plan.start, plan.end), (10, 25))
            self.assertIs(render.call_args.kwargs["framing_settings"], framing)

    def test_no_visual_evidence_records_conservative_fallback(self):
        with patch("autoclip.engine.inspect_media", return_value=self.media), \
                patch("autoclip.engine.render_clip", side_effect=self.encode):
            process(self.media.path, self.settings, start=10, end=25, framing=FramingSettings())
        plan = self.manifest()["clips"][0]["framing"]
        self.assertEqual(plan["requested_mode"], "auto")
        self.assertEqual(plan["selected_mode"], "full_gameplay")
        self.assertEqual(plan["confidence"], 0)
        self.assertIn("preserving", plan["fallback_reason"])

    def test_default_calls_keep_unframed_options_and_manifest(self):
        with patch("autoclip.engine.inspect_media", return_value=self.media), \
                patch("autoclip.engine.render_clip", side_effect=self.encode) as render, \
                patch("autoclip.reframing.build_initial_plan") as planner:
            process(self.media.path, self.settings, start=10, end=25)
            planner.assert_not_called()
            self.assertNotIn("framing_plan", render.call_args.kwargs)
            self.assertNotIn("framing_settings", render.call_args.kwargs)
        manifest = self.manifest()
        self.assertNotIn("framing", manifest["settings"])
        self.assertNotIn("framing", manifest["clips"][0])

    def test_invalid_settings_fail_before_media_inspection(self):
        with patch("autoclip.engine.inspect_media") as inspect:
            with self.assertRaisesRegex(ClipError, "validated framing settings"):
                process(self.media.path, self.settings, framing={"mode": "auto"})
            inspect.assert_not_called()
        self.assertFalse((self.root / "clips").exists())

    def test_unsupported_geometry_marks_job_failed_without_encoder(self):
        rotated = replace(self.media, rotation=90)
        with patch("autoclip.engine.inspect_media", return_value=rotated), \
                patch("autoclip.engine.run_tool") as tool:
            with self.assertRaisesRegex(ClipError, "unrotated"):
                process(self.media.path, self.settings, start=10, end=25,
                        framing=FramingSettings(mode="full_gameplay"))
            tool.assert_not_called()
        manifest = self.manifest()
        self.assertEqual(manifest["state"], "failed")
        self.assertEqual(manifest["clips"], [])
        self.assertIn("unrotated", manifest["error"])

    def test_cancellation_after_planning_prevents_render_and_records_status(self):
        cancelled = False

        def plan(*arguments, **options):
            nonlocal cancelled
            result = build_initial_plan(*arguments, **options)
            cancelled = True
            return result

        with patch("autoclip.engine.inspect_media", return_value=self.media), \
                patch("autoclip.reframing.build_initial_plan", side_effect=plan), \
                patch("autoclip.engine.render_clip") as render:
            with self.assertRaises(JobCancelled):
                process(self.media.path, self.settings, start=10, end=25,
                        framing=FramingSettings(), cancelled=lambda: cancelled)
            render.assert_not_called()
        manifest = self.manifest()
        self.assertEqual(manifest["state"], "cancelled")
        self.assertEqual(manifest["phase"], "cancelled")
        self.assertEqual(manifest["clips"], [])


if __name__ == "__main__":
    unittest.main()
