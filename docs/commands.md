# Skill Reference

All skills are invoked through the `/do` router. This repo installs only the `/do` command and does not provide direct `/skill-name` slash commands by default.

## /do -- universal entry point

```
/do add pagination to the API
```

Routes through the cost-ascending classifier (pattern match -> active state -> keyword heuristic -> plan structure -> LLM). Most requests resolve with zero LLM tokens.

## research -- standalone codebase research

```
/do research how does the authentication flow work?
```

Runs a Socratic **Clarify** phase (calibrated by question specificity), then spawns parallel sub-agents to investigate, synthesizes findings, and persists a structured research document to `.planning/research/`. Use when you need to understand code without planning implementation.

## plan -- clarify, research, design

```
/do plan add rate limiting to the API
```

Automatically decides which phases to run: Socratic **Clarify** if requirements are vague, parallel **Research** agents if the codebase is unfamiliar, then **Design** with phases and success criteria.

## run -- single-session orchestration

```
/do run refactor the database layer to use connection pooling
```

Decomposes into phases, executes sequentially, verifies each. Circuit breaker halts after 3 consecutive failures.

## campaign -- multi-session campaigns

```
/do campaign migrate from REST to GraphQL
```

Persists state in `.planning/campaigns/`. The session-start hook detects active campaigns and prompts to resume.

## fleet -- parallel worktree execution

```
/do fleet add type hints to src/db.py, src/router.py, and src/interview.py
```

Creates isolated git worktrees, dispatches workers in waves, compresses discovery briefs between waves, and merges results. Recovers interrupted workers automatically on resume.

## experiment -- metric-driven optimization

```
/do experiment optimize the hot loop in src/parser.py for throughput
```

Runs an autonomous THINK -> TEST -> REFLECT loop. You provide target files, a metric command (any shell command that outputs a number), and an optimization direction (minimize/maximize). Claude hypothesizes changes, measures their impact, keeps improvements, and reverts regressions -- all on a `experiment/safety-{id}` git branch.

Convergence detection (plateau, oscillation, repeated failures) stops the loop when progress stalls. State persists in `.planning/experiments/` so interrupted sessions can resume.

## loop -- autonomous execution

See [loop.md](loop.md) for full details including exit detection, circuit breaker, and auto-select mode.

```
/do loop run          # loop against the latest plan
/do loop campaign     # loop continuing the active campaign
/do loop fleet        # loop with parallel worktree execution
/do loop              # auto-select mode based on plan structure
/do loop status       # check loop progress
/do loop stop         # graceful stop
```

## learn -- teach the system

```
/do learn pytest fixtures in this project always go in conftest.py
```

User-taught knowledge starts at 0.7 confidence and is injected into future sessions when relevant.

## polish -- parallel code quality

```
/do polish              # review + security scan + simplify on changed files
/do polish src/db.py    # polish specific files
```

Runs three agents in parallel (code-reviewer, security-reviewer, code-simplifier), deduplicates findings, auto-fixes issues, and records quality scores to the learning DB.

## forget -- decay learnings

```
/do forget pytest fixtures always go in conftest.py
```

Decays or removes specific learnings from the database. Useful when a prior teaching is no longer accurate.

## learn-status -- knowledge inventory

```
/do learn-status
```

Shows confidence stats and knowledge inventory from the learning database -- how many learnings exist, their confidence distribution, and recent activity.

## gc -- autonomous git commits

```
/do gc                  # commit current changes
/do commit these changes
```

Analyzes session changes, groups them into logical atomic commits, and creates them directly. Auto-branches from main/master if needed. Never asks for confirmation.

## create-pr -- create pull requests

```
/do pr                  # create a PR for the current branch
/do create a pull request
```

Analyzes the full branch diff, writes a thorough PR description, and creates the PR via `gh`. Respects the repository's existing PR template if one exists.

## handoff -- session transfer

```
/do handoff
```

Creates a compact session transfer document (<150 words) capturing decisions, open items, and next steps.

## sync-thoughts -- cross-project sync

```
/do sync-thoughts              # sync all docs from current project
/do sync-thoughts <file>       # sync a specific file
```

Copies research and plan documents to `~/.planning/` for cross-project access. Local `.planning/` files are always preserved.
