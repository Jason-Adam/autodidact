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
6. **Convergence overrides** (optional) — custom thresholds for convergence detection. If provided, pass to `ConvergenceThresholds`. Available overrides:
   - `plateau_threshold` (float, default 0.02) — minimum improvement to avoid plateau signal
   - `plateau_window` (int, default 2) — consecutive keeps to evaluate
   - `max_consecutive_discards` (int, default 3) — discard streak before convergence
   - `alternating_window` (int, default 8) — last N entries for oscillation check
   - `alternating_ratio` (float, default 0.85) — oscillation detection threshold
   - `code_repetition_window` (int, default 10) — entry window for file-touch frequency check
   - `code_repetition_threshold` (int, default 4) — same file touched N+ times in window
   - `max_consecutive_interesting` (int, default 3) — interesting streak before convergence
   - `max_consecutive_thoughts` (int, default 3) — thought streak before convergence
   - `max_consecutive_timeouts` (int, default 2) — timeout streak before convergence

### Phase 1b: Resume (optional)

If a previous experiment exists at `.planning/experiments/{id}/state.json` with status `in_progress`:
1. Load existing state via `ExperimentLog.load()`
2. Verify safety branch still exists
3. Display summary of progress so far (entries recorded, best metric, last experiment number)
4. Ask user whether to resume or start fresh
5. If resuming, skip to Phase 3 (Loop) starting from `last_experiment_num + 1`
6. If starting fresh, proceed normally from Phase 1 Interview

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
- Convergence signal detected (plateau, consecutive discards, alternating, code repetition, timeout streak, consecutive interesting, consecutive thoughts)
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
