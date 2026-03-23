#!/usr/bin/env python3
"""PreCompact hook: serialize session state before context compaction.

Saves active campaign progress, circuit breaker state, and session learnings
to .planning/compact_state.json for restoration on next session start.
Non-blocking (exit 0).
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

    cwd = hook_input.get("cwd", "")
    session_id = hook_input.get("session_id", "")

    if not cwd:
        json.dump({}, sys.stdout)
        sys.exit(0)

    try:
        compact_state: dict = {"session_id": session_id}

        # Capture active campaign state
        campaigns_dir = Path(cwd) / ".planning" / "campaigns"
        if campaigns_dir.exists():
            active = []
            for f in campaigns_dir.glob("*.json"):
                try:
                    campaign = json.loads(f.read_text())
                    if campaign.get("status") == "in_progress":
                        active.append(campaign.get("name", f.stem))
                except (json.JSONDecodeError, KeyError):
                    pass
            if active:
                compact_state["active_campaigns"] = active

        # Capture recent learnings from this session
        db = LearningDB()
        if session_id:
            rows = db.conn.execute(
                "SELECT id, topic, key, value, confidence "
                "FROM learnings WHERE session_id = ? LIMIT 20",
                (session_id,),
            ).fetchall()
            if rows:
                compact_state["session_learnings"] = [dict(r) for r in rows]
        db.close()

        # Write compact state
        planning_dir = Path(cwd) / ".planning"
        planning_dir.mkdir(parents=True, exist_ok=True)
        (planning_dir / "compact_state.json").write_text(json.dumps(compact_state, indent=2))
    except Exception:
        pass  # Graceful degradation

    json.dump({}, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
