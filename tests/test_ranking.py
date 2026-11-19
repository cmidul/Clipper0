from dataclasses import replace
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from autoclip.engine import Candidate, ClipError, Media, Settings, process, select_candidates
from autoclip.ranking import RankingSettings, cue_matches, interval_iou


class RankingTests(unittest.TestCase):
    def test_quiet_reaction_generates_candidate_without_an_audio_peak(self):
        segments = [{"start": 40, "end": 44, "text": "No way!"}]
        self.assertEqual(select_candidates([0.02] * 90, 90), [])
        candidates = select_candidates([0.02] * 90, 90, segments=segments, language="en")
        self.assertEqual(len(candidates), 1)
        self.assertIn("no way", candidates[0].evidence["cue_matches"])
        self.assertGreater(candidates[0].evidence["speech_activity"], 0)

    def test_cues_are_language_specific_and_use_whole_tokens(self):
        segments = [{"start": 40, "end": 44, "text": "No way!"}]
        self.assertEqual(select_candidates([], 90, segments=segments, language="fr"), [])
        self.assertEqual(cue_matches("Amazingly ordinary", ["amazing"]), [])
        self.assertEqual(cue_matches("LET’S GO!", ["let's go"]), ["let's go"])
        self.assertEqual(cue_matches("দারুণ! বাঁচাও", ["দারুণ", "বাঁচাও"]), ["দারুণ", "বাঁচাও"])

    def test_unlisted_language_uses_speech_and_audio_without_english_cues(self):
        activity = [0.001] * 90
        activity[42] = 1
        candidates = select_candidates(activity, 90, segments=[
            {"start": 40, "end": 44, "text": "No way"},
        ], language="fr")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].evidence["cue_matches"], [])
        self.assertGreater(candidates[0].evidence["speech_activity"], 0)

    def test_contributions_explain_score_and_stay_normalized(self):
        activity = [0.001] * 90
        activity[42] = 1
        candidate = select_candidates(activity, 90, segments=[
            {"start": 40, "end": 44, "text": "Amazing"},
        ], language="en")[0]
        self.assertAlmostEqual(candidate.score, sum(candidate.evidence["contributions"].values()), places=5)
        self.assertGreaterEqual(candidate.score, 0)
        self.assertLessEqual(candidate.score, 1)
        self.assertEqual(candidate.evidence["score_kind"], "heuristic")

    def test_overlapping_speech_does_not_inflate_coverage(self):
        segments = [{"start": 0, "end": 90, "text": "amazing"}] * 3
        candidate = select_candidates([], 90, segments=segments, language="en")[0]
        self.assertEqual(candidate.evidence["speech_activity"], 1)

    def test_threshold_can_return_zero_candidates(self):
        activity = [0.001] * 90
        activity[42] = 1
        config = replace(RankingSettings(), min_score=1)
        self.assertEqual(select_candidates(activity, 90, config=config), [])

    def test_weight_changes_affect_ranking(self):
        activity = [0.001] * 120
        activity[10] = 1
        segments = [{"start": 80, "end": 84, "text": "amazing"}]
        config = replace(RankingSettings(), weights={
            "audio_peak": 0, "audio_onset": 0, "speech_activity": 0, "transcript_cues": 1,
        })
        candidates = select_candidates(activity, 120, 15, segments=segments, language="en", config=config)
        self.assertEqual(len(candidates), 1)
        self.assertLessEqual(candidates[0].start, 82)
        self.assertGreaterEqual(candidates[0].end, 82)

    def test_interval_iou_and_strict_gap_suppress_duplicates(self):
        self.assertAlmostEqual(interval_iou(Candidate(0, 30, 0, {}), Candidate(10, 40, 0, {})), 0.5)
        activity = [0.001] * 120
        for second in (5, 6, 7, 40, 41, 80):
            activity[second] = 1
        candidates = select_candidates(activity, 120, 15)
        self.assertEqual(len(candidates), 3)
        chronological = sorted(candidates, key=lambda candidate: candidate.start)
        for left, right in zip(chronological, chronological[1:]):
            self.assertEqual(interval_iou(left, right), 0)
            self.assertGreaterEqual(right.start - left.end, 2)

    def test_fractional_duration_and_analysis_padding_stay_in_bounds(self):
        activity = [0.001] * 32
        activity[15] = 1
        activity[-1] = 10
        candidates = select_candidates(activity, 15.25, 15)
        self.assertEqual(len(candidates), 1)
        self.assertLessEqual(candidates[0].evidence["event_time"], 15.25)
        self.assertLessEqual(candidates[0].end, 15.25)

    def test_iou_limit_controls_overlap_when_gap_is_explicitly_disabled(self):
        activity = [0.001] * 120
        activity[40] = 1
        activity[60] = 0.9
        strict = replace(RankingSettings(), min_gap_seconds=0, max_iou=0.1)
        relaxed = replace(strict, max_iou=0.3)
        self.assertEqual(len(select_candidates(activity, 120, config=strict)), 1)
        self.assertEqual(len(select_candidates(activity, 120, config=relaxed)), 2)

    def test_configuration_validation_and_custom_language(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ranking.json"
            path.write_text(json.dumps({"cues": {"fr": ["incroyable"]}}), encoding="utf-8")
            config = RankingSettings.from_file(path)
            candidates = select_candidates([], 90, segments=[
                {"start": 40, "end": 44, "text": "Incroyable!"},
            ], language="fr", config=config)
            self.assertEqual(len(candidates), 1)
            for raw in ({"min_score": -1}, {"weights": {"unknown": 1}}, {"extra": 1},
                        {"weights": {name: 0 for name in config.weights}},
                        {"min_score": math.nan}, {"cues": {"en": [""]}}, {"weights": []},
                        {"max_iou": 1}, {"min_gap_seconds": -1}):
                path.write_text(json.dumps(raw), encoding="utf-8")
                with self.subTest(config=raw), self.assertRaises(ClipError):
                    RankingSettings.from_file(path)

    def test_invalid_transcript_is_rejected(self):
        for segment in ({"start": math.nan, "end": 3, "text": "amazing"}, {"text": "missing times"}):
            with self.assertRaises(ClipError):
                select_candidates([], 90, segments=[segment], language="en")

    def test_labeled_synthetic_regression_cases(self):
        path = Path(__file__).parent / "fixtures" / "ranking_cases.json"
        for case in json.loads(path.read_text(encoding="utf-8")):
            with self.subTest(case=case["name"]):
                activity = [case["background"]] * case["duration"]
                for second, level in case["peaks"].items():
                    activity[int(second)] = level
                candidates = select_candidates(activity, case["duration"], 15,
                                               segments=case["segments"], language=case["language"])
                self.assertEqual(len(candidates), len(case["expected_events"]))
                for event in case["expected_events"]:
                    self.assertEqual(sum(candidate.start <= event <= candidate.end for candidate in candidates), 1)
                self.assertEqual(candidates, select_candidates(
                    activity, case["duration"], 15, segments=case["segments"], language=case["language"],
                ))

    def test_process_uses_transcript_before_selecting_without_caption_overlay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = Media(root / "input.mp4", 90, 100, 100, "h264", True, 1)
            transcript = {"segments": [{"start": 40, "end": 44, "text": "Amazing"}], "language": "en"}
            with patch("autoclip.engine.inspect_media", return_value=media), \
                    patch("autoclip.engine.audio_activity", return_value=[0.02] * 90), \
                    patch("autoclip.speech.transcribe_media", return_value=transcript), \
                    patch("autoclip.engine.render_clip") as renderer:
                path = process(media.path, Settings(root), speech_ranking=True)
            manifest = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["state"], "completed")
            self.assertEqual(len(manifest["clips"]), 1)
            self.assertEqual(manifest["caption_status"], "disabled")
            self.assertIsNone(renderer.call_args.kwargs["subtitle_path"])
            self.assertIn("amazing", manifest["clips"][0]["evidence"]["cue_matches"])


if __name__ == "__main__":
    unittest.main()
