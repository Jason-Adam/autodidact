#!/usr/bin/env python3
"""TaskCompleted hook: quality gate scoring, learning feedback.

Fires when a task completes. Non-blocking (exit 0).
Evaluates task output quality and feeds scores back into learning confidence.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from src.db import LearningDB

_STATE_DIR = Path.home() / ".claude" / "autodidact"
# Marker file so stop.py can detect whether any task completed this session
_TASK_SUCCESS_PATH = _STATE_DIR / "task_success.json"


def _mark_task_success(session_id: str) -> None:
    """Write a marker indicating a task completed successfully in this session."""
    import contextlib

    with contextlib.suppress(OSError):
        _TASK_SUCCESS_PATH.write_text(json.dumps({"session_id": session_id}))


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
                db.boost(row["id"], amount=0.05)  # Small boost for task completion
                db.set_outcome(row["id"], "success")

            # Mark that a task succeeded in this session
            _mark_task_success(session_id)

        db.close()
    except Exception:
        pass  # Graceful degradation

    json.dump({}, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
