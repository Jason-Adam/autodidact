---
description: Research codebase comprehensively using parallel sub-agents and persist findings.
model: opus
---

You are tasked with conducting comprehensive research.

Load and follow the protocol in the autodidact-research skill.

If the user provided arguments after `/research`, treat those as the research question. Begin with Step 1 (reading any mentioned files) and proceed through the protocol.

If no arguments were provided, respond with:

```
I'm ready to research. What's your question or area of interest? I'll analyze it thoroughly by exploring relevant components and connections, then save a structured research document to `.planning/research/`.
```

Then wait for the user's research query.
