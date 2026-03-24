"""Rolling-window exit signal tracker with multi-condition exit gates.

Tracks completion indicators, done signals, and test-only loops across
iterations. Evaluates exit conditions in priority order to determine
when an autonomous loop should terminate.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.response_analyzer import ResponseAnalysis


@dataclass
class ExitSignals:
    completion_indicators: list[int] = field(default_factory=list)
    done_signals: list[int] = field(default_factory=list)
    test_only_loops: list[int] = field(default_factory=list)


@dataclass
class ExitDecision:
    should_exit: bool
    reason: str


class ExitTracker:
    MAX_COMPLETION_INDICATORS = 5
    MAX_TEST_ONLY_LOOPS = 3
    MAX_DONE_SIGNALS = 2

    def __init__(self, state_path: Path, plan_path: Path | None = None) -> None:
        """state_path: where to persist ExitSignals JSON.
        plan_path: optional path to plan .md file for checkbox counting.
        """
        self._state_path = state_path
        self._plan_path = plan_path
        self._signals = self._load()

    def reset(self) -> None:
        """Unconditional reset. Clear all signal arrays. Delete state file.

        Called at loop start to prevent stale signals (Ralph's pattern).
        """
        self._signals = ExitSignals()
        if self._state_path.exists():
            self._state_path.unlink()

    def update(self, iteration: int, analysis: ResponseAnalysis) -> None:
        """Update signal arrays based on response analysis."""
        if analysis.exit_signal:
            self._signals.completion_indicators.append(iteration)
            self._signals.completion_indicators = self._signals.completion_indicators[
                -self.MAX_COMPLETION_INDICATORS :
            ]

        if analysis.raw_status == "COMPLETE":
            self._signals.done_signals.append(iteration)

        if analysis.work_type == "testing":
            self._signals.test_only_loops.append(iteration)

        self._save()

    def evaluate(
        self,
        analysis: ResponseAnalysis | None = None,
        fitness_results: tuple[bool, list[object]] | None = None,
    ) -> ExitDecision:
        """Evaluate exit conditions in Ralph's priority order."""
        # 0. Permission denied
        if analysis is not None and analysis.has_permission_denials:
            return ExitDecision(should_exit=True, reason="permission_denied")

        # 1. Test saturation
        if len(self._signals.test_only_loops) >= self.MAX_TEST_ONLY_LOOPS:
            return ExitDecision(should_exit=True, reason="test_saturation")

        # 2. Repeated done signals
        if len(self._signals.done_signals) >= self.MAX_DONE_SIGNALS:
            return ExitDecision(should_exit=True, reason="completion_signals")

        # 3. Safety backstop
        if len(self._signals.completion_indicators) >= self.MAX_COMPLETION_INDICATORS:
            return ExitDecision(should_exit=True, reason="safety_circuit_breaker")

        # 4. Dual-condition
        if (
            len(self._signals.completion_indicators) >= 2
            and analysis is not None
            and analysis.exit_signal
        ):
            return ExitDecision(should_exit=True, reason="completion_signals")

        # 5. Plan complete
        if self._check_plan_complete():
            return ExitDecision(should_exit=True, reason="plan_complete")

        # 6. Fitness gate (machine-checkable exit from plan)
        if fitness_results is not None and fitness_results[0]:
            return ExitDecision(should_exit=True, reason="fitness_gate_passed")

        return ExitDecision(should_exit=False, reason="")

    def _check_plan_complete(self) -> bool:
        """Count '- [ ]' vs '- [x]' in plan file.

        Returns True only if total > 0 and all items are checked.
        """
        if self._plan_path is None or not self._plan_path.exists():
            return False

        text = self._plan_path.read_text()
        unchecked = len(re.findall(r"- \[ \]", text))
        checked = len(re.findall(r"- \[x\]", text, re.IGNORECASE))
        total = unchecked + checked

        return total > 0 and unchecked == 0

    def _load(self) -> ExitSignals:
        """Load from JSON file or return empty ExitSignals."""
        if not self._state_path.exists():
            return ExitSignals()

        try:
            data = json.loads(self._state_path.read_text())
            return ExitSignals(
                completion_indicators=data.get("completion_indicators", []),
                done_signals=data.get("done_signals", []),
                test_only_loops=data.get("test_only_loops", []),
            )
        except (json.JSONDecodeError, KeyError):
            return ExitSignals()

    def _save(self) -> None:
        """Write current signals to JSON file."""
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(asdict(self._signals), indent=2))
