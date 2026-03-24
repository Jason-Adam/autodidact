# Planning and Document Persistence

All planning state lives in the `.planning/` directory at the project root (or worktree root).

## Directory structure

```
.planning/
|-- research/         # Research docs with YAML frontmatter
|-- plans/            # Plan docs (flat markdown)
|-- campaigns/        # Campaign state JSON
|-- experiments/      # Experiment state (state.json + log.tsv per session)
|-- fleet/            # Fleet state (active.json)
|-- loop_signals.json # Exit tracker state
|-- loop_cb_state.json# Circuit breaker state
|-- loop.pid          # Running loop PID
'-- loop.log          # Loop output
```

## Syncing to centralized storage

Use `/sync-thoughts` to copy research and plan documents to `~/.planning/` for cross-project access:

```bash
/sync-thoughts              # sync all docs from current project
/sync-thoughts <file>       # sync a specific file
```

Documents are copied (not moved) — local `.planning/` files are always preserved.

## Worktree isolation

`.planning/` state stays isolated per worktree, matching the one-worktree-per-task workflow. Learnings in the database are shared across all worktrees (resolved to the main repo root).
