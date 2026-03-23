# Autodidact Development Guide

## What This Is

Autodidact is a self-teaching AI harness for Claude Code. It is NOT a traditional application — it's a collection of markdown skills, Python hooks/scripts, and agent definitions that give Claude Code a structured operating system for autonomous work.

## Architecture

- **src/**: Python stdlib library (db, router, confidence, interview, worktree, circuit_breaker, handoff, sync, documents)
- **hooks/**: 8 Python hooks that fire on Claude Code lifecycle events
- **skills/**: 10 markdown skill definitions (5-section format)
- **agents/**: 10 agent personas (research, implementation, orchestration)
- **commands/**: 12 slash commands (user-facing entry points)
- **templates/**: Reference formats for skills, handoffs, campaigns, briefs

## Rules

- **Python stdlib only** — no third-party dependencies in src/ or hooks/
- **Global install** — everything symlinks to ~/.claude/, learning DB at ~/.claude/autodidact/learning.db
- **FTS5 for knowledge** — all learning queries go through SQLite FTS5 full-text search
- **Cost-ascending router** — /do resolves at cheapest tier possible (pattern → state → keyword → LLM)
- **5-section skills** — Identity, Orientation, Protocol, Quality Gates, Exit Protocol
- **HANDOFF blocks** — <150 words, 3-5 bullets between skills/agents
- **Document persistence** — research and plan outputs saved to `.planning/{research|plans}/`, auto-published to thoughts repo if `AUTODIDACT_THOUGHTS_REPO` is set
- **Research frontmatter** — research docs get YAML frontmatter (date, git_commit, branch, repository, topic, tags, status). Plans do NOT get frontmatter.

## Testing

```bash
python3 -m unittest discover -s tests -v
```

## Installing

```bash
python3 install.py          # Install globally
python3 install.py --uninstall  # Remove
```
