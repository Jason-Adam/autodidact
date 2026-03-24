# Command Reference

## `/do` — universal entry point

```
/do add pagination to the API
```

Routes through the cost-ascending classifier (pattern match -> active state -> keyword heuristic -> LLM). Most requests resolve with zero LLM tokens.

## `/plan` — clarify, research, design

```
/plan add rate limiting to the API
```

Automatically decides which phases to run: Socratic **Clarify** if requirements are vague, parallel **Research** agents if the codebase is unfamiliar, then **Design** with phases and success criteria.

## `/run` — single-session orchestration

```
/run refactor the database layer to use connection pooling
```

Decomposes into phases, executes sequentially, verifies each. Circuit breaker halts after 3 consecutive failures.

## `/campaign` — multi-session campaigns

```
/campaign migrate from REST to GraphQL
```

Persists state in `.planning/campaigns/`. The session-start hook detects active campaigns and prompts to resume.

## `/fleet` — parallel worktree execution

```
/fleet add type hints to src/db.py, src/router.py, and src/interview.py
```

Creates isolated git worktrees, dispatches workers in waves, compresses discovery briefs between waves, and merges results. Recovers interrupted workers automatically on resume.

## `/experiment` — metric-driven optimization

```
/experiment optimize the hot loop in src/parser.py for throughput
```

Runs an autonomous THINK -> TEST -> REFLECT loop. You provide target files, a metric command (any shell command that outputs a number), and an optimization direction (minimize/maximize). Claude hypothesizes changes, measures their impact, keeps improvements, and reverts regressions — all on a `experiment/safety-{id}` git branch.

Convergence detection (plateau, oscillation, repeated failures) stops the loop when progress stalls. State persists in `.planning/experiments/` so interrupted sessions can resume.

## `/loop` — autonomous execution

See [loop.md](loop.md) for full details including exit detection, circuit breaker, and auto-select mode.

```
/loop run          # loop against the latest plan
/loop campaign     # loop continuing the active campaign
/loop fleet        # loop with parallel worktree execution
/loop              # auto-select mode based on plan structure
/loop status       # check loop progress
/loop stop         # graceful stop
```

## `/learn` — teach the system

```
/learn pytest fixtures in this project always go in conftest.py
```

User-taught knowledge starts at 0.7 confidence and is injected into future sessions when relevant.

## `/review`, `/handoff`, `/publish`

```
/review              # code review with quality scoring
/handoff             # compact session transfer document (<150 words)
/publish <file>      # publish to thoughts repo via PR
```
