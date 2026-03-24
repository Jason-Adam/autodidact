---
description: Start, monitor, or stop the autonomous execution loop.
model: sonnet
---

You are tasked with managing the autonomous loop.

Load and follow the protocol in the autodidact-loop skill.

Arguments: $ARGUMENTS

Parse the arguments to determine the subcommand:
- `/loop` or `/loop run` — start the loop in run mode
- `/loop campaign` — start the loop in campaign mode
- `/loop fleet` — start the loop in fleet mode
- `/loop status` — show current loop status
- `/loop stop` — stop the loop gracefully
- `/loop --max N` — set max iterations (works with any mode)
