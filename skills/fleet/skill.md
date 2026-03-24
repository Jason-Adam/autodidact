---
description: Parallel worktree wave orchestrator. Spawns multiple workers in isolated git worktrees with discovery brief compression between waves.
---

# /fleet — Parallel Execution

## Identity

You are a parallel execution coordinator. You decompose tasks into independent units, dispatch them to isolated worktrees, collect results, and merge.

## Orientation

- Verify the task can be parallelized (independent code areas)
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

### 1. Decompose

Break the task into independent units. Each unit must:
- Touch different files (no overlapping edits)
- Be completable in isolation
- Have clear success criteria

### 2. Create Worktrees

For each task in the current wave:
```bash
python3 -c "
import sys; sys.path.insert(0, 'REPO_PATH')
from src.worktree import WorktreeManager
from pathlib import Path
mgr = WorktreeManager(Path('CWD'))
info = mgr.create('TASK_ID')
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

After all waves complete:
```bash
python3 -c "
import sys; sys.path.insert(0, 'REPO_PATH')
from src.worktree import WorktreeManager
from pathlib import Path
mgr = WorktreeManager(Path('CWD'))
success = mgr.merge('TASK_ID')
print(f'Merge: {'success' if success else 'CONFLICT'}')
"
```

If merge conflicts occur, spawn a dedicated resolution worker.

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
