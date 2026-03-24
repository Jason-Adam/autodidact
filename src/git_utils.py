"""Git utilities for resolving repository roots through worktrees.

When Claude Code starts with --worktree, the cwd is a worktree path,
not the main repo root. These utilities normalize paths so that
learnings are shared across worktrees and fleet doesn't create
nested worktrees.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def resolve_project_root(cwd: str) -> str:
    """Return the git repo root from cwd.

    In a worktree, returns the *worktree* root (not the main repo).
    Falls back to raw cwd for non-git directories.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        pass
    return cwd


def resolve_main_repo(cwd: str) -> str:
    """Return the main git repo root, resolving through worktrees.

    In a worktree, returns the MAIN repo root, not the worktree root.
    Uses --git-common-dir which points to the shared .git directory.
    Falls back to raw cwd for non-git directories.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            git_common = result.stdout.strip()
            # --git-common-dir returns /repo/.git — parent is the repo root
            repo_root = str(Path(git_common).parent)
            return repo_root
    except (subprocess.TimeoutExpired, OSError):
        pass
    return cwd
