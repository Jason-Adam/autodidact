"""Tests for fleet recovery in WorktreeManager."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.worktree import WorkerState, WorktreeManager, extract_file_references


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
            self.assertEqual(worker.status, "cleaned")


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


class TestMergeWorktree(unittest.TestCase):
    def test_merge_success(self) -> None:
        """Worker branch merges cleanly into spawning worktree's branch."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _init_repo(tmpdir)
            mgr = WorktreeManager(project_root=root, state_root=root)
            mgr.start_fleet()
            mgr.start_wave()
            worker = mgr.create_worktree("task-merge")

            # Commit a change in the worker worktree
            wt_path = Path(worker.path)
            (wt_path / "feature.txt").write_text("new feature")
            subprocess.run(
                ["git", "add", "feature.txt"],
                cwd=str(wt_path),
                capture_output=True,
                text=True,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "add feature"],
                cwd=str(wt_path),
                capture_output=True,
                text=True,
                check=True,
            )

            result = mgr.merge_worktree(worker.task_id)
            self.assertTrue(result)
            self.assertEqual(worker.status, "merged")

            # Verify the file exists in merge_root
            self.assertTrue((mgr.merge_root / "feature.txt").exists())

    def test_merge_conflict_aborts_cleanly(self) -> None:
        """Failed merge auto-aborts, leaving tree clean for next merge."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _init_repo(tmpdir)

            # Create initial file on main
            (root / "shared.txt").write_text("original")
            subprocess.run(
                ["git", "add", "shared.txt"],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "add shared"],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=True,
            )

            mgr = WorktreeManager(project_root=root, state_root=root)
            mgr.start_fleet()
            mgr.start_wave()
            worker = mgr.create_worktree("task-conflict")

            # Modify shared.txt in the worker
            wt_path = Path(worker.path)
            (wt_path / "shared.txt").write_text("worker version")
            subprocess.run(
                ["git", "add", "shared.txt"],
                cwd=str(wt_path),
                capture_output=True,
                text=True,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "worker edit"],
                cwd=str(wt_path),
                capture_output=True,
                text=True,
                check=True,
            )

            # Also modify shared.txt on the main branch (creates conflict)
            (root / "shared.txt").write_text("main version")
            subprocess.run(
                ["git", "add", "shared.txt"],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "main edit"],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=True,
            )

            result = mgr.merge_worktree(worker.task_id)
            self.assertFalse(result)
            self.assertEqual(worker.status, "failed")

            # Verify no merge in progress (abort succeeded)
            # Use rev-parse to check MERGE_HEAD (works in both repos and worktrees)
            check = subprocess.run(
                ["git", "rev-parse", "--verify", "MERGE_HEAD"],
                cwd=str(mgr.merge_root),
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(check.returncode, 0, "MERGE_HEAD should not exist after abort")

    def test_merge_uses_merge_root_not_project_root(self) -> None:
        """Merge runs in the spawning worktree, not the main repo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _init_repo(tmpdir)

            # Create a "spawning worktree" branch
            subprocess.run(
                ["git", "checkout", "-b", "feat/test-branch"],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=True,
            )
            subprocess.run(
                ["git", "checkout", "-"],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=True,
            )

            # Create a worktree simulating the spawning worktree
            spawn_path = Path(os.path.realpath(tmpdir)) / "spawn-wt"
            subprocess.run(
                ["git", "worktree", "add", str(spawn_path), "feat/test-branch"],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=True,
            )

            # WorktreeManager initialized from the spawning worktree
            mgr = WorktreeManager(project_root=spawn_path, state_root=spawn_path)

            # project_root should resolve to main repo
            self.assertEqual(mgr.project_root.resolve(), root.resolve())
            # merge_root should resolve to the spawning worktree
            self.assertEqual(mgr.merge_root.resolve(), spawn_path.resolve())

            # Create and populate a fleet worker
            mgr.start_fleet()
            mgr.start_wave()
            worker = mgr.create_worktree("task-spawn-test")

            wt_path = Path(worker.path)
            (wt_path / "spawned.txt").write_text("from worker")
            subprocess.run(
                ["git", "add", "spawned.txt"],
                cwd=str(wt_path),
                capture_output=True,
                text=True,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "worker commit"],
                cwd=str(wt_path),
                capture_output=True,
                text=True,
                check=True,
            )

            result = mgr.merge_worktree(worker.task_id)
            self.assertTrue(result)

            # File should appear in the spawning worktree, not main repo
            self.assertTrue((spawn_path / "spawned.txt").exists())

            # Clean up worktree
            subprocess.run(
                ["git", "worktree", "remove", str(spawn_path), "--force"],
                cwd=str(root),
                capture_output=True,
                text=True,
            )

    def test_merge_nonexistent_task_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _init_repo(tmpdir)
            mgr = WorktreeManager(project_root=root, state_root=root)
            mgr.start_fleet()
            self.assertFalse(mgr.merge_worktree("nonexistent"))


