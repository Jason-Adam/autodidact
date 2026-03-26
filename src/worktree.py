"""Git worktree lifecycle manager for fleet parallel execution.

Creates, manages, merges, and cleans up isolated git worktrees
for parallel task execution. Persists fleet state to
.planning/fleet/active.json for crash recovery and cross-session tracking.
"""

from __future__ import annotations

import json
import re
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.git_utils import resolve_main_repo, resolve_project_root

if TYPE_CHECKING:
    from src.task_graph import TaskGraph

_SAFE_TASK_ID = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")
_SAFE_GIT_REF = re.compile(r"^[a-zA-Z0-9_./@~^:-]{1,256}$")

WORKTREE_DIR = ".worktrees"
BRANCH_PREFIX = "fleet"
STATE_DIR = ".planning/fleet"
STATE_FILE = "active.json"

_FILE_EXT_PATTERN = re.compile(
    r"`([^`]+\.(?:py|ts|js|md|json|yaml|yml|toml|sql|sh))`"
    r"|(\b[\w./\-]+\.(?:py|ts|js|md|json|yaml|yml|toml|sql|sh)\b)"
)


def extract_file_references(text: str) -> list[str]:
    """Extract file path references from free-form text.

    Matches both backtick-quoted paths and bare paths with known extensions.
    Returns deduplicated list preserving first-seen order.
    """
    seen: dict[str, None] = {}
    for m in _FILE_EXT_PATTERN.finditer(text):
        path = m.group(1) or m.group(2)
        if path and path not in seen:
            seen[path] = None
    return list(seen)


# ── State Model ─────────────────────────────────────────────────────────


