"""Dependency graph for fleet task decomposition.

Partitions tasks into optimal waves using Kahn's algorithm,
respecting both explicit depends_on edges and implicit
file-overlap edges. Pure logic — no autodidact imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TaskNode:
    """A single task with its file targets and dependencies."""

    task_id: str
    description: str
    target_files: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)


class TaskGraph:
    """Builds a dependency graph and partitions tasks into waves.

    Waves respect:
    - Explicit depends_on edges between tasks
    - Implicit edges from file-set overlap (two tasks sharing target files
      are serialized, with the lower-indexed task going first)
    - A maximum number of tasks per wave
    """

    def __init__(self, max_per_wave: int = 3) -> None:
        self.nodes: dict[str, TaskNode] = {}
        self.max_per_wave = max_per_wave
        self._insertion_order: list[str] = []

    def add_task(self, node: TaskNode) -> None:
        """Register a task node in the graph."""
        self.nodes[node.task_id] = node
        self._insertion_order.append(node.task_id)

    def _build_edges(self) -> dict[str, set[str]]:
        """Build adjacency: {task_id: set of task_ids it must wait for}.

        Combines explicit depends_on with implicit file-overlap edges.
        For file overlaps, the task added later depends on the task added earlier
        (deterministic tie-breaking by insertion order).
        """
        # task_id -> set of task_ids it depends on (must wait for)
        edges: dict[str, set[str]] = {tid: set() for tid in self.nodes}

        # Explicit depends_on
        for tid, node in self.nodes.items():
            for dep in node.depends_on:
                if dep in self.nodes:
                    edges[tid].add(dep)

        # Implicit file-overlap edges (lower insertion order goes first)
        order = {tid: i for i, tid in enumerate(self._insertion_order)}
        task_ids = list(self.nodes.keys())
        for i in range(len(task_ids)):
            for j in range(i + 1, len(task_ids)):
                a, b = task_ids[i], task_ids[j]
                files_a = set(self.nodes[a].target_files)
                files_b = set(self.nodes[b].target_files)
                if files_a and files_b and (files_a & files_b):
                    # Later-inserted task depends on earlier-inserted
                    if order[a] < order[b]:
                        edges[b].add(a)
                    else:
                        edges[a].add(b)

        return edges

    def partition_waves(self) -> list[list[str]]:
        """Partition tasks into ordered waves using Kahn's algorithm.

        Returns a list of waves, each wave being a list of task_ids.
        Tasks within a wave are independent; cross-wave ordering
        respects dependency edges.

        Raises ValueError if a cycle is detected.
        """
        if not self.nodes:
            return []

        edges = self._build_edges()

        # Compute in-degree
        in_degree: dict[str, int] = {tid: 0 for tid in self.nodes}
        for tid, deps in edges.items():
            in_degree[tid] = len(deps)

        remaining = set(self.nodes.keys())
        waves: list[list[str]] = []

        while remaining:
            # Find all tasks with no unmet dependencies
            ready = sorted([tid for tid in remaining if in_degree[tid] == 0])
            if not ready:
                raise ValueError(f"Cycle detected in task graph. Remaining: {remaining}")

            # Split into sub-waves of max_per_wave
            for i in range(0, len(ready), self.max_per_wave):
                waves.append(ready[i : i + self.max_per_wave])

            # Remove dispatched tasks, decrement in-degrees
            for tid in ready:
                remaining.remove(tid)
                # Decrement in-degree for tasks that depended on this one
                for other_tid in remaining:
                    if tid in edges.get(other_tid, set()):
                        in_degree[other_tid] -= 1

        return waves

    def validate(self) -> dict[str, object]:
        """Validate the graph. Returns validation result.

        Returns:
            {
                "valid": bool,
                "waves": int,
                "warnings": list[str],
                "error": str | None,
            }
        """
        warnings: list[str] = []

        # Check for references to unknown task_ids
        for tid, node in self.nodes.items():
            for dep in node.depends_on:
                if dep not in self.nodes:
                    warnings.append(f"Task '{tid}' depends on unknown task '{dep}'")

        # Check for cycles and compute waves
        try:
            waves = self.partition_waves()
        except ValueError as e:
            return {
                "valid": False,
                "waves": 0,
                "warnings": warnings,
                "error": str(e),
            }

        # Check for large fan-out (many tasks depending on one)
        edges = self._build_edges()
        dependents: dict[str, int] = {tid: 0 for tid in self.nodes}
        for _tid, deps in edges.items():
            for dep in deps:
                dependents[dep] += 1
        for tid, count in dependents.items():
            if count > 5:
                warnings.append(f"Task '{tid}' has {count} dependents — potential bottleneck")

        return {
            "valid": True,
            "waves": len(waves),
            "warnings": warnings,
            "error": None,
        }
