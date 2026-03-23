---
description: Manage multi-session campaigns that persist across Claude Code invocations.
model: opus
---

You are tasked with managing a multi-session campaign.

Load and follow the protocol in the autodidact-archon skill.

- If an active campaign exists in `.planning/campaigns/`, offer to resume it
- If the user provided arguments, treat them as a new campaign to start
- Support `archon status`, `archon continue`, and `archon close` subcommands
