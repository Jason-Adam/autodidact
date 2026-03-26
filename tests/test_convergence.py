"""Tests for convergence signal detection."""

from __future__ import annotations

import unittest

from src.convergence import (
    ExperimentEntry,
    detect_signals,
)


def _make_entry(
    num: int,
    status: str,
    metric: float | None = None,
    files: list[str] | None = None,
) -> ExperimentEntry:
    """Minimal ExperimentEntry factory for tests."""
    return ExperimentEntry(
        experiment_num=num,
        status=status,
        metric_value=metric,
        files_touched=files or [],
        duration_seconds=1.0,
        description=f"experiment {num}",
        timestamp="2026-01-01T00:00:00Z",
    )


class TestConvergence(unittest.TestCase):
    # ── Edge cases ───────────────────────────────────────────────────

    def test_empty_entries(self) -> None:
        signals = detect_signals([])
        self.assertEqual(signals, [])

    def test_single_entry(self) -> None:
        signals = detect_signals([_make_entry(1, "keep", metric=0.5)])
        self.assertEqual(signals, [])

    # ── Plateau ──────────────────────────────────────────────────────

    def test_plateau_detected(self) -> None:
        entries = [
            _make_entry(1, "keep", metric=0.800),
            _make_entry(2, "keep", metric=0.800),
            _make_entry(3, "keep", metric=0.800),
        ]
        signals = detect_signals(entries)
        types = [s.signal_type for s in signals]
        self.assertIn("plateau", types)

    def test_no_plateau_with_improvement(self) -> None:
        entries = [
            _make_entry(1, "keep", metric=0.50),
            _make_entry(2, "keep", metric=0.70),
            _make_entry(3, "keep", metric=0.90),
        ]
        signals = detect_signals(entries)
        types = [s.signal_type for s in signals]
        self.assertNotIn("plateau", types)

    # ── Consecutive discards ─────────────────────────────────────────

    def test_consecutive_discards(self) -> None:
        entries = [
            _make_entry(1, "keep"),
            _make_entry(2, "discard"),
            _make_entry(3, "discard"),
            _make_entry(4, "discard"),
            _make_entry(5, "discard"),
            _make_entry(6, "discard"),
        ]
        signals = detect_signals(entries)
        types = [s.signal_type for s in signals]
        self.assertIn("consecutive_discards", types)

    def test_mixed_discards_no_signal(self) -> None:
        entries = [
            _make_entry(1, "discard"),
            _make_entry(2, "discard"),
            _make_entry(3, "keep"),  # resets the streak
            _make_entry(4, "discard"),
            _make_entry(5, "discard"),
        ]
        signals = detect_signals(entries)
        types = [s.signal_type for s in signals]
        self.assertNotIn("consecutive_discards", types)

    # ── Alternating ──────────────────────────────────────────────────

    def test_alternating_custom_ratio(self) -> None:
        from src.convergence import ConvergenceThresholds

        # Imperfect alternation: ratio = 3/5 = 0.6
        entries = [
            _make_entry(1, "keep"),
            _make_entry(2, "keep"),  # no alternation
            _make_entry(3, "discard"),
            _make_entry(4, "keep"),
            _make_entry(5, "keep"),  # no alternation
            _make_entry(6, "discard"),
        ]
        # Default ratio 0.8 should NOT fire (3/5 = 0.6 < 0.8)
        signals = detect_signals(entries)
        types = [s.signal_type for s in signals]
        self.assertNotIn("alternating", types)

        # With a lower threshold, it should fire
        low_threshold = ConvergenceThresholds(alternating_ratio=0.5)
        signals = detect_signals(entries, low_threshold)
        types = [s.signal_type for s in signals]
        self.assertIn("alternating", types)

    def test_alternating_detected(self) -> None:
        entries = [
            _make_entry(1, "keep"),
            _make_entry(2, "discard"),
            _make_entry(3, "keep"),
            _make_entry(4, "discard"),
            _make_entry(5, "keep"),
            _make_entry(6, "discard"),
        ]
        signals = detect_signals(entries)
        types = [s.signal_type for s in signals]
        self.assertIn("alternating", types)

    # ── Code repetition ──────────────────────────────────────────────

    def test_code_repetition(self) -> None:
        repeated_file = "src/main.py"
        entries = [
            _make_entry(1, "keep", files=[repeated_file, "src/other.py"]),
            _make_entry(2, "discard", files=[repeated_file]),
            _make_entry(3, "keep", files=[repeated_file, "tests/test_main.py"]),
        ]
        signals = detect_signals(entries)
        types = [s.signal_type for s in signals]
        self.assertIn("code_repetition", types)

    # ── Timeout streak ───────────────────────────────────────────────

    def test_timeout_streak(self) -> None:
        entries = [
            _make_entry(1, "keep"),
            _make_entry(2, "timeout"),
            _make_entry(3, "timeout"),
        ]
        signals = detect_signals(entries)
        types = [s.signal_type for s in signals]
        self.assertIn("timeout_streak", types)

    # ── Consecutive interesting ────────────────────────────────────────

    def test_consecutive_interesting_detected(self) -> None:
        entries = [
            _make_entry(1, "keep"),
            _make_entry(2, "interesting"),
            _make_entry(3, "interesting"),
            _make_entry(4, "interesting"),
            _make_entry(5, "interesting"),
        ]
        signals = detect_signals(entries)
        types = [s.signal_type for s in signals]
        self.assertIn("consecutive_interesting", types)

    def test_consecutive_interesting_broken_by_keep(self) -> None:
        entries = [
            _make_entry(1, "interesting"),
            _make_entry(2, "interesting"),
            _make_entry(3, "keep"),
            _make_entry(4, "interesting"),
            _make_entry(5, "interesting"),
        ]
        signals = detect_signals(entries)
        types = [s.signal_type for s in signals]
        self.assertNotIn("consecutive_interesting", types)

    # ── Consecutive thoughts ──────────────────────────────────────────

    def test_consecutive_thoughts_detected(self) -> None:
        entries = [
            _make_entry(1, "keep"),
            _make_entry(2, "thought"),
            _make_entry(3, "thought"),
            _make_entry(4, "thought"),
            _make_entry(5, "thought"),
        ]
        signals = detect_signals(entries)
        types = [s.signal_type for s in signals]
        self.assertIn("consecutive_thoughts", types)

    def test_consecutive_thoughts_broken_by_discard(self) -> None:
        entries = [
            _make_entry(1, "thought"),
            _make_entry(2, "thought"),
            _make_entry(3, "discard"),
            _make_entry(4, "thought"),
            _make_entry(5, "thought"),
        ]
        signals = detect_signals(entries)
        types = [s.signal_type for s in signals]
        self.assertNotIn("consecutive_thoughts", types)

    # ── Multiple signals ─────────────────────────────────────────────

    def test_multiple_signals(self) -> None:
        # Plateau: 3 keeps with identical metric
        # Consecutive discards: 5 trailing discards
        # Timeout streak won't fire (last entries are discards, not timeouts)
        # Build a history that triggers plateau AND consecutive_discards:
        #   first N keeps with same metric, then 5 discards
        repeated_file = "src/hot.py"
        entries = [
            # plateau fodder
            _make_entry(1, "keep", metric=0.5, files=[repeated_file]),
            _make_entry(2, "keep", metric=0.5, files=[repeated_file]),
            _make_entry(3, "keep", metric=0.5, files=[repeated_file]),
            # discard streak
            _make_entry(4, "discard"),
            _make_entry(5, "discard"),
            _make_entry(6, "discard"),
            _make_entry(7, "discard"),
            _make_entry(8, "discard"),
        ]
        signals = detect_signals(entries)
        types = [s.signal_type for s in signals]
        self.assertIn("plateau", types)
        self.assertIn("consecutive_discards", types)
        self.assertGreaterEqual(len(signals), 2)


if __name__ == "__main__":
    unittest.main()
