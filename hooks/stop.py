#!/usr/bin/env python3
"""Stop hook: time-based confidence decay, session summary.

Fires when a Claude Code session ends. Non-blocking (exit 0).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from src.db import LearningDB

_STATE_DIR = Path.home() / ".claude" / "autodidact"
# Marker file written by task_completed.py when a task succeeds
_TASK_SUCCESS_PATH = _STATE_DIR / "task_success.json"
# Pending fix tracker written by post_tool_use.py
_PENDING_FIX_PATH = _STATE_DIR / "pending_fix.json"


def _session_had_task_success(session_id: str) -> bool:
    """Check if any task completed successfully during this session."""
    if not _TASK_SUCCESS_PATH.exists():
        return False
    try:
        data = json.loads(_TASK_SUCCESS_PATH.read_text())
        return data.get("session_id") == session_id
    except (json.JSONDecodeError, OSError):
        return False


def _cleanup_session_markers() -> None:
    """Remove temp marker files at session end."""
    import contextlib

    for path in (_TASK_SUCCESS_PATH, _PENDING_FIX_PATH):
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    session_id = hook_input.get("session_id", "")

    try:
        db = LearningDB()

        # Apply time-based decay to all learnings accessed this session
        if session_id:
            accessed = db.get_accessed_in_session(session_id)
            learning_ids = [r["id"] for r in accessed]
            if learning_ids:
                db.time_decay(learning_ids)

            # If no task completed in this session, apply a soft decay
            # to learnings that were accessed (surfaced as context) but
            # didn't contribute to a successful outcome
            if not _session_had_task_success(session_id):
                accessed = db.get_accessed_in_session(session_id)
                for entry in accessed:
                    db.decay(entry["id"], amount=0.05)

        _cleanup_session_markers()
        db.close()
    except Exception:
        pass  # Graceful degradation

    json.dump({}, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
