#!/usr/bin/env python3
"""Stop hook: time-based confidence decay, git-status boost, session cleanup.

Fires when a Claude Code session ends. Non-blocking (exit 0).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from src.db import LearningDB

_STATE_DIR = Path.home() / ".claude" / "autodidact"
# Pending fix tracker written by post_tool_use.py
_PENDING_FIX_PATH = _STATE_DIR / "pending_fix.json"


def _cleanup_session_markers() -> None:
    """Remove temp marker files at session end."""
    import contextlib

    with contextlib.suppress(OSError):
        _PENDING_FIX_PATH.unlink(missing_ok=True)


def _session_modified_files(cwd: str) -> bool:
    """Check if any files were modified in the working directory."""
    if not cwd:
        return False
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd,
        )
        return bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return False


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

            # Lightweight boost if the session did meaningful work (file edits)
            cwd = hook_input.get("cwd", "")
            if cwd and _session_modified_files(cwd):
                for entry in accessed:
                    db.boost(entry["id"], amount=0.03)

        _cleanup_session_markers()
        db.close()
    except Exception:
        pass  # Graceful degradation

    json.dump({}, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
