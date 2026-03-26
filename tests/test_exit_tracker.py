"""Tests for exit_tracker module."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from src.exit_tracker import ExitTracker


@dataclass
class FakeAnalysis:
    exit_signal: bool = False
    raw_status: str = "unknown"
    work_type: str = "unknown"
    has_permission_denials: bool = False


class TestExitTracker(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.state_path = self.tmp_dir / "exit_signals.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _make_tracker(self, plan_path: Path | None = None) -> ExitTracker:
        return ExitTracker(state_path=self.state_path, plan_path=plan_path)

    # --- reset ---

    def test_reset_clears_all_signals(self) -> None:
        tracker = self._make_tracker()
        tracker.update(1, FakeAnalysis(exit_signal=True))
        tracker.update(2, FakeAnalysis(raw_status="COMPLETE"))
        tracker.update(3, FakeAnalysis(work_type="testing"))
        tracker.reset()

        decision = tracker.evaluate()
        self.assertFalse(decision.should_exit)
        self.assertFalse(self.state_path.exists())

    # --- update ---

    def test_update_records_completion_indicator(self) -> None:
        tracker = self._make_tracker()
        tracker.update(1, FakeAnalysis(exit_signal=True))
        self.assertEqual(tracker._signals.completion_indicators, [1])

    def test_update_records_done_signal(self) -> None:
        tracker = self._make_tracker()
        tracker.update(1, FakeAnalysis(raw_status="COMPLETE"))
        self.assertEqual(tracker._signals.done_signals, [1])

    def test_update_records_test_only_loop(self) -> None:
        tracker = self._make_tracker()
        tracker.update(1, FakeAnalysis(work_type="testing"))
        self.assertEqual(tracker._signals.test_only_loops, [1])

    def test_completion_indicators_capped(self) -> None:
        tracker = self._make_tracker()
        for i in range(10):
            tracker.update(i, FakeAnalysis(exit_signal=True))
        self.assertEqual(len(tracker._signals.completion_indicators), 7)
        self.assertEqual(tracker._signals.completion_indicators, [3, 4, 5, 6, 7, 8, 9])

    # --- priority 0: permission denied ---

    def test_priority_0_permission_denied(self) -> None:
        tracker = self._make_tracker()
        analysis = FakeAnalysis(has_permission_denials=True)
        decision = tracker.evaluate(analysis)
        self.assertTrue(decision.should_exit)
        self.assertEqual(decision.reason, "permission_denied")

    # --- priority 1: test saturation ---

    def test_priority_1_test_saturation(self) -> None:
        tracker = self._make_tracker()
        for i in range(5):
            tracker.update(i, FakeAnalysis(work_type="testing"))
        decision = tracker.evaluate()
        self.assertTrue(decision.should_exit)
        self.assertEqual(decision.reason, "test_saturation")

    # --- priority 2: repeated done signals ---

    def test_priority_2_repeated_done_signals(self) -> None:
        tracker = self._make_tracker()
        for i in range(2):
            tracker.update(i, FakeAnalysis(raw_status="COMPLETE"))
        decision = tracker.evaluate()
        self.assertTrue(decision.should_exit)
        self.assertEqual(decision.reason, "repeated_done")

    # --- priority 3: safety backstop ---

    def test_priority_3_safety_backstop(self) -> None:
        tracker = self._make_tracker()
        for i in range(7):
            tracker.update(i, FakeAnalysis(exit_signal=True))
        decision = tracker.evaluate()
        self.assertTrue(decision.should_exit)
        self.assertEqual(decision.reason, "safety_circuit_breaker")

    # --- priority 4: dual condition ---

    def test_priority_4_dual_condition(self) -> None:
        tracker = self._make_tracker()
        for i in range(1, 5):  # 4 indicators to meet DCF=4
            tracker.update(i, FakeAnalysis(exit_signal=True))
        analysis = FakeAnalysis(exit_signal=True)
        decision = tracker.evaluate(analysis)
        self.assertTrue(decision.should_exit)
        self.assertEqual(decision.reason, "dual_condition")

    def test_priority_4_dual_condition_no_exit_signal(self) -> None:
        tracker = self._make_tracker()
        for i in range(1, 5):  # 4 indicators to meet DCF=4
            tracker.update(i, FakeAnalysis(exit_signal=True))
        analysis = FakeAnalysis(exit_signal=False)
        decision = tracker.evaluate(analysis)
        self.assertFalse(decision.should_exit)

    # --- priority 5: plan complete ---

    def test_priority_5_plan_complete(self) -> None:
        plan_path = self.tmp_dir / "plan.md"
        plan_path.write_text("- [x] Step 1\n- [x] Step 2\n- [x] Step 3\n")
        tracker = self._make_tracker(plan_path=plan_path)
        decision = tracker.evaluate()
        self.assertTrue(decision.should_exit)
        self.assertEqual(decision.reason, "plan_complete")

    def test_plan_complete_with_unchecked(self) -> None:
        plan_path = self.tmp_dir / "plan.md"
        plan_path.write_text("- [x] Step 1\n- [ ] Step 2\n- [x] Step 3\n")
        tracker = self._make_tracker(plan_path=plan_path)
        decision = tracker.evaluate()
        self.assertFalse(decision.should_exit)

    def test_plan_complete_no_plan_path(self) -> None:
        tracker = self._make_tracker(plan_path=None)
        decision = tracker.evaluate()
        self.assertFalse(decision.should_exit)

    # --- persistence ---

    def test_state_persists(self) -> None:
        tracker = self._make_tracker()
        tracker.update(1, FakeAnalysis(exit_signal=True))
        tracker.update(2, FakeAnalysis(raw_status="COMPLETE"))
        tracker.update(3, FakeAnalysis(work_type="testing"))

        tracker2 = self._make_tracker()
        self.assertEqual(tracker2._signals.completion_indicators, [1])
        self.assertEqual(tracker2._signals.done_signals, [2])
        self.assertEqual(tracker2._signals.test_only_loops, [3])

    # --- fresh tracker ---

    def test_no_exit_on_fresh_tracker(self) -> None:
        tracker = self._make_tracker()
        decision = tracker.evaluate()
        self.assertFalse(decision.should_exit)
        self.assertEqual(decision.reason, "")


class TestDualConditionFloorScaling(unittest.TestCase):
    """Verify DUAL_CONDITION_FLOOR = max(1, MCI - 3) scales correctly."""

    def test_mci_3_floor_is_1(self) -> None:
        self.assertEqual(max(1, 3 - 3), 1)

    def test_mci_4_floor_is_1(self) -> None:
        self.assertEqual(max(1, 4 - 3), 1)

    def test_mci_7_floor_is_4(self) -> None:
        self.assertEqual(max(1, 7 - 3), 4)

    def test_current_constants_consistent(self) -> None:
        self.assertEqual(
            ExitTracker.DUAL_CONDITION_FLOOR,
            max(1, ExitTracker.MAX_COMPLETION_INDICATORS - 3),
        )


class TestSweepBaseline(unittest.TestCase):
    """Verify current thresholds produce composite >= pre-tuning baseline."""

    def test_current_beats_baseline(self) -> None:
        from tests.exit_tracker_param_sweep import _BASELINE, build_scenarios, evaluate_params

        scenarios = build_scenarios()

        # Evaluate current constants
        current = evaluate_params(
            scenarios,
            max_completion_indicators=ExitTracker.MAX_COMPLETION_INDICATORS,
            max_test_only_loops=ExitTracker.MAX_TEST_ONLY_LOOPS,
            max_done_signals=ExitTracker.MAX_DONE_SIGNALS,
            dual_condition_floor=ExitTracker.DUAL_CONDITION_FLOOR,
        )

        # Evaluate pre-tuning baseline
        baseline = evaluate_params(scenarios, **_BASELINE)

        self.assertGreaterEqual(
            current.composite_score,
            baseline.composite_score,
            f"Current {current.composite_score:.4f} < baseline {baseline.composite_score:.4f}",
        )


if __name__ == "__main__":
    unittest.main()
