"""Tests for loop module."""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.circuit_breaker import BreakerPhase
from src.exit_tracker import ExitDecision
from src.loop import LoopConfig, LoopRunner
from src.response_analyzer import ResponseAnalysis


def _make_config(tmp_dir: str, **overrides) -> LoopConfig:
    """Return a LoopConfig with sensible defaults pointing at a temp directory."""
    defaults = {
        "mode": "run",
        "worktree_cwd": tmp_dir,
        "main_repo": tmp_dir,
        "plan_path": None,
        "max_iterations": 50,
        "timeout_seconds": 10,
    }
    defaults.update(overrides)
    return LoopConfig(**defaults)


def _mock_subprocess_result(
    output: str = "",
    returncode: int = 0,
    stderr: str = "",
) -> subprocess.CompletedProcess:
    """Return a CompletedProcess mimicking claude CLI JSON output."""
    return subprocess.CompletedProcess(
        args=["claude"],
        returncode=returncode,
        stdout=output,
        stderr=stderr,
    )


def _default_claude_output() -> str:
    return json.dumps({"result": "Done.", "sessionId": "test-123"})


class TestLoopStopsSentinel(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @patch("src.loop.time.sleep")
    @patch("src.loop.subprocess.run")
    @patch("src.loop.capture_snapshot")
    @patch("src.loop.compare")
    def test_loop_stops_on_stop_sentinel(
        self,
        mock_compare,
        mock_snap,
        mock_run,
        mock_sleep,
    ) -> None:
        config = _make_config(self.tmp_dir, max_iterations=10)
        runner = LoopRunner(config)
        # Create the stop file
        runner.stop_path.parent.mkdir(parents=True, exist_ok=True)
        runner.stop_path.write_text("stop")

        result = runner.run()
        # Should have stopped at iteration 1 without executing any iteration
        self.assertEqual(result.iterations_completed, 1)
        mock_run.assert_not_called()


class TestLoopMaxIterations(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @patch("src.loop.time.sleep")
    @patch("src.loop.compare")
    @patch("src.loop.capture_snapshot")
    @patch("src.loop.subprocess.run")
    def test_loop_stops_at_max_iterations(
        self,
        mock_run,
        mock_snap,
        mock_compare,
        mock_sleep,
    ) -> None:
        mock_run.return_value = _mock_subprocess_result(_default_claude_output())
        mock_snap.return_value = MagicMock(timestamp=time.time())
        mock_compare.return_value = MagicMock(is_productive=True)

        config = _make_config(self.tmp_dir, max_iterations=2)
        runner = LoopRunner(config)
        result = runner.run()
        self.assertEqual(result.iterations_completed, 2)


class TestLoopCircuitBreaker(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @patch("src.loop.time.sleep")
    @patch("src.loop.subprocess.run")
    def test_loop_stops_when_circuit_breaker_opens(self, mock_run, mock_sleep) -> None:
        config = _make_config(self.tmp_dir, max_iterations=10)
        runner = LoopRunner(config)
        # Force circuit breaker to OPEN
        runner.circuit_breaker.state.phase = BreakerPhase.OPEN.value
        runner.circuit_breaker.state.is_open = True

        result = runner.run()
        self.assertEqual(result.iterations_completed, 1)
        self.assertEqual(result.final_phase, "open")
        mock_run.assert_not_called()


class TestLoopExitTracker(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @patch("src.loop.time.sleep")
    @patch("src.loop.subprocess.run")
    def test_loop_stops_on_exit_tracker(self, mock_run, mock_sleep) -> None:
        config = _make_config(self.tmp_dir, max_iterations=10)
        runner = LoopRunner(config)
        # Mock exit tracker to return should_exit=True
        runner.exit_tracker.evaluate = MagicMock(
            return_value=ExitDecision(should_exit=True, reason="test_saturation")
        )

        result = runner.run()
        self.assertEqual(result.iterations_completed, 1)
        mock_run.assert_not_called()


class TestBuildContext(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_build_context_includes_loop_number(self) -> None:
        config = _make_config(self.tmp_dir)
        runner = LoopRunner(config)
        context = runner._build_context(1)
        self.assertIn("Loop #1", context)

    def test_build_context_includes_remaining_tasks(self) -> None:
        plan_path = Path(self.tmp_dir) / "plan.md"
        plan_path.write_text("- [ ] Task 1\n- [ ] Task 2\n- [x] Task 3\n")
        config = _make_config(self.tmp_dir, plan_path=plan_path)
        runner = LoopRunner(config)
        context = runner._build_context(1)
        self.assertIn("Remaining tasks: 2", context)

    def test_build_context_question_corrective(self) -> None:
        config = _make_config(self.tmp_dir)
        runner = LoopRunner(config)
        runner._last_analysis = ResponseAnalysis(asking_questions=True)
        context = runner._build_context(1)
        self.assertIn("IMPORTANT: You asked questions", context)
        self.assertIn("Do NOT ask questions", context)

    def test_build_context_caps_at_500(self) -> None:
        plan_path = Path(self.tmp_dir) / "plan.md"
        # Create a plan with lots of checkboxes to make context long
        plan_path.write_text("- [ ] Task\n" * 100)
        config = _make_config(self.tmp_dir, plan_path=plan_path)
        runner = LoopRunner(config)
        runner._last_analysis = ResponseAnalysis(work_summary="A" * 300)
        context = runner._build_context(1)
        self.assertLessEqual(len(context), 500)

    def test_build_context_half_open_preserves_assessment_prompt(self) -> None:
        config = _make_config(self.tmp_dir)
        runner = LoopRunner(config)
        runner.circuit_breaker.state.phase = BreakerPhase.HALF_OPEN.value
        context = runner._build_context(5)
        self.assertIn("---SELF_ASSESSMENT---", context)
        self.assertIn("---END_SELF_ASSESSMENT---", context)
        self.assertIn("CIRCUIT BREAKER HALF_OPEN", context)

    def test_build_context_half_open_includes_pivot_when_low_viability(self) -> None:
        from src.interview import DimensionScore
        from src.self_assessment import AssessmentResult

        config = _make_config(self.tmp_dir)
        runner = LoopRunner(config)
        runner.circuit_breaker.state.phase = BreakerPhase.HALF_OPEN.value
        runner.last_assessment = AssessmentResult(
            scores=[DimensionScore("approach_viability", 0.3, 0.30)],
            overall_clarity=0.3,
        )
        context = runner._build_context(5)
        self.assertIn("PIVOT", context)


class TestBuildPrompt(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_build_prompt_run_mode(self) -> None:
        plan_path = Path(self.tmp_dir) / "plan.md"
        config = _make_config(self.tmp_dir, mode="run", plan_path=plan_path)
        runner = LoopRunner(config)
        prompt = runner._build_prompt()
        self.assertIn("/run workflow", prompt)
        self.assertIn("AUTODIDACT_STATUS", prompt)

    def test_build_prompt_campaign_mode(self) -> None:
        config = _make_config(self.tmp_dir, mode="campaign")
        runner = LoopRunner(config)
        prompt = runner._build_prompt()
        self.assertEqual(prompt, "/campaign continue")

    def test_build_prompt_fleet_mode(self) -> None:
        config = _make_config(self.tmp_dir, mode="fleet")
        runner = LoopRunner(config)
        prompt = runner._build_prompt()
        self.assertIn("/fleet workflow", prompt)
        self.assertIn("AUTODIDACT_STATUS", prompt)


class TestSessionValid(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_session_valid_within_expiry(self) -> None:
        config = _make_config(self.tmp_dir)
        runner = LoopRunner(config)
        runner.session_created = time.time() - 3600  # 1 hour ago
        self.assertTrue(runner._session_valid())

    def test_session_valid_expired(self) -> None:
        config = _make_config(self.tmp_dir)
        runner = LoopRunner(config)
        runner.session_created = time.time() - (25 * 3600)  # 25 hours ago
        self.assertFalse(runner._session_valid())


class TestInvokeClaude(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @patch("src.loop.subprocess.run")
    def test_invoke_claude_builds_correct_command(self, mock_run) -> None:
        mock_run.return_value = _mock_subprocess_result(_default_claude_output())
        plan_path = Path(self.tmp_dir) / "plan.md"
        config = _make_config(self.tmp_dir, mode="run", plan_path=plan_path)
        runner = LoopRunner(config)

        runner._invoke_claude("Loop #1.")

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], "claude")
        self.assertIn("--output-format", cmd)
        self.assertIn("json", cmd)
        self.assertIn("--append-system-prompt", cmd)
        self.assertIn("-p", cmd)

    @patch("src.loop.subprocess.run")
    def test_invoke_claude_includes_resume(self, mock_run) -> None:
        mock_run.return_value = _mock_subprocess_result(_default_claude_output())
        config = _make_config(self.tmp_dir, mode="campaign")
        runner = LoopRunner(config)
        runner.session_id = "sess-abc"
        runner.session_created = time.time()

        runner._invoke_claude("Loop #1.")

        cmd = mock_run.call_args[0][0]
        self.assertIn("--resume", cmd)
        self.assertIn("sess-abc", cmd)

    @patch("src.loop.subprocess.run")
    def test_invoke_claude_timeout_returns_124(self, mock_run) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=10)
        config = _make_config(self.tmp_dir, mode="campaign")
        runner = LoopRunner(config)

        result = runner._invoke_claude("Loop #1.")
        self.assertEqual(result.exit_code, 124)
        self.assertEqual(result.stderr, "timeout")


class TestPidLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @patch("src.loop.time.sleep")
    @patch("src.loop.compare")
    @patch("src.loop.capture_snapshot")
    @patch("src.loop.subprocess.run")
    def test_pid_file_lifecycle(self, mock_run, mock_snap, mock_compare, mock_sleep) -> None:
        mock_run.return_value = _mock_subprocess_result(_default_claude_output())
        mock_snap.return_value = MagicMock(timestamp=time.time())
        mock_compare.return_value = MagicMock(is_productive=True)

        config = _make_config(self.tmp_dir, max_iterations=1)
        runner = LoopRunner(config)
        pid_path = runner.pid_path

        # Verify PID file doesn't exist before run
        self.assertFalse(pid_path.exists())

        runner.run()

        # After run completes, PID file should be cleaned up
        self.assertFalse(pid_path.exists())


if __name__ == "__main__":
    unittest.main()
