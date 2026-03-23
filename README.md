# autodidact

A self-teaching AI harness for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) that grows smarter through use.

Autodidact is a collection of skills, hooks, agents, and a SQLite-backed learning database that gives Claude Code structured orchestration, persistent memory, and the ability to learn from its own mistakes.

## What it does

- **Learns from errors** — captures error patterns, remembers fixes, and injects relevant knowledge into future sessions via FTS5 full-text search
- **Plans before it builds** — a unified `/plan` pipeline that clarifies requirements (Socratic interview), researches the codebase (parallel agents), and produces implementation plans
- **Orchestrates complex work** — three tiers of orchestration: `/run` (single-session), `/campaign` (multi-session), `/fleet` (parallel git worktrees)
- **Routes cheaply** — a cost-ascending `/do` router resolves most requests with zero LLM tokens (pattern match → active state → keyword heuristic) before falling back to classification
- **Checks quality per-edit** — hooks run ruff/mypy on Python files and eslint on JavaScript files after every edit, feeding results back into the learning DB

## Architecture

```
/do (router)
  ├── Tier 0: pattern match (zero cost)
  ├── Tier 1: active state check (zero cost)
  ├── Tier 2: keyword heuristic (low cost)
  └── Tier 3: LLM classification (skill handles it)
        │
        ├── /plan ─── Clarify → Research → Design
        ├── /run ───── single-session multi-step
        ├── /campaign  multi-session campaigns
        ├── /fleet ─── parallel worktree waves
        ├── /review ── code review with quality scoring
        ├── /learn ─── teach autodidact something
        ├── /handoff ─ session transfer document
        └── /publish ─ auto-publish to thoughts repo
```

### Components

| Layer | Count | Description |
|-------|-------|-------------|
| **Core library** | 10 modules | `src/` — db, router, confidence, interview, worktree, circuit_breaker, handoff, sync, documents |
| **Hooks** | 8 | Python scripts on Claude Code lifecycle events (session start, tool use, compaction, stop) |
| **Skills** | 9 | Markdown protocols with 5-section format (Identity, Orientation, Protocol, Quality Gates, Exit) |
| **Agents** | 10 | Specialized personas: interviewer, fleet-worker, quality-scorer, 6 research agents, python-engineer |
| **Commands** | 11 | User-facing slash commands that invoke skills |

### Learning database

SQLite with FTS5 full-text search. Knowledge flows through a lifecycle:

```
Record (hooks capture errors/patterns)
  → Inject (FTS5 query on every user prompt)
  → Feedback (success: +0.15 confidence, failure: -0.10)
  → Decay (time-based: 0.01/day, floor 0.1)
  → Graduate (confidence ≥ 0.9 + 5 observations → promoted to CLAUDE.md)
  → Prune (confidence < 0.1 + 90 days stale → deleted)
```

### Document persistence

Research findings and implementation plans are saved as structured markdown in the current project:

```
.planning/
├── research/    # Research docs with YAML frontmatter (date, git_commit, topic, tags)
└── plans/       # Plan docs (flat markdown, no frontmatter)
```

If `AUTODIDACT_THOUGHTS_REPO` is set, documents are also auto-published to a GitHub thoughts repo via `/publish` (worktree → PR → squash merge). Research docs are deleted locally after publish; plans are kept for implementation tracking.

## Prerequisites