class TestExtractFileReferences(unittest.TestCase):
    def test_backtick_paths(self) -> None:
        text = "Edit `src/router.py` and `tests/test_router.py`"
        refs = extract_file_references(text)
        self.assertIn("src/router.py", refs)
        self.assertIn("tests/test_router.py", refs)

    def test_bare_paths(self) -> None:
        text = "Modify src/worktree.py and hooks/session_start.py"
        refs = extract_file_references(text)
        self.assertIn("src/worktree.py", refs)
        self.assertIn("hooks/session_start.py", refs)

    def test_no_paths(self) -> None:
        text = "Fix the bug in the login form"
        refs = extract_file_references(text)
        self.assertEqual(refs, [])

    def test_deduplication(self) -> None:
        text = "Edit `src/router.py` then also change src/router.py"
        refs = extract_file_references(text)
        self.assertEqual(refs.count("src/router.py"), 1)

    def test_multiple_extensions(self) -> None:
        text = "`config.json` and `setup.toml` and `script.sh`"
        refs = extract_file_references(text)
        self.assertIn("config.json", refs)
        self.assertIn("setup.toml", refs)
        self.assertIn("script.sh", refs)


class TestWorkerStateTargetFiles(unittest.TestCase):
    def test_serialization_round_trip(self) -> None:
        ws = WorkerState(
            task_id="abc123",
            description="test",
            branch="fleet/abc123",
            path="/tmp/wt",
            target_files=["src/a.py", "src/b.py"],
        )
        data = ws.to_dict()
        self.assertEqual(data["target_files"], ["src/a.py", "src/b.py"])
        restored = WorkerState.from_dict(data)
        self.assertEqual(restored.target_files, ["src/a.py", "src/b.py"])

    def test_from_dict_defaults_empty(self) -> None:
        data = {
            "task_id": "x",
            "description": "test",
            "branch": "fleet/x",
            "path": "/tmp/wt",
        }
        ws = WorkerState.from_dict(data)
        self.assertEqual(ws.target_files, [])


class TestValidateWave(unittest.TestCase):
    def test_no_overlap_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _init_repo(tmpdir)
            mgr = WorktreeManager(project_root=root, state_root=root)
            result = mgr.validate_wave(
                [
                    {"description": "a", "target_files": ["src/a.py"]},
                    {"description": "b", "target_files": ["src/b.py"]},
                ]
            )
            self.assertTrue(result["valid"])
            self.assertEqual(result["conflicts"], [])

    def test_overlap_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _init_repo(tmpdir)
            mgr = WorktreeManager(project_root=root, state_root=root)
            result = mgr.validate_wave(
                [
                    {"description": "a", "target_files": ["src/shared.py", "src/a.py"]},
                    {"description": "b", "target_files": ["src/shared.py", "src/b.py"]},
                ]
            )
            self.assertFalse(result["valid"])
            self.assertEqual(len(result["conflicts"]), 1)
            self.assertIn("src/shared.py", result["conflicts"][0]["files"])
            self.assertEqual(result["conflicts"][0]["tasks"], [0, 1])

    def test_three_tasks_pairwise_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _init_repo(tmpdir)
            mgr = WorktreeManager(project_root=root, state_root=root)
            result = mgr.validate_wave(
                [
                    {"description": "a", "target_files": ["src/x.py"]},
                    {"description": "b", "target_files": ["src/x.py", "src/y.py"]},
                    {"description": "c", "target_files": ["src/y.py"]},
                ]
            )
            self.assertFalse(result["valid"])
            self.assertEqual(len(result["conflicts"]), 2)

    def test_empty_target_files_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _init_repo(tmpdir)
            mgr = WorktreeManager(project_root=root, state_root=root)
            result = mgr.validate_wave(
                [
                    {"description": "a", "target_files": []},
                    {"description": "b", "target_files": []},
                ]
            )
            self.assertTrue(result["valid"])

    def test_auto_extract_from_description(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _init_repo(tmpdir)
            mgr = WorktreeManager(project_root=root, state_root=root)
            result = mgr.validate_wave(
                [
                    {"description": "Edit `src/shared.py` and `src/a.py`"},
                    {"description": "Modify `src/shared.py` and `src/b.py`"},
                ]
            )
            self.assertFalse(result["valid"])
            self.assertEqual(len(result["conflicts"]), 1)


if __name__ == "__main__":
    unittest.main()
