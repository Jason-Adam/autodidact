# Learning Database

SQLite with FTS5 full-text search. Knowledge flows through a lifecycle:

```
Record (hooks capture errors/patterns)
  -> Inject (FTS5 query on every user prompt)
  -> Feedback (success: +0.15 confidence, failure: -0.10)
  -> Decay (time-based: 0.01/day, floor 0.1)
  -> Graduate (confidence >= 0.9 + 5 observations -> promoted to CLAUDE.md)
  -> Prune (confidence < 0.1 + 90 days stale -> deleted)
```

## How it's used

- **Recording**: Hooks on Claude Code lifecycle events (tool errors, compaction, session stop) capture error patterns and fixes
- **Injection**: On every user prompt, the `user_prompt_submit` hook runs an FTS5 query against the learning DB and injects relevant knowledge into context
- **Feedback**: When a learning helps solve a problem, its confidence increases; when it leads to a wrong path, it decreases
- **Teaching**: `/learn` lets you manually teach the system facts that start at 0.7 confidence

## Storage

The database lives at `~/.claude/autodidact/learning.db` and is shared across all projects and worktrees. Learnings are tagged with the repo they originated from but are queryable globally.
