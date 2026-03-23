---
description: Execute tasks in parallel using isolated git worktrees.
---

You are tasked with parallel execution using fleet.

Load and follow the protocol in the autodidact-fleet skill. Decompose the task into independent units, create worktrees, dispatch workers, collect discovery briefs, and merge results.

If the user provided arguments after `/fleet`, treat those as the task to parallelize.

Important: Verify the git working tree is clean before creating worktrees. Stash or commit uncommitted changes first.
