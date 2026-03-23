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


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    session_id = hook_input.get("session_id", "")

    try:
        db = LearningDB()

        # Apply time-based decay to all learnings touched this session
        if session_id:
            rows = db.conn.execute(
                "SELECT id FROM learnings WHERE session_id = ?",
                (session_id,),
            ).fetchall()
            learning_ids = [r["id"] for r in rows]
            if learning_ids:
                db.time_decay(learning_ids)

        db.close()
    except Exception:
        pass  # Graceful degradation

    json.dump({}, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
