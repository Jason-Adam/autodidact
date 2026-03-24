# autodidact

A self-teaching AI harness for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) that grows smarter through use.

Autodidact is a collection of skills, hooks, agents, and a SQLite-backed learning database that gives Claude Code structured orchestration, persistent memory, and the ability to learn from its own mistakes.

## What it does

- **Learns from errors** — captures error patterns, remembers fixes, and injects relevant knowledge into future sessions via FTS5 full-text search
- **Plans before it builds** — a unified `/plan` pipeline that clarifies requirements (Socratic interview), researches the codebase (parallel agents), and produces implementation plans
- **Orchestrates complex work** — three tiers of orchestration: `/run` (single-session), `/campaign` (multi-session), `/fleet` (parallel git worktrees)
- **Experiments autonomously** — `/experiment` runs a metric-driven THINK → TEST → REFLECT loop that hypothesizes changes, measures impact, keeps improvements, and reverts regressions
- **Runs unattended** — `/loop` drives any execution mode autonomously with intelligent exit detection, progress tracking, and [auto-selects the right orchestrator](docs/loop.md#auto-select-mode) based on plan structure
- **Routes cheaply** — a cost-ascending `/do` router resolves most requests with zero LLM tokens (pattern match → active state → keyword heuristic) before falling back to classification
- **Checks quality per-edit** — hooks run ruff/mypy on Python files and eslint on JavaScript files after every edit, feeding results back into the learning DB

## Architecture

```
                        ┌──────────────────────────────────┐
                        │  /do  (cost-ascending router)    │
                        │  T0: pattern → T1: state →       │
                        │  T2: keyword → T3: LLM           │
                        └──────────┬───────────────────────┘
                                   │
         ┌──────────┬──────────┬───┴──────┬──────────┬──────────┬──────────┐
         ▼          ▼          ▼          ▼          ▼          ▼          ▼
      /plan      /run     /campaign   /fleet   /experiment /review   /learn
    Clarify →   single     multi      parallel   metric    quality   teach &
    Research →  session    session    worktree   driven    scoring   query DB
    Design                                       optimize

         ┌──────────────────────────────────────────────────────┐
         │  /loop  (autonomous driver)                          │
         │  Wraps /run, /campaign, or /fleet in an unattended   │
         │  loop with exit detection + circuit breaker          │
         │  Auto-selects mode from plan structure when omitted  │
         └──────────────────────────────────────────────────────┘
```

### Components

| Layer | Count | Description |
|-------|-------|-------------|
| **Core library** | 18 modules | `src/` — db, router, confidence, interview, worktree, circuit_breaker, handoff, sync, documents, git_utils, response_analyzer, progress, exit_tracker, loop, experiment, convergence, fitness |
| **Hooks** | 8 | Python scripts on Claude Code lifecycle events (session start, tool use, compaction, stop) |
| **Skills** | 11 | Markdown protocols with 5-section format (Identity, Orientation, Protocol, Quality Gates, Exit) |
| **Agents** | 10 | Specialized personas: interviewer, fleet-worker, quality-scorer, 6 research agents, python-engineer |
| **Commands** | 13 | User-facing slash commands that invoke skills |

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

To uninstall:

```bash
python3 install.py --uninstall
```

The learning database is preserved on uninstall. Delete `~/.claude/autodidact/` manually to remove it.

## Usage

| Command | Purpose | Docs |
|---------|---------|------|
| `/do` | Universal router — resolves most requests at zero LLM cost | — |
| `/plan` | Clarify → Research → Design pipeline | [commands.md](docs/commands.md#plan--clarify-research-design) |
| `/run` | Single-session sequential orchestration | [commands.md](docs/commands.md#run--single-session-orchestration) |
| `/campaign` | Multi-session persistent orchestration | [commands.md](docs/commands.md#campaign--multi-session-campaigns) |
| `/fleet` | Parallel worktree execution | [commands.md](docs/commands.md#fleet--parallel-worktree-execution) |
| `/experiment` | Metric-driven autonomous optimization | [commands.md](docs/commands.md#experiment--metric-driven-optimization) |
| `/loop` | Autonomous unattended execution (auto-selects mode) | [loop.md](docs/loop.md) |
| `/learn` | Teach the system facts for future injection | [commands.md](docs/commands.md#learn--teach-the-system) |
| `/review` | Code review with quality scoring | [commands.md](docs/commands.md#review-handoff-publish) |
| `/handoff` | Compact session transfer document | [commands.md](docs/commands.md#review-handoff-publish) |
| `/publish` | Publish docs to thoughts repo via PR | [commands.md](docs/commands.md#review-handoff-publish) |

## Deep dives

- [Command reference](docs/commands.md) — detailed usage and examples for every command
- [Loop and autonomous execution](docs/loop.md) — exit detection, circuit breaker, auto-select mode
- [Learning database](docs/learning-db.md) — knowledge lifecycle, confidence math, FTS5 queries
- [Planning and persistence](docs/planning.md) — `.planning/` directory structure, thoughts repo publishing

## Tests

```bash
uv run python3 -m pytest tests/ -v
```

227 tests covering the learning DB, confidence math, router classification, interview scoring, circuit breaker, response analysis, git progress detection, exit tracking, loop orchestration, fleet recovery, experiment state management, convergence detection, and fitness expression evaluation.

## Design principles

- **Python stdlib only** — no pip installs in `src/` or `hooks/`
- **Global installation** — one install serves all projects; learning persists across repos
- **Cost-ascending routing** — resolve at the cheapest tier; most requests cost zero LLM tokens
- **Graceful degradation** — all hooks catch errors and exit 0; a broken hook never blocks your work
- **Confidence-based knowledge** — learnings earn trust through repeated successful use, not just existence
- **Worktree-aware** — learnings shared across worktrees; `.planning/` state isolated per task

## License

[MIT](LICENSE)
