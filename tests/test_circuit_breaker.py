"""Tests for the circuit breaker."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.circuit_breaker import CircuitBreaker


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


if __name__ == "__main__":
    unittest.main()
