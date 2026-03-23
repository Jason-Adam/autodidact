---
description: Universal entry point — classifies intent and routes to the right autodidact skill.
---

You are tasked with routing the user's request through the autodidact system.

Load and follow the protocol in the autodidact-do skill. The `/do` router classifies intent using a cost-ascending tier system (pattern match → active state → keyword → LLM) and dispatches to the appropriate skill.

If the user provided arguments after `/do`, treat those as the request to classify and route.

If no arguments were provided, ask the user what they'd like to do.
