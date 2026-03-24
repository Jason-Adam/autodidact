"""Tests for the circuit breaker."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.circuit_breaker import (
    COOLDOWN_MINUTES,
    HALF_OPEN_THRESHOLD,
    NO_PROGRESS_THRESHOLD,
    PERMISSION_DENIAL_THRESHOLD,
    SAME_ERROR_THRESHOLD,
    BreakerPhase,
    CircuitBreaker,
)


class TestCircuitBreaker(unittest.TestCase):
    def test_starts_closed(self) -> None:
        cb = CircuitBreaker()
        self.assertFalse(cb.is_open())

    def test_opens_after_threshold(self) -> None:
        cb = CircuitBreaker(max_failures=3)
        cb.record_failure("fail 1")
        cb.record_failure("fail 2")
        self.assertFalse(cb.is_open())
        tripped = cb.record_failure("fail 3")
        self.assertTrue(tripped)
        self.assertTrue(cb.is_open())

    def test_resets_on_success(self) -> None:
        cb = CircuitBreaker(max_failures=3)
        cb.record_failure("fail 1")
        cb.record_failure("fail 2")
        cb.record_success()
        self.assertFalse(cb.is_open())
        self.assertEqual(cb.state.consecutive_failures, 0)

    def test_persists_to_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cb.json"
            cb = CircuitBreaker(state_path=path, max_failures=3)
            cb.record_failure("fail 1")
            cb.record_failure("fail 2")

            # Load from file
            cb2 = CircuitBreaker(state_path=path)
            self.assertEqual(cb2.state.consecutive_failures, 2)
            self.assertFalse(cb2.is_open())

    def test_manual_reset(self) -> None:
        cb = CircuitBreaker(max_failures=2)
        cb.record_failure("fail 1")
        cb.record_failure("fail 2")
        self.assertTrue(cb.is_open())
        cb.reset()
        self.assertFalse(cb.is_open())
        self.assertEqual(cb.state.consecutive_failures, 0)

    def test_status_report(self) -> None:
        cb = CircuitBreaker(max_failures=3)
        cb.record_failure("something broke")
        status = cb.status()
        self.assertEqual(status["consecutive_failures"], 1)
        self.assertEqual(status["max_failures"], 3)
        self.assertFalse(status["is_open"])
        self.assertEqual(status["last_context"], "something broke")


# --- Fake types for 3-state tests ---


@dataclass
class FakeProgress:
    is_productive: bool = False
    files_changed: int = 0
    commits_made: int = 0
    has_uncommitted: bool = False
    elapsed_seconds: float = 0.0


@dataclass
class FakeAnalysis:
    asking_questions: bool = False
    has_permission_denials: bool = False
    work_summary: str = ""
    is_error: bool = False


class TestThreeStateCircuitBreaker(unittest.TestCase):
    """Tests for the 3-state (CLOSED / HALF_OPEN / OPEN) circuit breaker."""

    def _no_progress(self, summary: str = "") -> tuple[FakeProgress, FakeAnalysis]:
        return FakeProgress(), FakeAnalysis(work_summary=summary)

    def _productive(self) -> tuple[FakeProgress, FakeAnalysis]:
        return FakeProgress(is_productive=True), FakeAnalysis(work_summary="did stuff")

    def test_three_state_closed_to_half_open(self) -> None:
        cb = CircuitBreaker()
        self.assertEqual(cb.current_phase, BreakerPhase.CLOSED)

        # Record enough no-progress iterations to reach HALF_OPEN
        for i in range(HALF_OPEN_THRESHOLD):
            cb.record_iteration(*self._no_progress(f"stuck {i}"))

        self.assertEqual(cb.current_phase, BreakerPhase.HALF_OPEN)
        self.assertFalse(cb.is_open())  # HALF_OPEN is not a halt state

    def test_three_state_half_open_to_open(self) -> None:
        cb = CircuitBreaker()

        # Get to HALF_OPEN
        for i in range(HALF_OPEN_THRESHOLD):
            cb.record_iteration(*self._no_progress(f"stuck {i}"))
        self.assertEqual(cb.current_phase, BreakerPhase.HALF_OPEN)

        # Continue no-progress until OPEN
        remaining = NO_PROGRESS_THRESHOLD - HALF_OPEN_THRESHOLD
        for i in range(remaining):
            cb.record_iteration(*self._no_progress(f"still stuck {i}"))

        self.assertEqual(cb.current_phase, BreakerPhase.OPEN)
        self.assertTrue(cb.is_open())

    def test_three_state_half_open_to_closed(self) -> None:
        cb = CircuitBreaker()

        # Get to HALF_OPEN
        for i in range(HALF_OPEN_THRESHOLD):
            cb.record_iteration(*self._no_progress(f"stuck {i}"))
        self.assertEqual(cb.current_phase, BreakerPhase.HALF_OPEN)

        # Progress resumes -> back to CLOSED
        cb.record_iteration(*self._productive())
        self.assertEqual(cb.current_phase, BreakerPhase.CLOSED)
        self.assertFalse(cb.is_open())

    def test_cooldown_recovery(self) -> None:
        cb = CircuitBreaker()

        # Force into OPEN state with opened_at in the past
        cb.state.phase = BreakerPhase.OPEN.value
        cb.state.is_open = True
        past = datetime.now(UTC) - timedelta(minutes=COOLDOWN_MINUTES + 1)
        cb.state.opened_at = past.isoformat()

        cb.check_cooldown()
        self.assertEqual(cb.current_phase, BreakerPhase.HALF_OPEN)
        self.assertFalse(cb.is_open())

    def test_question_hold(self) -> None:
        cb = CircuitBreaker()

        # One no-progress iteration
        cb.record_iteration(*self._no_progress("stuck"))
        self.assertEqual(cb.state.consecutive_no_progress, 1)

        # Question iteration holds steady
        question_progress = FakeProgress()
        question_analysis = FakeAnalysis(asking_questions=True, work_summary="question?")
        cb.record_iteration(question_progress, question_analysis)
        self.assertEqual(cb.state.consecutive_no_progress, 1)  # unchanged

    def test_permission_denial_fast_path(self) -> None:
        cb = CircuitBreaker()

        for i in range(PERMISSION_DENIAL_THRESHOLD):
            progress = FakeProgress()
            analysis = FakeAnalysis(has_permission_denials=True, work_summary=f"denied {i}")
            cb.record_iteration(progress, analysis)

        self.assertEqual(cb.current_phase, BreakerPhase.OPEN)
        self.assertTrue(cb.is_open())

    def test_same_error_accumulation(self) -> None:
        cb = CircuitBreaker()

        for _ in range(SAME_ERROR_THRESHOLD):
            progress = FakeProgress()
            analysis = FakeAnalysis(work_summary="same error over and over")
            cb.record_iteration(progress, analysis)

        self.assertEqual(cb.current_phase, BreakerPhase.OPEN)
        self.assertTrue(cb.is_open())

    def test_backward_compat_record_failure_success(self) -> None:
        cb = CircuitBreaker(max_failures=2)

        # Old-style record_failure still works
        cb.record_failure("fail 1")
        self.assertEqual(cb.state.consecutive_failures, 1)
        self.assertFalse(cb.is_open())

        cb.record_failure("fail 2")
        self.assertTrue(cb.is_open())

        # Old-style record_success still resets
        cb.record_success()
        self.assertFalse(cb.is_open())
        self.assertEqual(cb.state.consecutive_failures, 0)

    def test_current_phase_property(self) -> None:
        cb = CircuitBreaker()
        self.assertIsInstance(cb.current_phase, BreakerPhase)
        self.assertEqual(cb.current_phase, BreakerPhase.CLOSED)
        self.assertEqual(cb.current_phase.value, "closed")

        cb.state.phase = BreakerPhase.HALF_OPEN.value
        self.assertEqual(cb.current_phase, BreakerPhase.HALF_OPEN)

        cb.state.phase = BreakerPhase.OPEN.value
        self.assertEqual(cb.current_phase, BreakerPhase.OPEN)


if __name__ == "__main__":
    unittest.main()
