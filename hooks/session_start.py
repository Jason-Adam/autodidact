#!/usr/bin/env python3
"""SessionStart hook: restore state, inject learnings, detect campaigns, prune DB.

Fires when a new Claude Code session starts. Non-blocking (exit 0).
"""

from __future__ import annotations

import contextlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Add repo root to path for src imports
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from src.db import LearningDB
from src.git_utils import resolve_main_repo
from src.rtk_integration import (
    feed_discover_to_db,
    get_rtk_savings_summary,
    is_rtk_installed,
)


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    messages: list[str] = []
    cwd = hook_input.get("cwd", "")
    project_path = resolve_main_repo(cwd) if cwd else ""

    try:
        db = LearningDB()

        # Daily prune: check if we've pruned today
        prune_marker = db.db_path.parent / ".last_prune"
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        should_prune = True
        if prune_marker.exists():
            should_prune = prune_marker.read_text().strip() != today
        if should_prune:
            deleted = db.prune()
            prune_marker.write_text(today)
            if deleted > 0:
                messages.append(f"Pruned {deleted} stale learning(s).")

        # RTK token savings
        if is_rtk_installed():
            rtk_summary = get_rtk_savings_summary(project_path)
            if rtk_summary:
                total_cmds = rtk_summary.get("total_commands", 0)
                saved = rtk_summary.get("tokens_saved", 0)
                pct = rtk_summary.get("savings_percent", 0)
                messages.append(
                    f"RTK: {total_cmds} commands, {saved:,} tokens saved ({pct}%), last 7 days"
                )
        else:
            messages.append(
                "RTK saves 60-90% tokens on CLI output. "
                "Install: brew install patrickszmukowiak/tap/rtk"
            )

        # RTK discover -> learning DB (weekly)
        last_discover_path = Path(db.db_path).parent / ".last_rtk_discover"
        should_discover = True
        try:
            last_discover = last_discover_path.read_text().strip()
            last_date = datetime.strptime(last_discover, "%Y-%m-%d").replace(tzinfo=UTC)
            should_discover = (datetime.now(UTC) - last_date) >= timedelta(days=7)
        except (OSError, ValueError):
            pass
        if should_discover:
            recorded = feed_discover_to_db(project_path, db)
            if recorded > 0:
                messages.append(
                    f"RTK discover: {recorded} optimization tips recorded to learning DB"
                )
            with contextlib.suppress(OSError):
                last_discover_path.write_text(today)

        # Inject top learnings for current project
        learnings = db.get_top_learnings(limit=10, project_path=project_path)
        if learnings:
            lines = ["AUTODIDACT LEARNINGS (top confidence):"]
            for entry in learnings:
                db.increment_access(entry["id"])
                lines.append(
                    f"  [{entry['topic']}/{entry['key']}] "
                    f"{entry['value']} (conf: {entry['confidence']:.2f})"
                )
            messages.append("\n".join(lines))

        # Check for active campaigns
        planning_dir = Path(cwd) / ".planning" / "campaigns" if cwd else None
        if planning_dir and planning_dir.exists():
            for campaign_file in planning_dir.glob("*.json"):
                try:
                    campaign = json.loads(campaign_file.read_text())
                    if campaign.get("status") == "in_progress":
                        name = campaign.get("name", campaign_file.stem)
                        messages.append(f"ACTIVE CAMPAIGN: {name} — use /campaign to resume.")
                except (json.JSONDecodeError, KeyError):
                    pass

        # Restore compact state if present
        compact_state_path = Path(cwd) / ".planning" / "compact_state.json" if cwd else None
        if compact_state_path and compact_state_path.exists():
            try:
                state = json.loads(compact_state_path.read_text())
                if state:
                    messages.append("Restored session state from previous compaction.")
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
