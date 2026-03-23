"""Tests for confidence scoring logic."""

from __future__ import annotations

import unittest

from src.confidence import (
    CONFIDENCE_CAP,
    CONFIDENCE_FLOOR,
    boost,
    decay,
    initial_confidence,
    is_graduation_eligible,
    is_prunable,
    time_decay,
)


class TestConfidence(unittest.TestCase):
    # ── Boost ───────────────────────────────────────────────────────

    def test_boost_default(self) -> None:
        self.assertAlmostEqual(boost(0.5), 0.65)

    def test_boost_custom_amount(self) -> None:
        self.assertAlmostEqual(boost(0.5, 0.3), 0.8)

    def test_boost_caps_at_1(self) -> None:
        self.assertAlmostEqual(boost(0.95, 0.15), CONFIDENCE_CAP)

    def test_boost_from_zero(self) -> None:
        self.assertAlmostEqual(boost(0.0), 0.15)

    # ── Decay ───────────────────────────────────────────────────────

    def test_decay_default(self) -> None:
        self.assertAlmostEqual(decay(0.5), 0.4)

    def test_decay_floors_at_0(self) -> None:
        self.assertAlmostEqual(decay(0.05, 0.10), 0.0)

    def test_decay_from_zero(self) -> None:
        self.assertAlmostEqual(decay(0.0), 0.0)

    # ── Time Decay ──────────────────────────────────────────────────

    def test_time_decay_no_days(self) -> None:
        self.assertAlmostEqual(time_decay(0.5, 0), 0.5)

    def test_time_decay_10_days(self) -> None:
        self.assertAlmostEqual(time_decay(0.5, 10), 0.4)

    def test_time_decay_floors_at_threshold(self) -> None:
        result = time_decay(0.2, 100)
        self.assertAlmostEqual(result, CONFIDENCE_FLOOR)

    def test_time_decay_negative_days(self) -> None:
        self.assertAlmostEqual(time_decay(0.5, -1), 0.5)

    # ── Graduation ──────────────────────────────────────────────────

    def test_graduation_eligible(self) -> None:
        self.assertTrue(is_graduation_eligible(0.95, 10))

    def test_graduation_low_confidence(self) -> None:
        self.assertFalse(is_graduation_eligible(0.85, 10))

    def test_graduation_low_observations(self) -> None:
        self.assertFalse(is_graduation_eligible(0.95, 3))

    def test_graduation_boundary(self) -> None:
        self.assertTrue(is_graduation_eligible(0.9, 5))

    # ── Prune ───────────────────────────────────────────────────────

    def test_prunable(self) -> None:
        self.assertTrue(is_prunable(0.05, 100))

    def test_not_prunable_high_confidence(self) -> None:
        self.assertFalse(is_prunable(0.5, 100))

    def test_not_prunable_recent(self) -> None:
        self.assertFalse(is_prunable(0.05, 30))

    # ── Initial Confidence ──────────────────────────────────────────

    def test_user_teach_confidence(self) -> None:
        self.assertAlmostEqual(initial_confidence("user_teach"), 0.7)

    def test_error_learner_confidence(self) -> None:
        self.assertAlmostEqual(initial_confidence("error_learner"), 0.5)

    def test_subagent_confidence(self) -> None:
        self.assertAlmostEqual(initial_confidence("subagent_discovery"), 0.4)

    def test_unknown_source_confidence(self) -> None:
        self.assertAlmostEqual(initial_confidence("unknown"), 0.5)


if __name__ == "__main__":
    unittest.main()
