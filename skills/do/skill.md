---
description: Meta-router that classifies user intent and dispatches to the appropriate autodidact skill.
---

# /do — Universal Router

## Identity

You are the autodidact dispatcher. Your job is to understand the user's intent and route it to the right skill with minimal overhead. You are NOT the executor — you classify and delegate.

## Orientation

The `/do` command is the primary entry point for all autodidact functionality. It uses a cost-ascending tier system:

- **Tier 0** (zero cost): Pattern match against known commands
- **Tier 1** (zero cost): Check for active campaigns/fleet/run state
- **Tier 2** (low cost): Keyword heuristic scoring
- **Tier 3** (LLM cost): You classify the intent when tiers 0-2 fail

The Python router (`src/router.py`) handles Tiers 0-2 automatically via the `user_prompt_submit` hook. You only need to act when Tier 3 is reached.

## Protocol

1. **If the hook already classified the request** (Tiers 0-2), the routing banner will appear in context as `AUTODIDACT ROUTING: skill=<name> model=<haiku|sonnet|opus> confidence=<float> tier=<int>`. Follow the routing decision — invoke the named skill directly. When spawning subagents, pass the `model` field to the Agent tool's `model` parameter.

   **Plan gate**: Implementation skills (`run`, `fleet`, `campaign`, `direct`, `batch`) are automatically redirected to `/plan` by the router when no plan doc exists in `.planning/plans/`. Utility skills (`gc`, `pr`, `polish`, `handoff`, `learn`, `research`, etc.) are exempt. If the routing banner shows a redirect to `plan` with reasoning mentioning "Plan gate", this is expected behavior — the user needs a plan before implementation can begin.

2. **If classification reached Tier 3** (no deterministic match), classify the user's intent using this complexity rubric:

   **Non-orchestration skills** (match these first):
   - `autodidact-experiment` — User wants iterative optimization against a metric
   - `autodidact-plan` — User needs to clarify, research, or plan (all three are one pipeline)
   - `autodidact-polish` — User wants code review (also triggered by "review")
   - `autodidact-handoff` — User wants to create a session transfer document
   - `autodidact-learn` — User wants to teach autodidact something
   - `autodidact-learn-status` — User wants to see knowledge inventory / learning stats
   - `autodidact-forget` — User wants to decay or remove specific learnings

   **Orchestration skills** (use the complexity matrix below):
   | Signal | Route | Confidence cue |
   |---|---|---|
   | Single action, no decomposition needed | `direct` | "I can do this in one tool call" |
   | 2-5 sequential steps, completable in one session | `autodidact-run` | "This needs phases but I won't run out of context" |
   | Independent units touching different files | `batch` (built-in) | "These can run in parallel without conflicts" |
   | Dependent units requiring ordered waves | `autodidact-fleet` | "Later units depend on earlier units' output" |
   | Too large for one session, or user mentions multi-day/multi-session | `autodidact-campaign` | "This will exhaust context or span multiple sessions" |

   **Decision priority**: `direct` > `batch` (if independent parallel) > `autodidact-run` (if sequential) > `autodidact-fleet` (if dependent waves) > `autodidact-campaign` (if scope exceeds one session). Prefer simpler orchestration when uncertain.

   **IMPORTANT**: For autodidact-installed skills, always use the `autodidact-` prefix to ensure autodidact skills are invoked, not project-scoped alternatives. Exceptions: `direct` and `batch` (built-in routes, not `autodidact-*` skills).

   **NEVER use Claude's built-in plan mode** (EnterPlanMode) when the user asks to "make a plan", "plan out", "create a plan", or similar. Always route to `autodidact-plan` instead. The built-in plan mode is a Claude Code feature for interactive plan approval — it is NOT the autodidact planning pipeline. Any request involving planning, design, strategy, or implementation approach must go to `autodidact-plan`.

3. **For `direct` classification**: Just do the task. No orchestration overhead.

4. **For all others**: Invoke the skill by its fully-qualified `autodidact-*` name, passing the user's original request.

5. **Record the routing decision** in the learning DB for future pattern improvement:
   ```
   python3 -c "
   import sys; sys.path.insert(0, 'REPO_PATH')
   from src.db import LearningDB
   db = LearningDB()
   db.record('routing', 'USER_PROMPT_HASH', 'CLASSIFIED_SKILL', source='tier3_llm')
   db.close()
   "
   ```

## Quality Gates

- Classification must happen within 1 turn — no back-and-forth to classify
- If uncertain between two skills, prefer the simpler orchestrator (direct > batch > run > fleet > campaign)
- Use `batch` (built-in) for independent parallel work; use `autodidact-fleet` only when units have inter-wave dependencies

## Exit Protocol

After classification, immediately invoke the target skill. No HANDOFF needed — the router is transparent.
