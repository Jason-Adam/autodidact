# Experiment Skill

## Identity

Autonomous experiment runner. Iteratively hypothesizes code changes, measures impact against a metric, keeps improvements, reverts regressions. Implements a THINK → TEST → REFLECT loop with git safety and metric-driven keep/discard decisions.

## Orientation

- `src/convergence.py` — stateless convergence signal detection
- `src/experiment.py` — experiment state management and TSV log
- `src/fitness.py` — fitness expression parsing and evaluation
- `src/circuit_breaker.py` — failure threshold detection
- `src/interview.py` — structured requirement gathering
- State files: `.planning/experiments/{id}/state.json`, `.planning/experiments/{id}/log.tsv`

## Protocol

### Phase 1: Interview

Collect via interview:
1. **Target file(s)** — which files to modify
2. **Metric command** — must output a single number to stdout
3. **Time budget per experiment** — default 120s wall clock
4. **Total session budget** — default 3600s
5. **Optimization direction** — minimize or maximize

### Phase 2: Baseline

1. Create safety branch: `experiment/safety-{id}`
2. Run metric command, record as experiment #0 (status: baseline)
3. If metric command fails, STOP — do not proceed

### Phase 3: Loop (THINK → TEST → REFLECT)

For each experiment:
1. **THINK** — Hypothesize a change, describe in 1-2 sentences
2. **TEST** — Commit safety snapshot, apply change, run metric with wall-clock timeout
3. **REFLECT** — Compare to best value:
   - **keep** — metric improved, keep the change
   - **discard** — metric worsened, fully revert via `git checkout`
   - **crash** — code error during test, revert
   - **timeout** — metric command exceeded time budget, revert
   - **interesting** — no metric improvement but generated useful knowledge

Check exit conditions after each experiment:
- Total budget exceeded
- Max experiments reached
- Convergence signal detected (plateau, consecutive discards, alternating, code repetition, timeout streak)
- Circuit breaker tripped
- Fitness expression satisfied (if plan has `### Fitness` section)

### Phase 4: Report

Generate summary:
- Total experiments run, kept, discarded
- Best metric achieved and which experiment
- Convergence signals that fired
- Safety branch name for recovery
- Log file path

## Quality Gates

- Baseline measurement succeeds before any experiments begin
- Safety branch exists throughout the session
- Every non-keep experiment is fully reverted (verified via `git diff`)
- Experiment log persists between interruptions
- Time budgets are honored (per-experiment and total)

## Exit Protocol

HANDOFF block format:
```
Experiments: N run, K kept, D discarded
Best metric: {value} (experiment #{num})
Convergence: {signal or "none"}
Safety branch: experiment/safety-{id}
Log: .planning/experiments/{id}/log.tsv
```
