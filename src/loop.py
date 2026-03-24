"""Autonomous loop orchestrator for Claude Code.

Manages the iterate-until-done loop: invoke Claude CLI, analyze response,
track progress via circuit breaker and exit tracker, and terminate when
appropriate conditions are met.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from src.circuit_breaker import BreakerPhase, CircuitBreaker
from src.db import LearningDB
from src.documents import get_latest_plan
from src.exit_tracker import ExitTracker
from src.git_utils import resolve_main_repo
from src.progress import ProgressReport, capture_snapshot, compare, is_productive_timeout
from src.response_analyzer import ResponseAnalysis, analyze


@dataclass
class LoopConfig:
    mode: str  # "run" | "campaign" | "fleet"
    worktree_cwd: str  # actual working directory (may be a worktree)
    main_repo: str  # resolved main repo root
    plan_path: Path | None = None  # path to plan document
    campaign_slug: str | None = None  # active campaign slug
    max_iterations: int = 50
    session_expiry_hours: int = 24
    allowed_tools: list[str] | None = None
    rate_limit_wait_minutes: int = 60
    timeout_seconds: int = 600  # 10 min per iteration


@dataclass
class IterationResult:
    should_break: bool = False
    reason: str = ""


@dataclass
class LoopResult:
    iterations_completed: int = 0
    exit_reason: str = ""
    final_phase: str = "closed"

    def to_dict(self) -> dict[str, object]:
        return {
            "iterations_completed": self.iterations_completed,
            "exit_reason": self.exit_reason,
            "final_phase": self.final_phase,
        }


@dataclass
class CLIResult:
    exit_code: int
    output: str
    stderr: str


class LoopRunner:
    def __init__(self, config: LoopConfig) -> None:
        planning_dir = Path(config.worktree_cwd) / ".planning"
        self.config = config
        self.exit_tracker = ExitTracker(
            state_path=planning_dir / "loop_signals.json",
            plan_path=config.plan_path,
        )
        self.circuit_breaker = CircuitBreaker(
            state_path=planning_dir / "loop_cb_state.json",
        )
        self.session_id: str | None = None
        self.session_created: float | None = None
        self.pid_path = planning_dir / "loop.pid"
        self.stop_path = planning_dir / "loop.stop"
        self._last_analysis: ResponseAnalysis | None = None
        self._iteration_count = 0

    def run(self) -> LoopResult:
        """Main loop. Write PID, reset exit tracker, iterate until done."""
        self._write_pid()
        self.exit_tracker.reset()
        try:
            for iteration in range(1, self.config.max_iterations + 1):
                self._iteration_count = iteration
                if self._should_stop():
                    break
                result = self._execute_iteration(iteration)
                if result.should_break:
                    break
                time.sleep(5)  # Brief pause between iterations
        finally:
            self._record_run_summary()
            self._cleanup()
        return self._build_result()

    def _should_stop(self) -> bool:
        """Check stop sentinel, circuit breaker, exit tracker."""
        if self.stop_path.exists():
            return True
        self.circuit_breaker.check_cooldown()
        if self.circuit_breaker.current_phase == BreakerPhase.OPEN:
            return True
        decision = self.exit_tracker.evaluate(self._last_analysis)
        return decision.should_exit

    def _execute_iteration(self, iteration: int) -> IterationResult:
        """Single iteration: snapshot -> invoke -> analyze -> update."""
        snapshot = capture_snapshot(self.config.worktree_cwd)
        context = self._build_context(iteration)
        cli_result = self._invoke_claude(context)
        analysis = analyze(cli_result.output, cli_result.exit_code)
        self._last_analysis = analysis

        # Update session
        if analysis.session_id:
            self.session_id = analysis.session_id
            if self.session_created is None:
                self.session_created = time.time()

        # Rate limit -> wait and continue
        if analysis.is_rate_limited:
            self._wait_for_rate_limit()
            return IterationResult()

        # Productive timeout check
        if cli_result.exit_code == 124 and not is_productive_timeout(
            self.config.worktree_cwd,
            snapshot,
        ):
            prog = ProgressReport(0, 0, False, False, time.time() - snapshot.timestamp)
            self.circuit_breaker.record_iteration(prog, analysis)
            return IterationResult()

        # Normal progress detection
        progress_report = compare(self.config.worktree_cwd, snapshot)
        self.circuit_breaker.record_iteration(progress_report, analysis)
        self.exit_tracker.update(iteration, analysis)

        return IterationResult()

    def _build_context(self, iteration: int) -> str:
        """Per-iteration context, capped at 500 chars."""
        parts = [f"Loop #{iteration}."]

        if self.config.plan_path and self.config.plan_path.exists():
            text = self.config.plan_path.read_text()
            remaining = text.count("- [ ]")
            parts.append(f"Remaining tasks: {remaining}.")

        phase = self.circuit_breaker.current_phase
        if phase != BreakerPhase.CLOSED:
            parts.append(f"Circuit breaker: {phase.value}.")

        if self._last_analysis and self._last_analysis.work_summary:
            summary = self._last_analysis.work_summary[:200]
            parts.append(f"Previous: {summary}")

        if self._last_analysis and self._last_analysis.asking_questions:
            parts.append(
                "IMPORTANT: You asked questions in the previous loop. "
                "This is an autonomous loop with no human to answer. "
                "Do NOT ask questions. Choose the safest default and proceed."
            )

        return " ".join(parts)[:500]

    def _build_prompt(self) -> str:
        """Build the -p prompt based on mode."""
        if self.config.mode == "run":
            plan = self.config.plan_path
            return (
                f"Continue executing the plan at {plan} using the /run workflow. "
                "Emit an ---AUTODIDACT_STATUS--- block at the end of your response."
            )
        elif self.config.mode == "campaign":
            return "/campaign continue"
        elif self.config.mode == "fleet":
            return (
                "Continue fleet execution using the /fleet workflow. "
                "Emit an ---AUTODIDACT_STATUS--- block at the end of your response."
            )
        msg = f"Unknown mode: {self.config.mode}"
        raise ValueError(msg)

    def _invoke_claude(self, context: str) -> CLIResult:
        """Build and execute the claude CLI command."""
        cmd = ["claude", "--output-format", "json"]

        if self.config.allowed_tools:
            cmd.append("--allowedTools")
            cmd.extend(self.config.allowed_tools)

        if self.session_id and self._session_valid():
            cmd.extend(["--resume", self.session_id])

        if context:
            cmd.extend(["--append-system-prompt", context])

        cmd.extend(["-p", self._build_prompt()])

        try:
            result = subprocess.run(
                cmd,
                cwd=self.config.worktree_cwd,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
            )
            return CLIResult(result.returncode, result.stdout, result.stderr)
        except subprocess.TimeoutExpired:
            return CLIResult(124, "", "timeout")

    def _session_valid(self) -> bool:
        if not self.session_created:
            return False
        elapsed_hours = (time.time() - self.session_created) / 3600
        return elapsed_hours < self.config.session_expiry_hours

    def _wait_for_rate_limit(self) -> None:
        now = time.time()
        seconds_until_next_hour = 3600 - (now % 3600)
        wait = min(seconds_until_next_hour, self.config.rate_limit_wait_minutes * 60)
        time.sleep(wait)

    def _write_pid(self) -> None:
        self.pid_path.parent.mkdir(parents=True, exist_ok=True)
        self.pid_path.write_text(str(os.getpid()))

    def _cleanup(self) -> None:
        self.pid_path.unlink(missing_ok=True)
        self.stop_path.unlink(missing_ok=True)

    def _record_run_summary(self) -> None:
        """Persist a structured summary of this loop run to the learning DB."""
        summary = {
            "iterations": self._iteration_count,
            "exit_reason": self.exit_tracker.evaluate(self._last_analysis).reason
            or "max_iterations",
            "final_phase": self.circuit_breaker.current_phase.value,
            "mode": self.config.mode,
        }
        try:
            db = LearningDB()
            db.record_run_summary(
                summary,
                session_id=self.session_id or "",
                project_path=self.config.main_repo,
            )
            db.close()
        except Exception:
            pass  # graceful degradation, matching hook pattern

    def _build_result(self) -> LoopResult:
        decision = self.exit_tracker.evaluate(self._last_analysis)
        return LoopResult(
            iterations_completed=self._iteration_count,
            exit_reason=decision.reason if decision.should_exit else "max_iterations",
            final_phase=self.circuit_breaker.current_phase.value,
        )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Autodidact autonomous loop")
    parser.add_argument("mode", choices=["run", "campaign", "fleet"])
    parser.add_argument("--max", type=int, default=50, dest="max_iterations")
    parser.add_argument("--cwd", default=None)
    parser.add_argument("--plan", default=None)
    parser.add_argument("--campaign", default=None)
    args = parser.parse_args()

    cwd = args.cwd or os.getcwd()
    main_repo = resolve_main_repo(cwd)

    plan_path = None
    if args.plan:
        plan_path = Path(args.plan)
    elif args.mode in ("run", "fleet"):
        plan_path = get_latest_plan(cwd)
        if not plan_path:
            print("No plan found in .planning/plans/. Run /plan first.", file=sys.stderr)
            sys.exit(1)

    config = LoopConfig(
        mode=args.mode,
        worktree_cwd=cwd,
        main_repo=main_repo,
        plan_path=plan_path,
        campaign_slug=args.campaign,
        max_iterations=args.max_iterations,
    )
    runner = LoopRunner(config)
    result = runner.run()
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
