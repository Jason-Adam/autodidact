---
description: Orchestrate a multi-step task within a single session.
model: opus
---

You are tasked with orchestrating a multi-step task.

Load and follow the protocol in the autodidact-marshal skill. Decompose the task into sequential phases, execute each with verification, and advance through them.

If the user provided arguments after `/marshal`, treat those as the task to orchestrate. If a marshal state exists in `.planning/marshal_state.json`, offer to resume it.
