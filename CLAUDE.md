# Autodidact Development Guide

## What This Is

Autodidact is a self-teaching AI harness for Claude Code. It is NOT a traditional application — it's a collection of markdown skills, Python hooks/scripts, and agent definitions that give Claude Code a structured operating system for autonomous work.

## Architecture

- **src/**: 22-module flat Python stdlib library — all modules at `src/*.py` (db, router, confidence, graduate, interview, worktree, circuit_breaker, handoff, sync, documents, git_utils, response_analyzer, progress, exit_tracker, loop, experiment, convergence, fitness, rtk_integration, self_assessment, session_miner, task_graph)
- **hooks/**: 8 Python hooks that fire on Claude Code lifecycle events
- **skills/**: 14 markdown skill definitions (5-section format)
- **agents/**: 12 agent personas (research, review, implementation, orchestration)
- **commands/**: 17 slash commands (user-facing entry points)
- **templates/**: Reference formats for skills, handoffs, campaigns, briefs, clarify protocol

## Rules

- **Python stdlib only** — no third-party dependencies in src/ or hooks/
- **Global install** — everything symlinks to ~/.claude/, learning DB at ~/.claude/autodidact/learning.db
- **FTS5 for knowledge** — all learning queries go through SQLite FTS5 full-text search
- **Cost-ascending router** — /do resolves at cheapest tier possible (pattern → state → keyword → plan structure → LLM)
- **5-section skills** — Identity, Orientation, Protocol, Quality Gates, Exit Protocol
- **HANDOFF blocks** — <150 words, 3-5 bullets between skills/agents
- **Document persistence** — research and plan outputs saved to `.planning/{research|plans}/`, synced to `~/.planning/` via `/sync-thoughts` for cross-project access
- **Research frontmatter** — research docs get YAML frontmatter (date, git_commit, branch, repository, topic, tags, status). Plans do NOT get frontmatter.

## Testing

```bash
uv run python3 -m pytest tests/ -v
uv run python3 -m pytest tests/test_router.py -v            # Single file
uv run python3 -m pytest tests/test_router.py::test_name -v  # Single test
```

## Linting

```bash
uv run ruff check src/ hooks/        # Lint
uv run ruff format src/ hooks/       # Format
```

## Docs

See `docs/` for detailed architecture docs on commands, the learning DB, the loop, and planning.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for dependency management

## Installing

```bash
./install              # Install globally
./install --uninstall  # Remove
```
