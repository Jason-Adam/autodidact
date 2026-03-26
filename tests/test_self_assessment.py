"""Tests for src.self_assessment module."""

from __future__ import annotations

import unittest

from src.interview import DimensionScore
from src.self_assessment import (
    ASSESSMENT_DIMENSIONS,
    PIVOT_THRESHOLD,
    UNBLOCKING_THRESHOLD,
    AssessmentResult,
    build_assessment_prompt,
    parse_assessment_block,
    score_assessment,
)


class TestParseAssessmentBlock(unittest.TestCase):
    def test_parses_valid_block(self):
        text = (
            "Some preamble text.\n"
            "---SELF_ASSESSMENT---\n"
            "blocker_id: 0.3 | cannot find the API endpoint\n"
            "approach_viability: 0.7 | still viable\n"
            "scope_alignment: 0.9 | on track\n"
            "unblocking_paths: 0.5 | two options\n"
            "strategy_adjustment: try alternative endpoint\n"
            "---END_SELF_ASSESSMENT---\n"
            "Some trailing text."
        )
        result = parse_assessment_block(text)
        assert result is not None
        assert result["blocker_id"] == "0.3 | cannot find the API endpoint"
        assert result["approach_viability"] == "0.7 | still viable"
        assert result["strategy_adjustment"] == "try alternative endpoint"

    def test_returns_none_when_block_missing(self):
        text = "No assessment block here.\nJust regular output."
        result = parse_assessment_block(text)
        assert result is None

    def test_returns_none_for_partial_block(self):
        text = "---SELF_ASSESSMENT---\nblocker_id: 0.5\nNo end marker"
        result = parse_assessment_block(text)
        assert result is None

    def test_handles_empty_block(self):
        text = "---SELF_ASSESSMENT---\n\n---END_SELF_ASSESSMENT---"
        result = parse_assessment_block(text)
        assert result is not None
        assert len(result) == 0

    def test_skips_lines_without_colon(self):
        text = (
            "---SELF_ASSESSMENT---\n"
            "blocker_id: 0.5\n"
            "just a note\n"
            "approach_viability: 0.8\n"
            "---END_SELF_ASSESSMENT---"
        )
        result = parse_assessment_block(text)
        assert result is not None
        assert len(result) == 2

    def test_parses_block_with_crlf_line_endings(self):
        text = "---SELF_ASSESSMENT---\r\nblocker_id: 0.5\r\n---END_SELF_ASSESSMENT---"
        result = parse_assessment_block(text)
        assert result is not None
        assert result["blocker_id"] == "0.5"


class TestScoreAssessment(unittest.TestCase):
    def test_scores_all_dimensions(self):
        parsed = {
            "blocker_id": "0.8 | identified",
            "approach_viability": "0.7 | viable",
            "scope_alignment": "0.9 | aligned",
            "unblocking_paths": "0.6 | paths found",
        }
        result = score_assessment(parsed)
        assert len(result.scores) == len(ASSESSMENT_DIMENSIONS)
        names = {s.name for s in result.scores}
        assert names == {name for name, _ in ASSESSMENT_DIMENSIONS}

    def test_clarity_calculation(self):
        # All dimensions at 1.0 -> overall clarity should be 1.0
        parsed = {
            "blocker_id": "1.0",
            "approach_viability": "1.0",
            "scope_alignment": "1.0",
            "unblocking_paths": "1.0",
        }
        result = score_assessment(parsed)
        assert abs(result.overall_clarity - 1.0) < 0.01

    def test_zero_clarity(self):
        # All dimensions at 0.0 -> overall clarity should be 0.0
        parsed = {
            "blocker_id": "0.0",
            "approach_viability": "0.0",
            "scope_alignment": "0.0",
            "unblocking_paths": "0.0",
        }
        result = score_assessment(parsed)
        assert abs(result.overall_clarity - 0.0) < 0.01

    def test_missing_dimensions_default_to_zero(self):
        parsed = {"blocker_id": "0.8"}
        result = score_assessment(parsed)
        assert len(result.scores) == len(ASSESSMENT_DIMENSIONS)
        missing = [s for s in result.scores if s.name != "blocker_id"]
        assert all(s.clarity == 0.0 for s in missing)

    def test_invalid_score_defaults_to_zero(self):
        parsed = {"blocker_id": "not_a_number | oops"}
        result = score_assessment(parsed)
        blocker = next(s for s in result.scores if s.name == "blocker_id")
        assert blocker.clarity == 0.0

    def test_score_clamped_to_range(self):
        parsed = {
            "blocker_id": "1.5",
            "approach_viability": "-0.3",
        }
        result = score_assessment(parsed)
        blocker = next(s for s in result.scores if s.name == "blocker_id")
        approach = next(s for s in result.scores if s.name == "approach_viability")
        assert blocker.clarity == 1.0
        assert approach.clarity == 0.0

    def test_strategy_adjustment_extracted(self):
        parsed = {
            "blocker_id": "0.5",
            "strategy_adjustment": "try a different approach",
        }
        result = score_assessment(parsed)
        assert result.strategy_adjustment == "try a different approach"

    def test_justification_extracted(self):
        parsed = {"blocker_id": "0.5 | the root cause is unclear"}
        result = score_assessment(parsed)
        blocker = next(s for s in result.scores if s.name == "blocker_id")
        assert blocker.justification == "the root cause is unclear"


