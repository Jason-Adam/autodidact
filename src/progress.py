"""Git-based progress detection between autonomous loop iterations.

Captures git state snapshots and compares them to detect whether
an iteration made productive changes (new commits, file changes,
or uncommitted work).
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass


@dataclass
class GitSnapshot:
    head_sha: str
    dirty_files: int
    timestamp: float


@dataclass
class ProgressReport:
    files_changed: int
    commits_made: int
    has_uncommitted: bool
    is_productive: bool
    elapsed_seconds: float


def _run(cmd: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with standard safety options."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=5,
    )


def capture_snapshot(cwd: str) -> GitSnapshot:
    """Capture current git state before an iteration.

    Returns a snapshot with HEAD sha, dirty file count, and timestamp.
    On any error, returns GitSnapshot("", 0, time.time()).
    """
    try:
        head = _run(["git", "rev-parse", "HEAD"], cwd=cwd)
        status = _run(["git", "status", "--porcelain"], cwd=cwd)
        head_sha = head.stdout.strip() if head.returncode == 0 else ""
        dirty = (
            [line for line in status.stdout.strip().splitlines() if line]
            if status.returncode == 0
            else []
        )
        return GitSnapshot(
            head_sha=head_sha,
            dirty_files=len(dirty),
            timestamp=time.time(),
        )
    except (subprocess.TimeoutExpired, OSError):
        return GitSnapshot(head_sha="", dirty_files=0, timestamp=time.time())


def compare(cwd: str, before: GitSnapshot) -> ProgressReport:
    """Compare current git state against a prior snapshot.

    Detects new commits, changed files, and uncommitted work since
    the snapshot was taken. Returns a ProgressReport summarising
    the delta.
    """
    elapsed = time.time() - before.timestamp
    try:
        commits_result = _run(
            ["git", "rev-list", f"{before.head_sha}..HEAD", "--count"],
            cwd=cwd,
        )
        commits_made = int(commits_result.stdout.strip()) if commits_result.returncode == 0 else 0

        diff_result = _run(
            ["git", "diff", "--name-only", before.head_sha],
            cwd=cwd,
        )
        changed = (
            [line for line in diff_result.stdout.strip().splitlines() if line]
            if diff_result.returncode == 0
            else []
        )
        files_changed = len(changed)

        status_result = _run(["git", "status", "--porcelain"], cwd=cwd)
        dirty = (
            [line for line in status_result.stdout.strip().splitlines() if line]
            if status_result.returncode == 0
            else []
        )
        has_uncommitted = len(dirty) > before.dirty_files

        is_productive = files_changed > 0 or commits_made > 0 or has_uncommitted

        return ProgressReport(
            files_changed=files_changed,
            commits_made=commits_made,
            has_uncommitted=has_uncommitted,
            is_productive=is_productive,
            elapsed_seconds=elapsed,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ProgressReport(
            files_changed=0,
            commits_made=0,
            has_uncommitted=False,
            is_productive=False,
            elapsed_seconds=elapsed,
        )


def is_productive_timeout(cwd: str, before: GitSnapshot) -> bool:
    """Special case for exit code 124 (timeout).

    Returns True if git shows changes despite the timeout.
    """
    report = compare(cwd, before)
    return report.is_productive
