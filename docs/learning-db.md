# Learning Database

SQLite with FTS5 full-text search. Knowledge flows through a lifecycle:

```
Record (hooks capture errors/patterns)
  -> Inject (FTS5 query on every user prompt)
  -> Feedback (success: +0.15 confidence, failure: -0.10)
  -> Decay (time-based: 0.01/day, floor 0.1)
  -> Graduate (confidence >= 0.9 + 5 observations -> written to Claude Code memory system)
  -> Prune (confidence < 0.1 + 90 days stale -> deleted)
```

## How it's used

- **Recording**: Hooks on Claude Code lifecycle events (tool errors, compaction, session stop) capture error patterns and fixes
- **Injection**: On every user prompt, the `user_prompt_submit` hook runs an FTS5 query against the learning DB and injects relevant knowledge into context
- **Feedback**: When a learning helps solve a problem, its confidence increases; when it leads to a wrong path, it decreases
- **Teaching**: `/learn` lets you manually teach the system facts that start at 0.7 confidence

## Graduation

When a learning reaches confidence ≥ 0.9 with ≥ 5 observations, it is eligible for graduation. The daily `session_start` hook auto-graduates eligible learnings:

- **Error-signature learnings** (tool failures with a hash) stay in the DB — they're surfaced on-demand via FTS5 matching and don't need to be in memory.
- **All other learnings** are written as `feedback`-type memory files to `~/.claude/projects/{encoded-path}/memory/` and indexed in `MEMORY.md`. Claude Code loads these automatically into every conversation.
- Graduated rows are marked with the memory file path in `graduated_to` and excluded from all FTS5/injection queries.
- `MEMORY.md` is capped at 150 entries to avoid overflow (Claude Code truncates after ~200 lines).

## Storage

The database lives at `~/.claude/autodidact/learning.db` and is shared across all projects and worktrees. Learnings are tagged with the repo they originated from but are queryable globally.
