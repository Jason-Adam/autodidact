Campaign state file format (`.planning/campaigns/{slug}.json`):

```json
{
  "id": "uuid-string",
  "name": "Human-readable campaign name",
  "created": "2026-03-23T10:00:00Z",
  "status": "in_progress",
  "phases": [
    {
      "name": "Phase 1: Description",
      "status": "completed",
      "session_id": "session-uuid",
      "completed_at": "2026-03-23T12:00:00Z"
    },
    {
      "name": "Phase 2: Description",
      "status": "in_progress",
      "session_id": "current-session-uuid",
      "completed_at": null
    },
    {
      "name": "Phase 3: Description",
      "status": "pending",
      "session_id": "",
      "completed_at": null
    }
  ],
  "decision_log": [
    {
      "timestamp": "2026-03-23T11:30:00Z",
      "decision": "What was decided",
      "reasoning": "Why it was decided"
    }
  ],
  "learnings": [
    "Key discovery from Phase 1"
  ],
  "circuit_breaker": {
    "consecutive_failures": 0,
    "max_failures": 3
  }
}
```

Status values: `in_progress`, `completed`, `paused`, `aborted`
Phase status values: `pending`, `in_progress`, `completed`, `failed`, `skipped`
