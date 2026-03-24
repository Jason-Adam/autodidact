"""Tests for fleet recovery in WorktreeManager."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.worktree import WorktreeManager


def _init_repo(tmpdir: str) -> Path:
    """Create a minimal git repo and return its resolved path."""
    root = Path(os.path.realpath(tmpdir))
    subprocess.run(["git", "init"], cwd=str(root), capture_output=True, text=True, check=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=True,
    )
    return root


class TestRecoverFleetNoActiveWorkers(unittest.TestCase):
    def test_recover_fleet_no_active_workers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _init_repo(tmpdir)
            mgr = WorktreeManager(project_root=root, state_root=root)
            mgr.start_fleet()
            mgr.start_wave()
            worker = mgr.create_worktree("task-a")
            mgr.complete_worker(worker.task_id, brief="done")

            result = mgr.recover_fleet()
            self.assertEqual(result, [])


class TestRecoverFleetCommittedChanges(unittest.TestCase):
    def test_recover_fleet_committed_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _init_repo(tmpdir)
            mgr = WorktreeManager(project_root=root, state_root=root)
            mgr.start_fleet()
            mgr.start_wave()
            worker = mgr.create_worktree("task-commit")

            # Commit a change in the worktree
            wt_path = Path(worker.path)
            (wt_path / "new_file.txt").write_text("hello")
            subprocess.run(
                ["git", "add", "new_file.txt"],
                cwd=str(wt_path),
                capture_output=True,
                text=True,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "add file"],
                cwd=str(wt_path),
                capture_output=True,
                text=True,
                check=True,
            )

            # Simulate interruption: reset status to active
            worker.status = "active"
            mgr._save_state()

            result = mgr.recover_fleet()
            self.assertEqual(result, [])
            self.assertEqual(worker.status, "completed")


class TestRecoverFleetUncommittedChanges(unittest.TestCase):
    def test_recover_fleet_uncommitted_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _init_repo(tmpdir)
            mgr = WorktreeManager(project_root=root, state_root=root)
            mgr.start_fleet()
            mgr.start_wave()
            worker = mgr.create_worktree("task-uncommit")

            # Create uncommitted file in the worktree
            wt_path = Path(worker.path)
            (wt_path / "dirty.txt").write_text("uncommitted")

            # Simulate interruption
            worker.status = "active"
            mgr._save_state()

            result = mgr.recover_fleet()
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].task_id, worker.task_id)
            self.assertEqual(worker.status, "active")


class TestRecoverFleetMissingWorktree(unittest.TestCase):
    def test_recover_fleet_missing_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _init_repo(tmpdir)
            mgr = WorktreeManager(project_root=root, state_root=root)
            mgr.start_fleet()
            mgr.start_wave()
            worker = mgr.create_worktree("task-missing")

            # Remove the worktree directory to simulate missing
            wt_path = Path(worker.path)
            subprocess.run(
                ["git", "worktree", "remove", str(wt_path), "--force"],
                cwd=str(root),
                capture_output=True,
                text=True,
            )

            # Simulate interruption
            worker.status = "active"
            mgr._save_state()

            result = mgr.recover_fleet()
            self.assertEqual(result, [])
            self.assertEqual(worker.status, "failed")


class TestRecoverFleetEmptyWorktree(unittest.TestCase):
    def test_recover_fleet_empty_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _init_repo(tmpdir)
            mgr = WorktreeManager(project_root=root, state_root=root)
            mgr.start_fleet()
            mgr.start_wave()
            worker = mgr.create_worktree("task-empty")

            # Worktree exists but has no changes — simulate interruption
            worker.status = "active"
            mgr._save_state()

            result = mgr.recover_fleet()
            self.assertEqual(result, [])
            self.assertEqual(worker.status, "failed")


class TestCheckWorktreeHealthMissing(unittest.TestCase):
    def test_check_worktree_health_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _init_repo(tmpdir)
            mgr = WorktreeManager(project_root=root, state_root=root)
            mgr.start_fleet()
            mgr.start_wave()
            worker = mgr.create_worktree("task-health-missing")

            # Remove worktree directory
            wt_path = Path(worker.path)
            subprocess.run(
                ["git", "worktree", "remove", str(wt_path), "--force"],
                cwd=str(root),
                capture_output=True,
                text=True,
            )

            health = mgr._check_worktree_health(worker)
            self.assertEqual(health, "missing")


class TestCheckWorktreeHealthEmpty(unittest.TestCase):
    def test_check_worktree_health_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _init_repo(tmpdir)
            mgr = WorktreeManager(project_root=root, state_root=root)
            mgr.start_fleet()
            mgr.start_wave()
            worker = mgr.create_worktree("task-health-empty")

            health = mgr._check_worktree_health(worker)
            self.assertEqual(health, "empty")


if __name__ == "__main__":
    unittest.main()
