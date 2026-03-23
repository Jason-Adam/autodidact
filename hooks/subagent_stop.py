#!/usr/bin/env python3
"""SubagentStop hook: compress discovery briefs, collect subagent learnings.

Fires when a subagent completes. Non-blocking (exit 0).
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
    cwd = hook_input.get("cwd", "")
    agent_output = hook_input.get("stdout", "")

    if not agent_output:
        json.dump({}, sys.stdout)
        sys.exit(0)

    try:
        db = LearningDB()

        # Extract and store any learnings from agent output
        # Agents can embed learnings as JSON blocks: <!-- LEARNING: {...} -->
        import re
        learning_pattern = re.compile(r"<!--\s*LEARNING:\s*({.*?})\s*-->", re.DOTALL)
        for match in learning_pattern.finditer(agent_output):
            try:
                learning = json.loads(match.group(1))
                db.record(
                    topic=learning.get("topic", "agent_discovery"),
                    key=learning.get("key", "unknown"),
                    value=learning.get("value", ""),
                    confidence=0.4,
                    source="subagent_discovery",
                    project_path=cwd,
                    session_id=session_id,
                )
            except (json.JSONDecodeError, KeyError):
                pass

        db.close()
    except Exception:
        pass  # Graceful degradation

    json.dump({}, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
