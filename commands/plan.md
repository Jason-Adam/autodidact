---
description: Unified planning — clarify requirements, research the codebase, and produce an implementation plan. Skips phases automatically when not needed.
model: opus
---

You are tasked with planning an implementation.

Load and follow the protocol in the autodidact-plan skill. The skill has three phases:

1. **Clarify** — Socratic questioning if requirements are ambiguous (skipped if clear)
2. **Research** — parallel codebase exploration if context is needed (skipped if sufficient)
3. **Design** — produce the implementation plan (always runs)

If the user provided arguments after `/plan`, treat those as the planning topic. Assess clarity and context to decide which phases to run.
