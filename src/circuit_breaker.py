"""Circuit breaker: consecutive failure detection with configurable threshold.

Prevents infinite retry loops by tracking consecutive failures and
halting operations when the threshold is exceeded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class CircuitState:
    consecutive_failures: int = 0
    max_failures: int = 3
    is_open: bool = False
    last_failure: str = ""
    last_failure_context: str = ""

    def to_dict(self) -> dict:
        return {
            "consecutive_failures": self.consecutive_failures,
            "max_failures": self.max_failures,
            "is_open": self.is_open,
            "last_failure": self.last_failure,
            "last_failure_context": self.last_failure_context,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CircuitState:
        return cls(
            consecutive_failures=data.get("consecutive_failures", 0),
            max_failures=data.get("max_failures", 3),
            is_open=data.get("is_open", False),
            last_failure=data.get("last_failure", ""),
            last_failure_context=data.get("last_failure_context", ""),
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
        self.state.last_failure = datetime.now(timezone.utc).isoformat()
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

    def is_open(self) -> bool:
        """True if too many consecutive failures."""
        return self.state.is_open

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        self.state = CircuitState(max_failures=self.state.max_failures)
        self._save()

    def status(self) -> dict:
        return {
            "is_open": self.state.is_open,
            "consecutive_failures": self.state.consecutive_failures,
            "max_failures": self.state.max_failures,
            "last_failure": self.state.last_failure,
            "last_context": self.state.last_failure_context,
        }
