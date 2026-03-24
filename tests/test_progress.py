"""Tests for git-based progress detection."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest

from src.progress import capture_snapshot, compare, is_productive_timeout


def _git(args: list[str], cwd: str) -> None:
    """Run a git command in the given directory."""
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


def _init_repo(path: str) -> None:
    """Initialise a git repo with one empty commit."""
    _git(["init"], cwd=path)
    _git(["config", "user.email", "test@test.com"], cwd=path)
    _git(["config", "user.name", "Test"], cwd=path)
    _git(["commit", "--allow-empty", "-m", "init"], cwd=path)


class TestCaptureSnapshot(unittest.TestCase):
    def test_capture_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = os.path.realpath(tmpdir)
            _init_repo(repo)
            snap = capture_snapshot(repo)
            self.assertTrue(len(snap.head_sha) > 0)
            self.assertEqual(snap.dirty_files, 0)
            self.assertGreater(snap.timestamp, 0)

    def test_capture_snapshot_with_dirty_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = os.path.realpath(tmpdir)
            _init_repo(repo)
            with open(os.path.join(repo, "dirty.txt"), "w") as f:
                f.write("dirty")
            snap = capture_snapshot(repo)
            self.assertGreater(snap.dirty_files, 0)

    def test_capture_snapshot_non_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = os.path.realpath(tmpdir)
            snap = capture_snapshot(repo)
            self.assertEqual(snap.head_sha, "")
            self.assertEqual(snap.dirty_files, 0)


class TestCompare(unittest.TestCase):
    def test_compare_detects_new_commits(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = os.path.realpath(tmpdir)
            _init_repo(repo)
            snap = capture_snapshot(repo)
            _git(["commit", "--allow-empty", "-m", "second"], cwd=repo)
            report = compare(repo, snap)
            self.assertEqual(report.commits_made, 1)
            self.assertTrue(report.is_productive)

    def test_compare_detects_uncommitted_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = os.path.realpath(tmpdir)
            _init_repo(repo)
            snap = capture_snapshot(repo)
            with open(os.path.join(repo, "new.txt"), "w") as f:
                f.write("new")
            report = compare(repo, snap)
            self.assertTrue(report.has_uncommitted)
            self.assertTrue(report.is_productive)

    def test_compare_no_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = os.path.realpath(tmpdir)
            _init_repo(repo)
            snap = capture_snapshot(repo)
            report = compare(repo, snap)
            self.assertFalse(report.is_productive)
            self.assertEqual(report.files_changed, 0)
            self.assertEqual(report.commits_made, 0)
            self.assertFalse(report.has_uncommitted)


class TestIsProductiveTimeout(unittest.TestCase):
    def test_is_productive_timeout_with_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = os.path.realpath(tmpdir)
            _init_repo(repo)
            snap = capture_snapshot(repo)
            with open(os.path.join(repo, "file.txt"), "w") as f:
                f.write("content")
            self.assertTrue(is_productive_timeout(repo, snap))

    def test_is_productive_timeout_no_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = os.path.realpath(tmpdir)
            _init_repo(repo)
            snap = capture_snapshot(repo)
            self.assertFalse(is_productive_timeout(repo, snap))


if __name__ == "__main__":
    unittest.main()
