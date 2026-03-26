"""Experiment state management and TSV log persistence."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from src.convergence import ExperimentEntry


@dataclass
class ExperimentConfig:
    """Configuration for a single experiment session."""

    target_files: list[str]
    metric_command: str
    time_budget_seconds: float  # per-experiment wall clock
    total_budget_seconds: float  # entire session (0 = unlimited)
    direction: str = "minimize"  # "minimize" | "maximize"
    max_experiments: int = 50
    cwd: str = ""


@dataclass
class ExperimentState:
    """Persisted state for an experiment session."""

    id: str
    config: ExperimentConfig
    status: str = "in_progress"  # "in_progress" | "completed" | "converged" | "aborted"
    created: str = ""
    entries: list[ExperimentEntry] = field(default_factory=list)
    baseline_value: float | None = None
    best_value: float | None = None
    best_experiment: int | None = None
    safety_branch: str = ""


class ExperimentLog:
    """Manages experiment state and TSV log persistence."""

    def __init__(self, experiments_dir: Path) -> None:
        self._dir = experiments_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._state_path = self._dir / "state.json"
        self._log_path = self._dir / "log.tsv"
        self._state: ExperimentState | None = None

    def start(self, config: ExperimentConfig) -> ExperimentState:
        """Initialize a new experiment session."""
        now = datetime.now(UTC)
        self._state = ExperimentState(
            id=now.strftime("%Y%m%dT%H%M%SZ"),
            config=config,
            created=now.isoformat(),
        )
        self._write_tsv_header()
        self._save()
        return self._state

    def record_baseline(self, value: float) -> None:
        """Record the baseline metric measurement."""
        assert self._state is not None
        self._state.baseline_value = value
        self._state.best_value = value
        entry = ExperimentEntry(
            experiment_num=0,
            status="baseline",
            metric_value=value,
            files_touched=[],
            duration_seconds=0.0,
            description="Initial measurement",
            timestamp=datetime.now(UTC).isoformat(),
        )
        self._state.entries.append(entry)
        self._append_tsv(entry)
        self._save()

    def record_entry(self, entry: ExperimentEntry) -> None:
        """Record an experiment result and update best tracking."""
        assert self._state is not None
        self._state.entries.append(entry)
        if (
            entry.status == "keep"
            and entry.metric_value is not None
            and (self._state.best_value is None or self._is_better(entry.metric_value))
        ):
            self._state.best_value = entry.metric_value
            self._state.best_experiment = entry.experiment_num
        self._append_tsv(entry)
        self._save()

    def finish(self, reason: str) -> None:
        """Mark the experiment session as finished."""
        assert self._state is not None
        self._state.status = reason  # "completed" | "converged" | "aborted"
        self._save()

    def load(self) -> ExperimentState | None:
        """Load experiment state from disk."""
        if not self._state_path.exists():
            return None
        try:
            data = json.loads(self._state_path.read_text())
            config = ExperimentConfig(**data.pop("config"))
            entries = [ExperimentEntry(**e) for e in data.pop("entries", [])]
            self._state = ExperimentState(config=config, entries=entries, **data)
            return self._state
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def set_safety_branch(self, branch_name: str) -> None:
        """Set the safety branch name for this experiment session."""
        assert self._state is not None
        self._state.safety_branch = branch_name
        self._save()

    def get_entries(self) -> list[ExperimentEntry]:
        """Return all recorded entries."""
        if self._state:
            return self._state.entries
        return []

    def _is_better(self, value: float) -> bool:
        """Check if value is better than current best based on direction."""
        assert self._state is not None
        if self._state.best_value is None:
            return True
        if self._state.config.direction == "minimize":
            return value < self._state.best_value
        return value > self._state.best_value

    def _write_tsv_header(self) -> None:
        with open(self._log_path, "w", newline="") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow(
                [
                    "experiment_num",
                    "status",
                    "metric_value",
                    "duration_seconds",
                    "files_touched",
                    "description",
                    "timestamp",
                ]
            )

    def _append_tsv(self, entry: ExperimentEntry) -> None:
        with open(self._log_path, "a", newline="") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow(
                [
                    entry.experiment_num,
                    entry.status,
                    entry.metric_value if entry.metric_value is not None else "",
                    f"{entry.duration_seconds:.1f}",
                    ",".join(entry.files_touched),
                    entry.description,
                    entry.timestamp,
                ]
            )

    def _save(self) -> None:
        """Persist state as JSON."""
        assert self._state is not None
        data = {
            "id": self._state.id,
            "config": asdict(self._state.config),
            "status": self._state.status,
            "created": self._state.created,
            "entries": [asdict(e) for e in self._state.entries],
            "baseline_value": self._state.baseline_value,
            "best_value": self._state.best_value,
            "best_experiment": self._state.best_experiment,
            "safety_branch": self._state.safety_branch,
        }
        self._state_path.write_text(json.dumps(data, indent=2))
