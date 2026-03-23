#!/usr/bin/env python3
"""SessionStart hook: restore state, inject learnings, detect campaigns, prune DB.

Fires when a new Claude Code session starts. Non-blocking (exit 0).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add repo root to path for src imports
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from src.db import LearningDB


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    messages: list[str] = []
    cwd = hook_input.get("cwd", "")

    try:
        db = LearningDB()

        # Daily prune: check if we've pruned today
        prune_marker = db.db_path.parent / ".last_prune"
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        should_prune = True
        if prune_marker.exists():
            should_prune = prune_marker.read_text().strip() != today
        if should_prune:
            deleted = db.prune()
            prune_marker.write_text(today)
            if deleted > 0:
                messages.append(f"Pruned {deleted} stale learning(s).")

        # Inject top learnings for current project
        learnings = db.get_top_learnings(limit=10, project_path=cwd)
        if learnings:
            lines = ["AUTODIDACT LEARNINGS (top confidence):"]
            for l in learnings[:10]:
                lines.append(f"  [{l['topic']}/{l['key']}] {l['value']} (conf: {l['confidence']:.2f})")
            messages.append("\n".join(lines))

        # Check for active campaigns
        planning_dir = Path(cwd) / ".planning" / "campaigns" if cwd else None
        if planning_dir and planning_dir.exists():
            for campaign_file in planning_dir.glob("*.json"):
                try:
                    campaign = json.loads(campaign_file.read_text())
                    if campaign.get("status") == "in_progress":
                        name = campaign.get("name", campaign_file.stem)
                        messages.append(f"ACTIVE CAMPAIGN: {name} — use /archon to resume.")
                except (json.JSONDecodeError, KeyError):
                    pass

        # Restore compact state if present
        compact_state_path = Path(cwd) / ".planning" / "compact_state.json" if cwd else None
        if compact_state_path and compact_state_path.exists():
            try:
                state = json.loads(compact_state_path.read_text())
                if state:
                    messages.append(f"Restored session state from previous compaction.")
                    compact_state_path.unlink()
            except (json.JSONDecodeError, KeyError):
                pass

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