class TestAssessmentResult(unittest.TestCase):
    def test_should_pivot_when_approach_low(self):
        scores = [
            DimensionScore("approach_viability", 0.3, 0.30),
            DimensionScore("blocker_id", 0.8, 0.35),
        ]
        result = AssessmentResult(scores=scores, overall_clarity=0.5)
        assert result.should_pivot is True

    def test_should_not_pivot_when_approach_high(self):
        scores = [
            DimensionScore("approach_viability", 0.8, 0.30),
            DimensionScore("blocker_id", 0.8, 0.35),
        ]
        result = AssessmentResult(scores=scores, overall_clarity=0.8)
        assert result.should_pivot is False

    def test_should_not_pivot_when_no_approach_dimension(self):
        scores = [DimensionScore("blocker_id", 0.8, 0.35)]
        result = AssessmentResult(scores=scores, overall_clarity=0.8)
        assert result.should_pivot is False

    def test_should_not_pivot_when_approach_low_but_unblocking_high(self):
        """Low viability + high escape routes = recoverable, don't pivot."""
        scores = [
            DimensionScore("approach_viability", 0.3, 0.30),
            DimensionScore("unblocking_paths", 0.8, 0.15),
            DimensionScore("blocker_id", 0.5, 0.35),
        ]
        result = AssessmentResult(scores=scores, overall_clarity=0.5)
        assert result.should_pivot is False

    def test_should_pivot_when_approach_low_and_unblocking_low(self):
        """Low viability + no escape routes = true dead end, pivot."""
        scores = [
            DimensionScore("approach_viability", 0.3, 0.30),
            DimensionScore("unblocking_paths", 0.2, 0.15),
            DimensionScore("blocker_id", 0.5, 0.35),
        ]
        result = AssessmentResult(scores=scores, overall_clarity=0.3)
        assert result.should_pivot is True

    def test_should_pivot_when_approach_low_and_unblocking_missing(self):
        """Low viability + missing unblocking dimension = fallback to pivot."""
        scores = [
            DimensionScore("approach_viability", 0.3, 0.30),
            DimensionScore("blocker_id", 0.8, 0.35),
        ]
        result = AssessmentResult(scores=scores, overall_clarity=0.5)
        assert result.should_pivot is True

    def test_pivot_boundary_at_unblocking_threshold(self):
        """Exactly at UNBLOCKING_THRESHOLD = no pivot (threshold is exclusive)."""
        scores = [
            DimensionScore("approach_viability", 0.3, 0.30),
            DimensionScore("unblocking_paths", UNBLOCKING_THRESHOLD, 0.15),
        ]
        result = AssessmentResult(scores=scores, overall_clarity=0.4)
        assert result.should_pivot is False

    def test_pivot_boundary_at_pivot_threshold(self):
        """Exactly at PIVOT_THRESHOLD = no pivot (threshold is exclusive)."""
        scores = [
            DimensionScore("approach_viability", PIVOT_THRESHOLD, 0.30),
            DimensionScore("unblocking_paths", 0.1, 0.15),
        ]
        result = AssessmentResult(scores=scores, overall_clarity=0.4)
        assert result.should_pivot is False


class TestBuildAssessmentPrompt(unittest.TestCase):
    def test_prompt_contains_dimensions(self):
        prompt = build_assessment_prompt()
        for name, _ in ASSESSMENT_DIMENSIONS:
            assert name in prompt

    def test_prompt_contains_delimiters(self):
        prompt = build_assessment_prompt()
        assert "---SELF_ASSESSMENT---" in prompt
        assert "---END_SELF_ASSESSMENT---" in prompt


class TestDimensionWeights(unittest.TestCase):
    def test_weights_sum_to_one(self):
        total = sum(w for _, w in ASSESSMENT_DIMENSIONS)
        assert abs(total - 1.0) < 0.001


if __name__ == "__main__":
    unittest.main()
