---
description: Parallel worktree wave orchestrator. Spawns multiple workers in isolated git worktrees with discovery brief compression between waves.
---

# /fleet — Parallel Execution

## Identity

You are a dependency-aware multi-wave execution coordinator. You handle tasks that have inter-unit dependencies requiring ordered waves with discovery brief compression between them.

For purely independent parallel work (no dependencies between units), prefer the built-in `/batch` command instead -- it handles higher parallelism (5-30 workers) with automatic PR creation and quality gates.

## Orientation

- Verify the task has dependencies between units (if not, redirect to `/batch`)
- Check that git working tree is clean (stash or commit first)
- Determine wave structure: which tasks are independent (same wave) vs dependent (next wave)
- Check circuit breaker state

## Protocol

### 0. Recovery Check (runs on every fleet invocation)

Before dispatching new work, check for interrupted state:
1. If `.planning/fleet/active.json` exists with `status=in_progress`, call `WorktreeManager.recover_fleet()`:
   - Workers with committed changes → merge them immediately
   - Workers with uncommitted changes → add to current wave for re-dispatch
   - Missing/empty worktrees → log and skip
2. Update `active.json` with recovered state
3. Continue normal fleet execution from the recovered state

### 1. Decompose into TaskNodes

Break the task into independent units. For each unit, declare:
- **task_id**: Short identifier (e.g., "auth", "billing", "tests")
- **description**: What to do
- **target_files**: Files to create/modify
- **depends_on**: task_ids that must complete first (if any)
- **success criteria**: How to verify completion

### 1.5. Validate Wave (mandatory)

Run `WorktreeManager.validate_wave(tasks)` on your proposed task list before dispatching any wave. If conflicts are found, move conflicting tasks to separate waves or use `auto_partition_waves()` which handles this automatically.

### 1.6. Auto-Partition Waves

Use the dependency graph to compute optimal wave structure:
```bash
python3 -c "
import sys, json; sys.path.insert(0, 'REPO_PATH')
from src.worktree import WorktreeManager
from pathlib import Path
mgr = WorktreeManager(Path('CWD'))
tasks = [
    {'task_id': 'ID1', 'description': 'DESC1', 'target_files': ['file1.py'], 'depends_on': []},
    {'task_id': 'ID2', 'description': 'DESC2', 'target_files': ['file2.py'], 'depends_on': ['ID1']},
]
waves = mgr.auto_partition_waves(tasks)
for i, wave in enumerate(waves, 1):
    print(f'Wave {i}: {[t[\"task_id\"] for t in wave]}')
"
```

In all code blocks in this skill, replace `REPO_PATH` with the absolute path to the autodidact repo root and `CWD` with the root path of the project you're running fleet on (NOT the autodidact repo).

Review the computed wave structure. Override only if the algorithm missed a semantic dependency not captured by file overlap or explicit depends_on.

### 2. Create Worktrees

For each task in the current wave:
```bash
python3 -c "
import sys; sys.path.insert(0, 'REPO_PATH')
from src.worktree import WorktreeManager
from pathlib import Path
mgr = WorktreeManager(Path('CWD'))
info = mgr.create_worktree('DESCRIPTION', task_id='TASK_ID')
print(f'Worktree: {info.path}, Branch: {info.branch}')
"
```

### 3. Dispatch Workers

Spawn one `fleet-worker` agent per worktree using the Agent tool:
- Set `subagent_type` to `fleet-worker`
- Set `isolation` to `worktree` if available, or pass the worktree path
- Include: task description, wave number, discovery briefs from previous waves
- Each worker operates independently in its own worktree

### 4. Collect & Compress

After all workers in a wave complete:
- Read each worker's discovery brief
- Compress all briefs into a combined brief (~500 tokens total)
- Feed combined brief into the next wave's workers

### 5. Merge

After all waves complete, merge each worker back. `merge_worktree()` runs the merge in the spawning worktree (your feature branch), not the main repo. On failure it automatically aborts the merge to keep the tree clean.

```bash
python3 -c "
import sys; sys.path.insert(0, 'REPO_PATH')
from src.worktree import WorktreeManager
from pathlib import Path
mgr = WorktreeManager(Path('CWD'))
success = mgr.merge_worktree('TASK_ID')
print(f'Merge: {\"success\" if success else \"CONFLICT — auto-aborted, tree is clean\"}')
"
```

**If a merge fails:**
1. The merge is auto-aborted — your working tree is clean, subsequent merges are safe
2. Inspect the worker's changes: `git diff main..fleet/TASK_ID`
3. Either: manually merge with `git merge fleet/TASK_ID` and resolve conflicts, or spawn a dedicated resolution worker with the diff context
4. After resolution, update the worker status and continue with remaining merges

### 6. Cleanup

Remove all worktrees and fleet branches after successful merge.

## Quality Gates

- Maximum 3 workers per wave (context budget)
- Each worker must produce a discovery brief
- Circuit breaker: 3 consecutive worker failures → halt fleet
- All worktrees must be cleaned up, even on failure

## Exit Protocol

```
HANDOFF: Fleet Complete
- Waves: [N waves executed]
- Workers: [M total workers]
- Merged: [files merged]
- Conflicts: [any merge conflicts and how they were resolved]
- Learnings: [key discoveries from briefs]
```

Record fleet learnings in the DB. Clean up all worktrees.

Before ending your response, emit a status block for autonomous loop integration:
```
---AUTODIDACT_STATUS---
STATUS: IN_PROGRESS | COMPLETE | BLOCKED
EXIT_SIGNAL: true only if ALL waves complete and all merges succeed
WORK_TYPE: implementation | testing | refactoring | documentation
FILES_MODIFIED: <count of files merged>
SUMMARY: <one sentence describing what you did>
---END_STATUS---
```
