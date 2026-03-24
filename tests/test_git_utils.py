"""Tests for git utility functions."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.git_utils import resolve_main_repo, resolve_project_root


def _real_path(p: str) -> str:
    """Resolve symlinks (macOS /var -> /private/var)."""
    return os.path.realpath(p)


class TestResolveProjectRoot(unittest.TestCase):
    def test_returns_repo_root_for_normal_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = _real_path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
            result = resolve_project_root(tmpdir)
            self.assertEqual(result, tmpdir)

    def test_returns_repo_root_from_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = _real_path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
            subdir = Path(tmpdir) / "a" / "b"
            subdir.mkdir(parents=True)
            result = resolve_project_root(str(subdir))
            self.assertEqual(result, tmpdir)

    def test_falls_back_to_cwd_for_non_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = resolve_project_root(tmpdir)
            self.assertEqual(result, tmpdir)


class TestResolveMainRepo(unittest.TestCase):
    def test_returns_repo_root_for_normal_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = _real_path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "--allow-empty", "-m", "init"],
                cwd=tmpdir,
                capture_output=True,
                check=True,
            )
            result = resolve_main_repo(tmpdir)
            self.assertEqual(result, tmpdir)

    def test_returns_main_repo_from_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = _real_path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "--allow-empty", "-m", "init"],
                cwd=tmpdir,
                capture_output=True,
                check=True,
            )
            wt_path = Path(tmpdir) / "my-worktree"
            subprocess.run(
                ["git", "worktree", "add", str(wt_path), "-b", "test-branch"],
                cwd=tmpdir,
                capture_output=True,
                check=True,
            )
            result = resolve_main_repo(str(wt_path))
            self.assertEqual(result, tmpdir)

            subprocess.run(
                ["git", "worktree", "remove", str(wt_path)],
                cwd=tmpdir,
                capture_output=True,
            )

    def test_falls_back_to_cwd_for_non_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = resolve_main_repo(tmpdir)
            self.assertEqual(result, tmpdir)

    def test_resolve_project_root_returns_worktree_root(self) -> None:
        """resolve_project_root returns the worktree root, not main repo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = _real_path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "--allow-empty", "-m", "init"],
                cwd=tmpdir,
                capture_output=True,
                check=True,
            )
            wt_path = Path(tmpdir) / "wt"
            subprocess.run(
                ["git", "worktree", "add", str(wt_path), "-b", "wt-branch"],
                cwd=tmpdir,
                capture_output=True,
                check=True,
            )
            result = resolve_project_root(str(wt_path))
            self.assertEqual(result, str(wt_path))

            main = resolve_main_repo(str(wt_path))
            self.assertEqual(main, tmpdir)

            subprocess.run(
                ["git", "worktree", "remove", str(wt_path)],
                cwd=tmpdir,
                capture_output=True,
            )


if __name__ == "__main__":
    unittest.main()