| Tool | Required | Purpose |
|------|----------|---------|
| [Python 3.11+](https://www.python.org/) | Yes | Runtime for hooks and core library |
| [uv](https://docs.astral.sh/uv/) | Yes | Package/project management; hooks run through `uv run` |
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | Yes | The AI coding tool this harness extends |
| [git](https://git-scm.com/) | Yes | Version control, worktree isolation for fleet |
| [gh](https://cli.github.com/) | For `/publish` | GitHub CLI for auto-publishing to thoughts repo |
| [ruff](https://docs.astral.sh/ruff/) | For quality checks | Linting/formatting Python files on every edit |
| [mypy](https://mypy-lang.org/) | Optional | Type checking Python files (runs if project has mypy config) |

`ruff` and `mypy` are installed as dev dependencies via `uv sync` — no separate install needed.

## Installation

```bash
git clone https://github.com/Jason-Adam/autodidact.git
cd autodidact
uv sync                       # install dependencies and create .venv
uv run pre-commit install     # set up pre-commit hooks (ruff lint, ruff format, mypy)
uv run python3 install.py     # install globally to ~/.claude/
```

This will:
1. Symlink skills, agents, and commands into `~/.claude/`
2. Register 8 hooks in `~/.claude/settings.json` (hooks run via `uv run` so they have access to project dependencies)
3. Initialize the learning database at `~/.claude/autodidact/learning.db`

Every commit will automatically run ruff lint, ruff format, and mypy strict via pre-commit.

To uninstall:

```bash
python3 install.py --uninstall
```

The learning database is preserved on uninstall. Delete `~/.claude/autodidact/` manually to remove it.

### Optional: thoughts repo publishing

To auto-publish research and plans to a GitHub repository:

```bash
export AUTODIDACT_THOUGHTS_REPO=your-org/your-thoughts-repo
```

The repo will be cloned automatically on first publish. Requires the `gh` CLI to be authenticated.

## Usage

### `/do` — the universal entry point

Route any request through the autodidact system:

```
/do add pagination to the API
/do clarify the requirements for the auth refactor
/do review the changes I just made
```

The router resolves at the cheapest tier possible. Most requests never need an LLM call.

### `/plan` — clarify, research, design

The unified planning pipeline. It automatically decides which phases to run:

```
/plan add rate limiting to the API
```

If requirements are vague, it enters the **Clarify** phase and asks Socratic questions. If the codebase is unfamiliar, it spawns parallel **Research** agents. Then it produces an implementation plan with phases and success criteria.

### `/run` — single-session orchestration

For multi-step tasks that fit in one session:

```
/run refactor the database layer to use connection pooling
```

Decomposes into phases, executes sequentially, verifies each phase, and advances. Circuit breaker halts after 3 consecutive failures.

### `/campaign` — multi-session campaigns

For work that spans multiple Claude Code sessions:

```
/campaign migrate from REST to GraphQL
```

Persists campaign state in `.planning/campaigns/`. The session-start hook detects active campaigns and offers to resume them.

### `/fleet` — parallel worktree execution

For tasks that can be parallelized across independent code areas:

```
/fleet add type hints to src/db.py, src/router.py, and src/interview.py
```

Creates isolated git worktrees, dispatches workers in parallel, compresses discovery briefs between waves, and merges results.

### `/learn` — teach the system

Explicitly teach autodidact something:

```
/learn pytest fixtures in this project always go in conftest.py
/learn our API responses always use snake_case keys
```

User-taught knowledge starts at 0.7 confidence and is injected into future sessions when relevant.

### `/learn_status` — check what it knows

```
/learn_status
```

Shows total learnings, average confidence, graduation candidates, and routing gaps.

### `/review` — code review

```
/review
```

Reviews changed files with quality scoring across correctness, security, completeness, and style. Scores feed back into the learning DB.

### `/handoff` — session transfer

```
/handoff
```

Creates a compact (<150 words) transfer document capturing what was done, decisions made, and next steps.

### `/publish` — publish to thoughts repo

```
/publish .planning/research/2026-03-24-auth-flow.md
```

Publishes a research or plan document to the GitHub thoughts repo configured via `AUTODIDACT_THOUGHTS_REPO`. Creates a worktree, commits, opens a PR, squash merges, and cleans up. Research docs are deleted locally after publish; plans are kept.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

82 tests covering the learning DB, confidence math, router classification, interview scoring, and circuit breaker.

## Design principles

- **Python stdlib only** — no pip installs, no virtual environments, no dependency management
- **Global installation** — one install serves all projects; learning persists across repos
- **Cost-ascending routing** — resolve at the cheapest tier; most requests cost zero LLM tokens
- **Graceful degradation** — all hooks catch errors and exit 0; a broken hook never blocks your work
- **Confidence-based knowledge** — learnings earn trust through repeated successful use, not just existence

## License

MIT
