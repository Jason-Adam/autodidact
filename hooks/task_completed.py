#!/usr/bin/env python3
"""TaskCompleted hook: learning feedback on task completion.

Fires when a task completes. Non-blocking (exit 0).
Boosts confidence of learnings that were accessed during the session.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from src.db import LearningDB


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    session_id = hook_input.get("session_id", "")

    try:
        db = LearningDB()

        # Boost learnings that were accessed (injected) during this session
        # (they were presumably helpful if the task completed successfully)
        if session_id:
            accessed = db.get_accessed_in_session(session_id)
            for row in accessed:
                db.boost(row["id"], amount=0.05)
                db.set_outcome(row["id"], "success")

        db.close()
    except Exception:
        pass  # Graceful degradation

    json.dump({}, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
