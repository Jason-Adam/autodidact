---
description: Run an autonomous optimization experiment loop.
model: opus
---

Load and follow the experiment skill protocol at `skills/experiment/skill.md`.

Begin with the Interview phase to collect:
- Target files to optimize
- Metric command (must output a single number to stdout)
- Time budget per experiment (default: 120s)
- Total session budget (default: 3600s)
- Direction: minimize or maximize

Then proceed through Baseline → Loop → Report.
