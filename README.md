# autodidact

A self-teaching AI harness for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) that grows smarter through use.

Autodidact is a collection of skills, hooks, agents, and a SQLite-backed learning database that gives Claude Code structured orchestration, persistent memory, and the ability to learn from its own mistakes.

## What it does

- **Learns from errors** — captures error patterns, remembers fixes, and injects relevant knowledge into future sessions via FTS5 full-text search
- **Plans before it builds** — a unified `/plan` pipeline that clarifies requirements (Socratic interview), researches the codebase (parallel agents), and produces implementation plans
- **Orchestrates complex work** — three tiers of orchestration: `/run` (single-session), `/campaign` (multi-session), `/fleet` (parallel git worktrees)
- **Runs unattended** — `/loop` drives any execution mode autonomously with intelligent exit detection, progress tracking, and rate limit handling
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
         ┌──────────┬──────────┬───┴──────┬──────────┬──────────┐
         ▼          ▼          ▼          ▼          ▼          ▼
      /plan      /run     /campaign   /fleet     /review   /learn
    Clarify →   single     multi      parallel   quality   teach &
    Research →  session    session    worktree   scoring   query DB
    Design

         ┌──────────────────────────────────────────────────────┐
         │  /loop  (autonomous driver)                          │
         │  Wraps /run, /campaign, or /fleet in an unattended   │
         │  loop with exit detection + circuit breaker           │
         └──────────────────────────────────────────────────────┘
```

### How the loop works

```
/plan (interactive, you're present)
  │
  ▼  plan approved
/loop run|campaign|fleet (autonomous, you walk away)
  │
  ├── invoke claude CLI ──► hooks fire automatically inside
  ├── analyze response ──► question detection, status block parsing
  ├── detect progress ───► git diff, commits, file changes
  ├── update trackers ──► circuit breaker (3-state) + exit tracker
  ├── check exit gates ─► 6 priority levels (permission denied → plan complete)
  └── iterate or stop
```

The loop **wraps** existing skills — it doesn't reimplement them. Each iteration invokes Claude with the appropriate skill prompt, and the skill handles the actual work.

### Components

| Layer | Count | Description |
|-------|-------|-------------|
| **Core library** | 15 modules | `src/` — db, router, confidence, interview, worktree, circuit_breaker, handoff, sync, documents, git_utils, response_analyzer, progress, exit_tracker, loop |
| **Hooks** | 8 | Python scripts on Claude Code lifecycle events (session start, tool use, compaction, stop) |
| **Skills** | 10 | Markdown protocols with 5-section format (Identity, Orientation, Protocol, Quality Gates, Exit) |
| **Agents** | 10 | Specialized personas: interviewer, fleet-worker, quality-scorer, 6 research agents, python-engineer |
| **Commands** | 12 | User-facing slash commands that invoke skills |

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

```
.planning/
├── research/         # Research docs with YAML frontmatter
├── plans/            # Plan docs (flat markdown)
├── campaigns/        # Campaign state JSON
├── fleet/            # Fleet state (active.json)
├── loop_signals.json # Exit tracker state
├── loop_cb_state.json# Circuit breaker state
├── loop.pid          # Running loop PID
└── loop.log          # Loop output
```

If `AUTODIDACT_THOUGHTS_REPO` is set, documents are also auto-published to a GitHub thoughts repo via `/publish`.

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

### Optional: thoughts repo publishing

```bash
export AUTODIDACT_THOUGHTS_REPO=your-org/your-thoughts-repo
```

### Worktree compatibility

Autodidact works with `claude --worktree`. Learnings are shared across all worktrees of the same repo (resolved to the main repo root). `.planning/` state stays isolated per worktree, matching the one-worktree-per-task workflow.

## Usage

### `/do` — universal entry point

```
/do add pagination to the API
```

Routes through the cost-ascending classifier. Most requests resolve with zero LLM tokens.

### `/plan` — clarify, research, design

```
/plan add rate limiting to the API
```

Automatically decides which phases to run: Socratic **Clarify** if requirements are vague, parallel **Research** agents if the codebase is unfamiliar, then **Design** with phases and success criteria.

### `/run` — single-session orchestration

```
/run refactor the database layer to use connection pooling
```

Decomposes into phases, executes sequentially, verifies each. Circuit breaker halts after 3 consecutive failures.

### `/campaign` — multi-session campaigns

```
/campaign migrate from REST to GraphQL
```

Persists state in `.planning/campaigns/`. The session-start hook detects active campaigns and prompts to resume.

### `/fleet` — parallel worktree execution

```
/fleet add type hints to src/db.py, src/router.py, and src/interview.py
```

Creates isolated git worktrees, dispatches workers in waves, compresses discovery briefs between waves, and merges results. Recovers interrupted workers automatically on resume.

### `/loop` — autonomous execution

Run any execution mode unattended:

```
/loop run          # loop against the latest plan
/loop campaign     # loop continuing the active campaign
/loop fleet        # loop with parallel worktree execution
/loop --max 20     # limit iterations
/loop status       # check loop progress
/loop stop         # graceful stop after current iteration
```

From the terminal directly (foreground mode):

```bash
uv run --project ~/code/autodidact python3 -m src.loop run --cwd .
```

**Exit detection** (checked in priority order):
1. Permission denied → immediate stop
2. Test saturation → 3+ test-only loops
3. Repeated done signals → 2+ explicit completions
4. Safety backstop → 5+ completion indicators
5. Dual-condition gate → 2+ indicators AND Claude's EXIT_SIGNAL
6. Plan complete → all checkboxes checked

**Circuit breaker** (3-state: closed → half_open → open):
- 3 iterations with no git progress → opens
- 5 same-error iterations → opens
- 2 permission denials → opens
- Auto-recovers after 30-minute cooldown

### `/learn` — teach the system

```
/learn pytest fixtures in this project always go in conftest.py
```

User-taught knowledge starts at 0.7 confidence and is injected into future sessions when relevant.

### `/review`, `/handoff`, `/publish`

```
/review              # code review with quality scoring
/handoff             # compact session transfer document (<150 words)
/publish <file>      # publish to thoughts repo via PR
```

## Tests

```bash
uv run python3 -m pytest tests/ -v
```

185 tests covering the learning DB, confidence math, router classification, interview scoring, circuit breaker (2-state and 3-state), response analysis, git progress detection, exit tracking, loop orchestration, and fleet recovery.

## Design principles

- **Python stdlib only** — no pip installs in `src/` or `hooks/`
- **Global installation** — one install serves all projects; learning persists across repos
- **Cost-ascending routing** — resolve at the cheapest tier; most requests cost zero LLM tokens
- **Graceful degradation** — all hooks catch errors and exit 0; a broken hook never blocks your work
- **Confidence-based knowledge** — learnings earn trust through repeated successful use, not just existence
- **Worktree-aware** — learnings shared across worktrees; `.planning/` state isolated per task

## License

MIT
