#!/usr/bin/env python3
"""UserPromptSubmit hook: FTS5 knowledge injection on user prompts.

Fires on every user prompt. Queries the learning DB for relevant knowledge
and injects it as additional context. Non-blocking (exit 0).

Router dispatch (Tiers 0-2) is handled here; Tier 3 signals to the /do skill.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from src.confidence import INJECTION_MIN_CONFIDENCE
from src.db import LearningDB


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    prompt = hook_input.get("userMessage", "")
    session_id = hook_input.get("session_id") or hook_input.get("sessionId") or ""

    if not prompt or not prompt.strip():
        json.dump({}, sys.stdout)
        sys.exit(0)

    messages: list[str] = []

    try:
        db = LearningDB()

        # FTS5 query for relevant learnings
        learnings = db.query_fts(prompt, limit=5, min_confidence=INJECTION_MIN_CONFIDENCE)
        if learnings:
            lines = ["RELEVANT LEARNINGS:"]
            for entry in learnings:
                db.increment_access(entry["id"], session_id=session_id)
                lines.append(
                    f"  [{entry['topic']}/{entry['key']}] "
                    f"{entry['value']} (conf: {entry['confidence']:.2f})"
                )
            messages.append("\n".join(lines))

        db.close()
    except Exception:
        pass  # Graceful degradation

    output: dict = {}
    if messages:
        output["additionalContext"] = "\n\n".join(messages)

    json.dump(output, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
