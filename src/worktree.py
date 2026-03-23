"""Git worktree lifecycle manager for fleet parallel execution.

Creates, manages, merges, and cleans up isolated git worktrees
for parallel task execution. Persists fleet state to
.planning/fleet/active.json for crash recovery and cross-session tracking.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKTREE_DIR = ".worktrees"
BRANCH_PREFIX = "fleet"
STATE_DIR = ".planning/fleet"
STATE_FILE = "active.json"


# ── State Model ─────────────────────────────────────────────────────────

@dataclass
class WorkerState:
    task_id: str
    description: str
    branch: str
    path: str
    status: str = "active"  # active | completed | merged | failed | cleaned
    brief: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "branch": self.branch,
            "path": self.path,
            "status": self.status,
            "brief": self.brief,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkerState:
        return cls(
            task_id=data["task_id"],
            description=data.get("description", ""),
            branch=data["branch"],
            path=data["path"],
            status=data.get("status", "active"),
            brief=data.get("brief"),
        )


@dataclass
class WaveState:
    number: int
    workers: list[WorkerState] = field(default_factory=list)
    combined_brief: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "workers": [w.to_dict() for w in self.workers],
            "combined_brief": self.combined_brief,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WaveState:
        wave = cls(
            number=data["number"],
            combined_brief=data.get("combined_brief"),
        )
        wave.workers = [WorkerState.from_dict(w) for w in data.get("workers", [])]
        return wave


@dataclass
class FleetState:
    id: str
    status: str = "in_progress"  # in_progress | completed | failed | aborted
    created: str = ""
    waves: list[WaveState] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.created:
            self.created = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "created": self.created,
            "waves": [w.to_dict() for w in self.waves],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FleetState:
        state = cls(
            id=data["id"],
            status=data.get("status", "in_progress"),
            created=data.get("created", ""),
        )
        state.waves = [WaveState.from_dict(w) for w in data.get("waves", [])]
        return state

    @property
    def current_wave(self) -> WaveState | None:
        return self.waves[-1] if self.waves else None

    @property
    def all_workers(self) -> list[WorkerState]:
        return [w for wave in self.waves for w in wave.workers]


# ── Worktree Manager ───────────────────────────────────────────────────

class WorktreeManager:
    """Manages git worktrees and fleet state for parallel execution."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.state: FleetState | None = self._load_state()

    @property
    def worktree_base(self) -> Path:
        return self.project_root / WORKTREE_DIR

    @property
    def state_path(self) -> Path:
        return self.project_root / STATE_DIR / STATE_FILE

    # ── State Persistence ───────────────────────────────────────────

    def _load_state(self) -> FleetState | None:
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text())
                return FleetState.from_dict(data)
            except (json.JSONDecodeError, KeyError):
                return None
        return None

    def _save_state(self) -> None:
        if self.state is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state.to_dict(), indent=2))

    def _clear_state(self) -> None:
        if self.state_path.exists():
            self.state_path.unlink()
        self.state = None

    # ── Fleet Lifecycle ─────────────────────────────────────────────

    def start_fleet(self) -> FleetState:
        """Initialize a new fleet session."""
        self.state = FleetState(id=uuid.uuid4().hex[:8])
        self._save_state()
        return self.state

    def start_wave(self) -> WaveState:
        """Start a new wave within the current fleet."""
        if self.state is None:
            self.start_fleet()
        assert self.state is not None
        wave_num = len(self.state.waves) + 1
        wave = WaveState(number=wave_num)
        self.state.waves.append(wave)
        self._save_state()
        return wave

    def finish_fleet(self) -> None:
        """Mark fleet as completed and clean up state file."""
        if self.state:
            self.state.status = "completed"
            self._save_state()
        self._clear_state()

    def abort_fleet(self) -> None:
        """Mark fleet as aborted (e.g., circuit breaker tripped)."""
        if self.state:
            self.state.status = "aborted"
            self._save_state()

    # ── Worktree Operations ─────────────────────────────────────────

    def create_worktree(
        self,
        description: str,
        task_id: str | None = None,
        base_ref: str = "HEAD",
    ) -> WorkerState:
        """Create an isolated worktree and register it in fleet state."""
        if task_id is None:
            task_id = uuid.uuid4().hex[:8]

        branch = f"{BRANCH_PREFIX}/{task_id}"
        wt_path = self.worktree_base / f"fleet-{task_id}"

        subprocess.run(
            ["git", "worktree", "add", str(wt_path), "-b", branch, base_ref],
            cwd=str(self.project_root),
            capture_output=True,
            text=True,
            check=True,
        )

        worker = WorkerState(
            task_id=task_id,
            description=description,
            branch=branch,
            path=str(wt_path),
            status="active",
        )

        # Register in current wave
        if self.state and self.state.current_wave:
            self.state.current_wave.workers.append(worker)
            self._save_state()

        return worker

    def complete_worker(self, task_id: str, brief: str | None = None) -> None:
        """Mark a worker as completed with its discovery brief."""
        if self.state is None:
            return
        for worker in self.state.all_workers:
            if worker.task_id == task_id:
                worker.status = "completed"
                worker.brief = brief
                break
        self._save_state()

    def set_wave_brief(self, wave_number: int, combined_brief: str) -> None:
        """Set the compressed combined brief for a wave."""
        if self.state is None:
            return
        for wave in self.state.waves:
            if wave.number == wave_number:
                wave.combined_brief = combined_brief
                break
        self._save_state()

    def destroy_worktree(self, task_id: str) -> None:
        """Remove a worktree and its branch."""
        if self.state is None:
            return

        worker = None
        for w in self.state.all_workers:
            if w.task_id == task_id:
                worker = w
                break
        if not worker:
            return

        wt_path = Path(worker.path)
        if wt_path.exists():
            subprocess.run(
                ["git", "worktree", "remove", str(wt_path), "--force"],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
            )

        subprocess.run(
            ["git", "branch", "-D", worker.branch],
            cwd=str(self.project_root),
            capture_output=True,
            text=True,
        )

        worker.status = "cleaned"
        self._save_state()

    def merge_worktree(self, task_id: str, target_branch: str = "") -> bool:
        """Merge a worktree branch into target. Returns True on success."""
        if self.state is None:
            return False

        worker = None
        for w in self.state.all_workers:
            if w.task_id == task_id:
                worker = w
                break
        if not worker:
            return False

        if not target_branch:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
            )
            target_branch = result.stdout.strip()

        result = subprocess.run(
            ["git", "merge", worker.branch, "--no-edit"],
            cwd=str(self.project_root),
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            worker.status = "merged"
            self._save_state()
            return True
        else:
            worker.status = "failed"
            self._save_state()
            return False

    def cleanup_all(self) -> int:
        """Remove all fleet worktrees. Returns count cleaned."""
        count = 0
        if self.state:
            for worker in self.state.all_workers:
                if worker.status not in ("cleaned",):
                    self.destroy_worktree(worker.task_id)
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

    # ── Query ───────────────────────────────────────────────────────

    def get_active_workers(self) -> list[WorkerState]:
        if self.state is None:
            return []
        return [w for w in self.state.all_workers if w.status == "active"]

    def get_previous_briefs(self) -> str | None:
        """Get the combined brief from the previous wave (for injection into next wave)."""
        if self.state is None or len(self.state.waves) < 2:
            return None
        prev_wave = self.state.waves[-2]
        return prev_wave.combined_brief

    def is_active(self) -> bool:
        return self.state is not None and self.state.status == "in_progress"
