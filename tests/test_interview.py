"""Tests for the Socratic interview engine."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.interview import (
    AMBIGUITY_THRESHOLD,
    AmbiguityScore,
    DimensionScore,
    InterviewState,
    compute_ambiguity,
    detect_brownfield,
    generate_clarification_targets,
    get_scoring_dimensions,
    load_state,
    save_state,
)


class TestBrownfieldDetection(unittest.TestCase):

    def test_detects_pyproject(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "pyproject.toml").touch()
            self.assertTrue(detect_brownfield(tmpdir))

    def test_detects_package_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "package.json").touch()
            self.assertTrue(detect_brownfield(tmpdir))

    def test_detects_src_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "src").mkdir()
            self.assertTrue(detect_brownfield(tmpdir))

    def test_empty_dir_is_greenfield(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertFalse(detect_brownfield(tmpdir))

    def test_empty_path(self) -> None:
        self.assertFalse(detect_brownfield(""))

    def test_nonexistent_path(self) -> None:
        self.assertFalse(detect_brownfield("/nonexistent/path"))


class TestScoringDimensions(unittest.TestCase):

    def test_greenfield_has_3_dimensions(self) -> None:
        dims = get_scoring_dimensions(is_brownfield=False)
        self.assertEqual(len(dims), 3)
        weights = sum(w for _, w in dims)
        self.assertAlmostEqual(weights, 1.0)

    def test_brownfield_has_4_dimensions(self) -> None:
        dims = get_scoring_dimensions(is_brownfield=True)
        self.assertEqual(len(dims), 4)
        weights = sum(w for _, w in dims)
        self.assertAlmostEqual(weights, 1.0)


class TestAmbiguityScoring(unittest.TestCase):

    def test_all_clear(self) -> None:
        dims = [
            DimensionScore("scope", 1.0, 0.4),
            DimensionScore("constraints", 1.0, 0.3),
            DimensionScore("acceptance", 1.0, 0.3),
        ]
        score = compute_ambiguity(dims)
        self.assertAlmostEqual(score.overall, 0.0)
        self.assertTrue(score.is_ready)

    def test_all_ambiguous(self) -> None:
        dims = [
            DimensionScore("scope", 0.0, 0.4),
            DimensionScore("constraints", 0.0, 0.3),
            DimensionScore("acceptance", 0.0, 0.3),
        ]
        score = compute_ambiguity(dims)
        self.assertAlmostEqual(score.overall, 1.0)
        self.assertFalse(score.is_ready)

    def test_threshold_boundary(self) -> None:
        # 80% clarity = 0.2 ambiguity = ready
        dims = [
            DimensionScore("scope", 0.8, 0.4),
            DimensionScore("constraints", 0.8, 0.3),
            DimensionScore("acceptance", 0.8, 0.3),
        ]
        score = compute_ambiguity(dims)
        self.assertAlmostEqual(score.overall, 0.2)
        self.assertTrue(score.is_ready)

    def test_just_above_threshold(self) -> None:
        dims = [
            DimensionScore("scope", 0.7, 0.4),
            DimensionScore("constraints", 0.7, 0.3),
            DimensionScore("acceptance", 0.7, 0.3),
        ]
        score = compute_ambiguity(dims)
        self.assertAlmostEqual(score.overall, 0.3)
        self.assertFalse(score.is_ready)


class TestClarificationTargets(unittest.TestCase):

    def test_identifies_weak_dimensions(self) -> None:
        dims = [
            DimensionScore("scope", 0.9, 0.4),
            DimensionScore("constraints", 0.5, 0.3),
            DimensionScore("acceptance", 0.3, 0.3),
        ]
        targets = generate_clarification_targets(dims)
        self.assertIn("constraints", targets)
        self.assertIn("acceptance", targets)
        self.assertNotIn("scope", targets)


class TestStatePersistence(unittest.TestCase):

    def test_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = InterviewState(
                interview_id="test-123",
                initial_context="Build a CLI tool",
                is_brownfield=False,
            )
            save_state(state, Path(tmpdir))
            loaded = load_state("test-123", Path(tmpdir))
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.interview_id, "test-123")
            self.assertEqual(loaded.initial_context, "Build a CLI tool")

    def test_load_nonexistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            loaded = load_state("nonexistent", Path(tmpdir))
            self.assertIsNone(loaded)

    def test_roundtrip_with_rounds(self) -> None:
        from src.interview import InterviewRound
        with tempfile.TemporaryDirectory() as tmpdir:
            state = InterviewState(
                interview_id="test-456",
                initial_context="Build a web app",
            )
            state.rounds.append(InterviewRound(
                round_number=1,
                question="What problem does this solve?",
                answer="It manages tasks",
            ))
            save_state(state, Path(tmpdir))
            loaded = load_state("test-456", Path(tmpdir))
            assert loaded is not None
            self.assertEqual(len(loaded.rounds), 1)
            self.assertEqual(loaded.rounds[0].answer, "It manages tasks")


if __name__ == "__main__":
    unittest.main()
