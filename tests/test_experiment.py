"""Tests for experiment state management."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.convergence import ExperimentEntry
from src.experiment import ExperimentConfig, ExperimentLog


def _make_entry(
    num: int,
    status: str = "keep",
    metric: float | None = 1.0,
    files: list[str] | None = None,
) -> ExperimentEntry:
    return ExperimentEntry(
        experiment_num=num,
        status=status,
        metric_value=metric,
        files_touched=files or [],
        duration_seconds=10.0,
        description=f"Experiment {num}",
        timestamp="2026-01-01T00:00:00+00:00",
    )


class TestExperimentLog(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        self.exp_dir = self.tmpdir / "experiments" / "test"
        self.log = ExperimentLog(self.exp_dir)
        self.config = ExperimentConfig(
            target_files=["train.py"],
            metric_command="echo 0.85",
            time_budget_seconds=120.0,
            total_budget_seconds=3600.0,
        )

    def test_start_creates_state(self) -> None:
        state = self.log.start(self.config)
        self.assertEqual(state.status, "in_progress")
        self.assertTrue((self.exp_dir / "state.json").exists())
        self.assertTrue((self.exp_dir / "log.tsv").exists())

    def test_record_baseline(self) -> None:
        self.log.start(self.config)
        self.log.record_baseline(0.85)
        state = self.log.load()
        assert state is not None
        self.assertEqual(state.baseline_value, 0.85)
        self.assertEqual(state.best_value, 0.85)
        self.assertEqual(len(state.entries), 1)
        self.assertEqual(state.entries[0].status, "baseline")

    def test_record_entry_updates_best(self) -> None:
        config = ExperimentConfig(
            target_files=["train.py"],
            metric_command="echo 0.85",
            time_budget_seconds=120.0,
            total_budget_seconds=3600.0,
            direction="minimize",
        )
        self.log.start(config)
        self.log.record_baseline(0.85)
        self.log.record_entry(_make_entry(1, "keep", 0.80))
        state = self.log.load()
        assert state is not None
        self.assertEqual(state.best_value, 0.80)
        self.assertEqual(state.best_experiment, 1)

    def test_record_entry_discard_no_best_update(self) -> None:
        self.log.start(self.config)
        self.log.record_baseline(0.85)
        self.log.record_entry(_make_entry(1, "discard", 0.90))
        state = self.log.load()
        assert state is not None
        self.assertEqual(state.best_value, 0.85)
        self.assertIsNone(state.best_experiment)

    def test_finish_sets_status(self) -> None:
        self.log.start(self.config)
        self.log.finish("converged")
        state = self.log.load()
        assert state is not None
        self.assertEqual(state.status, "converged")

    def test_state_persistence_roundtrip(self) -> None:
        self.log.start(self.config)
        self.log.record_baseline(0.85)
        self.log.record_entry(_make_entry(1, "keep", 0.80))
        # Load in a new ExperimentLog instance
        new_log = ExperimentLog(self.exp_dir)
        state = new_log.load()
        assert state is not None
        self.assertEqual(state.id, self.log._state.id)
        self.assertEqual(len(state.entries), 2)

    def test_tsv_content(self) -> None:
        self.log.start(self.config)
        self.log.record_baseline(0.85)
        self.log.record_entry(_make_entry(1, "keep", 0.80, ["train.py"]))
        tsv_content = (self.exp_dir / "log.tsv").read_text()
        lines = tsv_content.strip().split("\n")
        self.assertEqual(len(lines), 3)  # header + baseline + entry
        self.assertIn("experiment_num", lines[0])
        self.assertIn("timestamp", lines[0])
        self.assertIn("train.py", lines[2])
        # Verify timestamp column is populated in data rows
        self.assertIn("2026-01-01", lines[2])

    def test_load_nonexistent(self) -> None:
        empty_log = ExperimentLog(self.tmpdir / "nonexistent")
        self.assertIsNone(empty_log.load())

    def test_multiple_entries_append(self) -> None:
        self.log.start(self.config)
        self.log.record_baseline(0.85)
        for i in range(1, 6):
            self.log.record_entry(_make_entry(i, "keep", 0.85 - i * 0.01))
        state = self.log.load()
        assert state is not None
        self.assertEqual(len(state.entries), 6)  # baseline + 5

    def test_set_safety_branch(self) -> None:
        self.log.start(self.config)
        self.log.set_safety_branch("experiment/safety-20260101T000000Z")
        state = self.log.load()
        assert state is not None
        self.assertEqual(state.safety_branch, "experiment/safety-20260101T000000Z")

    def test_maximize_direction(self) -> None:
        config = ExperimentConfig(
            target_files=["train.py"],
            metric_command="echo 0.85",
            time_budget_seconds=120.0,
            total_budget_seconds=3600.0,
            direction="maximize",
        )
        self.log.start(config)
        self.log.record_baseline(0.85)
        self.log.record_entry(_make_entry(1, "keep", 0.90))
        self.log.record_entry(_make_entry(2, "keep", 0.88))
        state = self.log.load()
        assert state is not None
        self.assertEqual(state.best_value, 0.90)
        self.assertEqual(state.best_experiment, 1)
