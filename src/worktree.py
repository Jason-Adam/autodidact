"""Git worktree lifecycle manager for fleet parallel execution.

Creates, manages, merges, and cleans up isolated git worktrees
for parallel task execution.
"""

from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path


WORKTREE_DIR = ".worktrees"
BRANCH_PREFIX = "fleet"


@dataclass
class WorktreeInfo:
    task_id: str
    path: str
    branch: str
    status: str = "active"  # active | merged | failed | cleaned


@dataclass
class WorktreeManager:
    """Manages git worktrees for fleet parallel execution."""
    project_root: Path
    worktrees: dict[str, WorktreeInfo] = field(default_factory=dict)

    @property
    def worktree_base(self) -> Path:
        return self.project_root / WORKTREE_DIR

    def create(self, task_id: str | None = None, base_ref: str = "HEAD") -> WorktreeInfo:
        """Create an isolated worktree for a task."""
        if task_id is None:
            task_id = uuid.uuid4().hex[:8]

        branch = f"{BRANCH_PREFIX}/{task_id}"
        wt_path = self.worktree_base / f"fleet-{task_id}"

        # Create worktree with new branch
        subprocess.run(
            ["git", "worktree", "add", str(wt_path), "-b", branch, base_ref],
            cwd=str(self.project_root),
            capture_output=True,
            text=True,
            check=True,
        )

        info = WorktreeInfo(
            task_id=task_id,
            path=str(wt_path),
            branch=branch,
            status="active",
        )
        self.worktrees[task_id] = info
        return info

    def destroy(self, task_id: str) -> None:
        """Remove a worktree and its branch."""
        info = self.worktrees.get(task_id)
        if not info:
            return

        wt_path = Path(info.path)

        # Remove worktree
        if wt_path.exists():
            subprocess.run(
                ["git", "worktree", "remove", str(wt_path), "--force"],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
            )

        # Delete branch
        subprocess.run(
            ["git", "branch", "-D", info.branch],
            cwd=str(self.project_root),
            capture_output=True,
            text=True,
        )

        info.status = "cleaned"

    def merge(self, task_id: str, target_branch: str = "") -> bool:
        """Merge a worktree branch into target. Returns True on success."""
        info = self.worktrees.get(task_id)
        if not info:
            return False

        if not target_branch:
            # Get current branch
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
            )
            target_branch = result.stdout.strip()

        result = subprocess.run(
            ["git", "merge", info.branch, "--no-edit"],
            cwd=str(self.project_root),
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            info.status = "merged"
            return True
        else:
            info.status = "failed"
            return False

    def list_active(self) -> list[WorktreeInfo]:
        """List all active fleet worktrees."""
        return [wt for wt in self.worktrees.values() if wt.status == "active"]

    def cleanup_all(self) -> int:
        """Remove all fleet worktrees. Returns count cleaned."""
        count = 0
        for task_id in list(self.worktrees.keys()):
            self.destroy(task_id)
            count += 1

        # Also clean any orphaned worktrees
        if self.worktree_base.exists():
            for wt_dir in self.worktree_base.glob("fleet-*"):
                if wt_dir.is_dir():
                    subprocess.run(
                        ["git", "worktree", "remove", str(wt_dir), "--force"],
                        cwd=str(self.project_root),
                        capture_output=True,
                        text=True,
                    )

        return count

    def get_discovery_brief_path(self, task_id: str) -> Path:
        """Get the path where a worker should write its discovery brief."""
        return self.worktree_base / f"brief-{task_id}.md"