@dataclass
class WorkerState:
    task_id: str
    description: str
    branch: str
    path: str
    status: str = "active"  # active | completed | merged | failed | cleaned
    brief: str | None = None
    target_files: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "branch": self.branch,
            "path": self.path,
            "status": self.status,
            "brief": self.brief,
            "target_files": self.target_files,
            "depends_on": self.depends_on,
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
            target_files=data.get("target_files", []),
            depends_on=data.get("depends_on", []),
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
            self.created = datetime.now(UTC).isoformat()

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

    def __init__(self, project_root: Path, state_root: Path | None = None) -> None:
        # Resolve to main repo for git worktree add/remove (prevents nested worktrees)
        self.project_root = Path(resolve_main_repo(str(project_root)))
        # Resolve to the spawning worktree for merge operations —
        # fleet workers branch from main but merge back into the caller's branch
        self.merge_root = Path(resolve_project_root(str(project_root)))
        # State lives in the caller's directory (preserves per-worktree isolation)
        self._state_root = state_root or project_root
        self.state: FleetState | None = self._load_state()

    @property
    def worktree_base(self) -> Path:
        return self.project_root / WORKTREE_DIR

    @property
    def state_path(self) -> Path:
        return self._state_root / STATE_DIR / STATE_FILE

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
        target_files: list[str] | None = None,
    ) -> WorkerState:
        """Create an isolated worktree and register it in fleet state."""
        if task_id is None:
            task_id = uuid.uuid4().hex[:8]
        elif not _SAFE_TASK_ID.match(task_id):
            raise ValueError(f"Invalid task_id: {task_id!r}")

        if not _SAFE_GIT_REF.match(base_ref):
            raise ValueError(f"Invalid base_ref: {base_ref!r}")

        # Auto-extract file targets from description if not provided
        resolved_files = (
            target_files if target_files is not None else extract_file_references(description)
        )

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
            target_files=resolved_files,
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

        wt_path = Path(worker.path).resolve()
        if not str(wt_path).startswith(str(self.worktree_base.resolve())):
            return
        if wt_path.exists():
            subprocess.run(
                ["git", "worktree", "remove", str(wt_path), "--force"],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
            )

        subprocess.run(
            ["git", "branch", "-D", "--", worker.branch],
            cwd=str(self.project_root),
            capture_output=True,
            text=True,
        )

        worker.status = "cleaned"
        self._save_state()

    def merge_worktree(self, task_id: str) -> bool:
        """Merge a worker branch into the spawning worktree's branch.

        Runs git merge in merge_root (the worktree that launched the fleet),
        not project_root (the main repo). On failure, aborts the merge to
        leave the working tree clean for subsequent merges.
        """
        if self.state is None:
            return False

        worker = None
        for w in self.state.all_workers:
            if w.task_id == task_id:
                worker = w
                break
        if not worker:
            return False

        result = subprocess.run(
            ["git", "merge", "--no-edit", "--", worker.branch],
            cwd=str(self.merge_root),
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            worker.status = "merged"
            self._save_state()
            return True

        # Merge failed — abort to leave working tree clean
        subprocess.run(
            ["git", "merge", "--abort"],
            cwd=str(self.merge_root),
            capture_output=True,
            text=True,
        )
        worker.status = "failed"
        self._save_state()
        return False

    def cleanup_all(self) -> int:
        """Remove all fleet worktrees. Returns count cleaned."""
        count = 0
        if self.state:
            for worker in self.state.all_workers:
                if worker.status != "cleaned":
                    self.destroy_worktree(worker.task_id)
                    count += 1

        # Also clean any orphaned worktrees (with containment check)
        if self.worktree_base.exists():
            base_resolved = str(self.worktree_base.resolve())
            for wt_dir in self.worktree_base.glob("fleet-*"):
                if wt_dir.is_dir() and str(wt_dir.resolve()).startswith(base_resolved):
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

    def validate_wave(self, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        """Check proposed tasks for file-set overlaps before dispatch.

        Args:
            tasks: list of {"description": str, "target_files": list[str]}.
                   If target_files is missing, auto-extracted from description.

        Returns:
            {"valid": bool, "conflicts": [{"files": list[str], "tasks": [int, int]}]}
        """
        # Resolve target files for each task
        resolved: list[list[str]] = []
        for task in tasks:
            tf = task.get("target_files")
            files = tf if tf is not None else extract_file_references(task.get("description", ""))
            resolved.append(files)

        # Pairwise intersection check
        conflicts: list[dict[str, Any]] = []
        for i in range(len(resolved)):
            for j in range(i + 1, len(resolved)):
                overlap = set(resolved[i]) & set(resolved[j])
                if overlap:
                    conflicts.append({"files": sorted(overlap), "tasks": [i, j]})

        return {"valid": len(conflicts) == 0, "conflicts": conflicts}

    def build_task_graph(self, tasks: list[dict[str, Any]], max_per_wave: int = 3) -> TaskGraph:
        """Build a dependency graph from proposed tasks.

        Args:
            tasks: list of {
                "task_id": str,
                "description": str,
                "target_files": list[str],  # optional, auto-extracted if missing
                "depends_on": list[str],    # optional
            }
            max_per_wave: maximum tasks per wave

        Returns:
            TaskGraph ready for partition_waves() or validate()
        """
        from src.task_graph import TaskGraph, TaskNode

        graph = TaskGraph(max_per_wave=max_per_wave)
        for task in tasks:
            tf = task.get("target_files")
            files = tf if tf is not None else extract_file_references(task.get("description", ""))
            node = TaskNode(
                task_id=task["task_id"],
                description=task.get("description", ""),
                target_files=files,
                depends_on=task.get("depends_on", []),
            )
            graph.add_task(node)
        return graph

    def auto_partition_waves(
        self, tasks: list[dict[str, Any]], max_per_wave: int = 3
    ) -> list[list[dict[str, Any]]]:
        """Build graph, validate, partition, and return grouped tasks.

        Returns list of waves, each wave being a list of task dicts.
        Raises ValueError on cycle detection.
        """
        graph = self.build_task_graph(tasks, max_per_wave)
        validation = graph.validate()
        if not validation["valid"]:
            raise ValueError(validation["error"])

        wave_ids = graph.partition_waves()
        task_map = {t["task_id"]: t for t in tasks}
        return [[task_map[tid] for tid in wave] for wave in wave_ids]

    # ── Fleet Recovery ─────────────────────────────────────────────

    def _check_worktree_health(self, worker: WorkerState) -> str:
        """Check a worker's worktree for usable changes.

        Returns one of:
        - "missing"    — worktree path doesn't exist on disk
        - "committed"  — worktree has committed changes on its branch
        - "uncommitted"— worktree has uncommitted changes
        - "empty"      — worktree exists but has no changes at all
        """
        path = Path(worker.path).resolve()
        if not str(path).startswith(str(self.worktree_base.resolve())):
            return "missing"
        if not path.exists():
            return "missing"

        # Check for committed changes on the worker's branch
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", f"HEAD..{worker.branch}", "--"],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return "committed"
        except (subprocess.TimeoutExpired, OSError):
            pass

        # Check for uncommitted changes in the worktree
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(path),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return "uncommitted"
        except (subprocess.TimeoutExpired, OSError):
            pass

        return "empty"

    def recover_fleet(self) -> list[WorkerState]:
        """Recover interrupted fleet workers.

        Scans active.json for workers with status='active' (interrupted mid-execution).

        For each interrupted worker:
        - 'committed' -> mark as 'completed' (ready to merge)
        - 'uncommitted' -> keep as 'active' (needs re-dispatch)
        - 'empty' -> mark as 'failed', clean up worktree
        - 'missing' -> mark as 'failed'

        Returns list of workers still needing re-dispatch (status='active').
        """
        if self.state is None:
            return []

        needs_redispatch: list[WorkerState] = []

        for worker in self.state.all_workers:
            if worker.status != "active":
                continue

            health = self._check_worktree_health(worker)

            if health == "committed":
                worker.status = "completed"
            elif health == "uncommitted":
                needs_redispatch.append(worker)
            elif health == "empty":
                self.destroy_worktree(worker.task_id)
            elif health == "missing":
                worker.status = "failed"

        self._save_state()
        return needs_redispatch
