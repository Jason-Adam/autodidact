# Clarify Protocol

Shared Socratic interview protocol used by skills that include a Clarify phase. Each skill defines its own exit criteria and calibration rules; this template covers the common mechanics.

## Interviewer Mechanics

1. Spawn the `autodidact-interviewer` agent using the Agent tool with a prompt that includes the user's request and any codebase context gathered so far. Give the agent a `name` (e.g., `"interviewer"`) so you can continue the conversation.
2. When the interviewer returns a question, present it to the user.
3. When the user answers, relay their answer back to the interviewer via `SendMessage`. **You MUST include a `summary` parameter** — this is a platform requirement when `message` is a string. The summary should condense the interview state so far.
4. Repeat until exit criteria are met (defined by the calling skill).

> **SendMessage contract**: Every `SendMessage` call to the interviewer MUST include `summary` (string). Omitting it when `message` is a string causes `Error: summary is required when message is a string`. Example:
> ```
> SendMessage(to: "interviewer", message: "User's answer here...", summary: "Round 2. User confirmed scope to token refresh flow.")
> ```

## Brownfield Awareness

When codebase context is available, include specific files/patterns in the initial agent prompt so the interviewer asks CONFIRMATION questions, not open-ended discovery.
- GOOD: "I see JWT middleware in `src/auth/`. Should the new feature use this?"
- BAD: "Do you have any authentication set up?"

## No Escape Hatch

The Clarify phase is mandatory. Even well-scoped requests benefit from Socratic questioning — it surfaces blind spots, identifies low-information areas, and sharpens constraints. The interview runs until exit criteria are met (ambiguity <= 0.2 or maximum rounds exhausted). There is no skip mechanism.
