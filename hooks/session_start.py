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

from src.confidence import INJECTION_MIN_CONFIDENCE
from src.db import LearningDB
from src.git_utils import resolve_main_repo
from src.graduate import graduate_to_memory
from src.rtk_integration import (
    feed_discover_to_db,
    get_rtk_savings_summary,
    is_rtk_installed,
)
from src.session_miner import mine_and_record


def _should_run_weekly(marker_path: Path, today: str) -> bool:
    """Check if a weekly-throttled task should run based on its marker file."""
    try:
        last_run = marker_path.read_text().strip()
        today_date = datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=UTC)
        last_date = datetime.strptime(last_run, "%Y-%m-%d").replace(tzinfo=UTC)
        return (today_date - last_date) >= timedelta(days=7)
    except (OSError, ValueError):
        return True


def _stamp_weekly(marker_path: Path, today: str) -> None:
    """Write today's date to a weekly throttle marker file."""
    with contextlib.suppress(OSError):
        marker_path.write_text(today)


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    messages: list[str] = []
    cwd = hook_input.get("cwd", "")
    session_id = hook_input.get("session_id") or hook_input.get("sessionId") or ""
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

        # Auto-graduate eligible learnings to memory system (daily, alongside pruning)
        # Wrapped in its own try/except so a filesystem error can't disable
        # the rest of the hook (injection, campaign detection, etc.)
        if should_prune:
            try:
                candidates = db.get_graduation_candidates()
                if candidates and project_path:
                    results = graduate_to_memory(candidates, project_path)
                    graduated_keys = []
                    for result in results:
                        if db.graduate(result["id"], result["memory_path"]):
                            graduated_keys.append(result["key"])
                    if graduated_keys:
                        max_listed = 5
                        listed = graduated_keys[:max_listed]
                        remaining = len(graduated_keys) - len(listed)
                        keys_str = ", ".join(listed)
                        msg = f"Graduated {len(graduated_keys)} learning(s) to memory: {keys_str}"
                        if remaining > 0:
                            msg += f" (and {remaining} more)"
                        messages.append(msg)
            except Exception:
                pass  # Graceful degradation — don't block other hook behavior

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
        rtk_marker = Path(db.db_path).parent / ".last_rtk_discover"
        if _should_run_weekly(rtk_marker, today):
            recorded = feed_discover_to_db(project_path, db)
            if recorded > 0:
                messages.append(
                    f"RTK discover: {recorded} optimization tips recorded to learning DB"
                )
            _stamp_weekly(rtk_marker, today)

        # Session mining -> learning DB (weekly)
        mine_marker = Path(db.db_path).parent / ".last_session_mine"
        if _should_run_weekly(mine_marker, today) and project_path:
            try:
                mine_result = mine_and_record(project_path, db)
                if mine_result.get("learnings_recorded", 0) > 0:
                    messages.append(
                        f"Session mining: {mine_result['learnings_recorded']} error patterns "
                        f"from {mine_result['sessions_scanned']} sessions"
                    )
                _stamp_weekly(mine_marker, today)
            except Exception:
                pass  # Graceful degradation — don't stamp marker on failure

        # Inject progressive learnings for current project
        # Derive topic hint from project directory name for FTS relevance
        topic_hint = Path(project_path).name if project_path else ""
        learnings = db.get_progressive_learnings(
            token_budget=2000,
            project_path=project_path,
            topic_hint=topic_hint,
            min_confidence=INJECTION_MIN_CONFIDENCE,
        )

        core = learnings.get("core", [])
        relevant = learnings.get("relevant", [])

        if core or relevant:
            lines = []
            if core:
                lines.append("AUTODIDACT LEARNINGS (high confidence):")
                for entry in core:
                    db.increment_access(entry["id"], session_id=session_id)
                    lines.append(
                        f"  [{entry['topic']}/{entry['key']}] "
                        f"{entry['value']} (conf: {entry['confidence']:.2f})"
                    )
            if relevant:
                lines.append("\nPOSSIBLY RELEVANT:")
                for entry in relevant:
                    db.increment_access(entry["id"], session_id=session_id)
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
