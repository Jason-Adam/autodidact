"""Circuit breaker: consecutive failure detection with configurable threshold.

Prevents infinite retry loops by tracking consecutive failures and
halting operations when the threshold is exceeded.

Supports 3-state transitions: CLOSED -> HALF_OPEN -> OPEN with cooldown recovery.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.progress import ProgressReport
    from src.response_analyzer import ResponseAnalysis


class BreakerPhase(Enum):
    CLOSED = "closed"
    HALF_OPEN = "half_open"
    OPEN = "open"


# 3-state transition thresholds
NO_PROGRESS_THRESHOLD = 3
SAME_ERROR_THRESHOLD = 5
PERMISSION_DENIAL_THRESHOLD = 2
HALF_OPEN_THRESHOLD = 2
COOLDOWN_MINUTES = 30


@dataclass
class CircuitState:
    consecutive_failures: int = 0
    max_failures: int = 3
    is_open: bool = False
    last_failure: str = ""
    last_failure_context: str = ""
    # 3-state fields
    phase: str = "closed"
    consecutive_no_progress: int = 0
    consecutive_same_error: int = 0
    consecutive_permission_denials: int = 0
    last_error_signature: str = ""
    opened_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "consecutive_failures": self.consecutive_failures,
            "max_failures": self.max_failures,
            "is_open": self.is_open,
            "last_failure": self.last_failure,
            "last_failure_context": self.last_failure_context,
            "phase": self.phase,
            "consecutive_no_progress": self.consecutive_no_progress,
            "consecutive_same_error": self.consecutive_same_error,
            "consecutive_permission_denials": self.consecutive_permission_denials,
            "last_error_signature": self.last_error_signature,
            "opened_at": self.opened_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CircuitState:
        return cls(
            consecutive_failures=data.get("consecutive_failures", 0),
            max_failures=data.get("max_failures", 3),
            is_open=data.get("is_open", False),
            last_failure=data.get("last_failure", ""),
            last_failure_context=data.get("last_failure_context", ""),
            phase=data.get("phase", "closed"),
            consecutive_no_progress=data.get("consecutive_no_progress", 0),
            consecutive_same_error=data.get("consecutive_same_error", 0),
            consecutive_permission_denials=data.get("consecutive_permission_denials", 0),
            last_error_signature=data.get("last_error_signature", ""),
            opened_at=data.get("opened_at", ""),
        )


class CircuitBreaker:
    """Tracks consecutive failures and trips when threshold is exceeded."""

    def __init__(self, state_path: str | Path | None = None, max_failures: int = 3) -> None:
        self.state_path = Path(state_path) if state_path else None
        self.state = self._load() or CircuitState(max_failures=max_failures)

    def _load(self) -> CircuitState | None:
        if self.state_path and self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text())
                return CircuitState.from_dict(data)
            except (json.JSONDecodeError, KeyError):
                return None
        return None

    def _save(self) -> None:
        if self.state_path:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(self.state.to_dict(), indent=2))

    def record_failure(self, context: str = "") -> bool:
        """Record a failure. Returns True if circuit is now open (should stop)."""
        self.state.consecutive_failures += 1
        self.state.last_failure = datetime.now(UTC).isoformat()
        self.state.last_failure_context = context
        if self.state.consecutive_failures >= self.state.max_failures:
            self.state.is_open = True
        self._save()
        return self.state.is_open

    def record_success(self) -> None:
        """Reset the failure counter on success."""
        self.state.consecutive_failures = 0
        self.state.is_open = False
        self.state.last_failure_context = ""
        self._save()

    def record_iteration(self, progress: ProgressReport, analysis: ResponseAnalysis) -> None:
        """Rich iteration recording for the 3-state loop.

        Tracks no-progress streaks, repeated errors, and permission denials,
        then applies transition logic across CLOSED / HALF_OPEN / OPEN phases.
        """
        # --- Track same-error signature ---
        error_sig = hashlib.md5(analysis.work_summary.encode()).hexdigest()[:12]  # noqa: S324
        if error_sig == self.state.last_error_signature and analysis.work_summary:
            self.state.consecutive_same_error += 1
        else:
            self.state.consecutive_same_error = 1 if analysis.work_summary else 0
        self.state.last_error_signature = error_sig

        # --- Permission denials ---
        if analysis.has_permission_denials:
            self.state.consecutive_permission_denials += 1
        else:
            self.state.consecutive_permission_denials = 0

        # --- Progress tracking ---
        if progress.is_productive:
            self.state.consecutive_no_progress = 0
            if self.state.phase == BreakerPhase.HALF_OPEN.value:
                self.state.phase = BreakerPhase.CLOSED.value
        elif analysis.asking_questions:
            pass  # hold steady — don't increment, don't reset
        else:
            self.state.consecutive_no_progress += 1

        # --- Transition logic ---
        self._apply_transitions()

        # Keep is_open in sync with phase
        self.state.is_open = self.state.phase == BreakerPhase.OPEN.value
        if self.state.is_open and not self.state.opened_at:
            self.state.opened_at = datetime.now(UTC).isoformat()

        self._save()

    def _apply_transitions(self) -> None:
        """Apply phase transition rules."""
        phase = self.state.phase

        if phase == BreakerPhase.CLOSED.value:
            should_open = (
                self.state.consecutive_no_progress >= NO_PROGRESS_THRESHOLD
                or self.state.consecutive_same_error >= SAME_ERROR_THRESHOLD
                or self.state.consecutive_permission_denials >= PERMISSION_DENIAL_THRESHOLD
            )
            if should_open:
                self._open()
            elif self.state.consecutive_no_progress >= HALF_OPEN_THRESHOLD:
                self.state.phase = BreakerPhase.HALF_OPEN.value

        elif phase == BreakerPhase.HALF_OPEN.value:
            # Progress recovery is handled above in record_iteration
            should_open = (
                self.state.consecutive_no_progress >= NO_PROGRESS_THRESHOLD
                or self.state.consecutive_same_error >= SAME_ERROR_THRESHOLD
                or self.state.consecutive_permission_denials >= PERMISSION_DENIAL_THRESHOLD
            )
            if should_open:
                self._open()

        # OPEN stays OPEN (cooldown checked separately)

    def _open(self) -> None:
        """Transition to OPEN phase."""
        self.state.phase = BreakerPhase.OPEN.value
        self.state.opened_at = datetime.now(UTC).isoformat()

    def check_cooldown(self) -> None:
        """If OPEN and cooldown elapsed, transition to HALF_OPEN."""
        if self.state.phase != BreakerPhase.OPEN.value:
            return
        if not self.state.opened_at:
            return
        opened = datetime.fromisoformat(self.state.opened_at)
        if datetime.now(UTC) - opened >= timedelta(minutes=COOLDOWN_MINUTES):
            self.state.phase = BreakerPhase.HALF_OPEN.value
            self.state.is_open = False
            self.state.opened_at = ""
            self.state.consecutive_no_progress = 0
            self.state.consecutive_same_error = 0
            self.state.consecutive_permission_denials = 0
            self._save()

    @property
    def current_phase(self) -> BreakerPhase:
        """Returns the 3-state enum value."""
        return BreakerPhase(self.state.phase)

    def is_open(self) -> bool:
        """True if too many consecutive failures."""
        return self.state.is_open

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        self.state = CircuitState(max_failures=self.state.max_failures)
        self._save()

    def status(self) -> dict[str, Any]:
        return {
            "is_open": self.state.is_open,
            "consecutive_failures": self.state.consecutive_failures,
            "max_failures": self.state.max_failures,
            "last_failure": self.state.last_failure,
            "last_context": self.state.last_failure_context,
        }
