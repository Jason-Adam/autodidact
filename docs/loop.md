# Loop — Autonomous Execution

`/loop` drives any execution mode unattended with intelligent exit detection, progress tracking, and rate limit handling.

## How it works

```
/plan (interactive, you're present)
  |
  v  plan approved
/loop run|campaign|fleet (autonomous, you walk away)
  |
  |-- invoke claude CLI --> hooks fire automatically inside
  |-- analyze response --> question detection, status block parsing
  |-- detect progress ---> git diff, commits, file changes
  |-- update trackers --> circuit breaker (3-state) + exit tracker
  |-- check exit gates -> 6 priority levels (permission denied -> plan complete)
  '-- iterate or stop
```

The loop **wraps** existing skills — it doesn't reimplement them. Each iteration invokes Claude with the appropriate skill prompt, and the skill handles the actual work.

## Usage

```
/loop run          # loop against the latest plan
/loop campaign     # loop continuing the active campaign
/loop fleet        # loop with parallel worktree execution
/loop              # auto-select mode based on plan structure
/loop --max 20     # limit iterations
/loop status       # check loop progress
/loop stop         # graceful stop after current iteration
```

From the terminal directly (foreground mode):

```bash
uv run --project ~/code/autodidact python3 -m src.loop run --cwd .
```

## Auto-select mode

When invoked without an explicit mode (`/loop` or `/do loop`), the loop skill auto-selects using `select_loop_mode()` from `src/router.py`:

1. **Active state** — if a campaign, fleet, or run is already in progress, resume it
2. **Plan structure analysis** — reads the most recent plan in `.planning/plans/` and picks based on:
   - Independent phases (disjoint files) -> `fleet`
   - \>5 sequential phases -> `campaign`
   - 2-5 sequential phases -> `run`
   - 1 phase -> `run`
3. **Default** — `run`

## Exit detection

Checked in priority order:

1. **Permission denied** — immediate stop
2. **Test saturation** — 3+ test-only loops
3. **Repeated done signals** — 2+ explicit completions
4. **Safety backstop** — 5+ completion indicators
5. **Dual-condition gate** — 2+ indicators AND Claude's EXIT_SIGNAL
6. **Fitness gate** — all `### Fitness` expressions in the plan pass
7. **Plan complete** — all checkboxes checked

## Circuit breaker

Three states: `closed` -> `half_open` -> `open`.

- 3 iterations with no git progress -> opens
- 5 same-error iterations -> opens
- 2 permission denials -> opens
- Auto-recovers after 30-minute cooldown
