#!/usr/bin/env python3
"""Install autodidact globally to ~/.claude/.

Creates symlinks for hooks, skills, agents, and commands.
Patches ~/.claude/settings.json to register hook commands.
Initializes the learning database.

Usage:
    python3 install.py              # Install
    python3 install.py --uninstall  # Remove
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
CLAUDE_DIR = Path.home() / ".claude"
AUTODIDACT_DIR = CLAUDE_DIR / "autodidact"
INSTALLED_MARKER = AUTODIDACT_DIR / ".installed"

# Symlink mappings: (source_in_repo, target_in_claude, prefix)
SKILL_DIRS = [
    "do",
    "run",
    "campaign",
    "fleet",
    "learn",
    "plan",
    "review",
    "handoff",
    "publish",
    "loop",
]
AGENT_FILES = [
    "interviewer.md",
    "fleet-worker.md",
    "quality-scorer.md",
    "codebase-analyzer.md",
    "codebase-locator.md",
    "pattern-finder.md",
    "architecture-researcher.md",
    "web-researcher.md",
    "code-reviewer.md",
    "python-engineer.md",
]
COMMAND_FILES = [
    "do.md",
    "run.md",
    "campaign.md",
    "fleet.md",
    "learn.md",
    "learn_status.md",
    "forget.md",
    "plan.md",
    "review.md",
    "handoff.md",
    "publish.md",
    "loop.md",
]

HOOK_EVENTS = {
    "SessionStart": ["session_start.py"],
    "UserPromptSubmit": ["user_prompt_submit.py"],
    "PreToolUse": ["pre_tool_use.py"],
    "PostToolUse": ["post_tool_use.py"],
    "PreCompact": ["pre_compact.py"],
    "Stop": ["stop.py"],
    "SubagentStop": ["subagent_stop.py"],
    "TaskCompleted": ["task_completed.py"],
}


def _symlink(source: Path, target: Path) -> None:
    """Create a symlink, removing any existing one."""
    if target.is_symlink() or target.exists():
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(source)
    print(f"  -> {target.relative_to(CLAUDE_DIR)}")


def _backup_settings() -> Path | None:
    settings = CLAUDE_DIR / "settings.json"
    if settings.exists():
        backup = CLAUDE_DIR / "settings.json.autodidact-backup"
        shutil.copy2(settings, backup)
        return backup
    return None


def _patch_settings() -> None:
    """Merge autodidact hooks into ~/.claude/settings.json."""
    settings_path = CLAUDE_DIR / "settings.json"
    if settings_path.exists():
        with open(settings_path) as f:
            settings = json.load(f)
    else:
        settings = {}

    hooks = settings.get("hooks", {})
    hooks_dir = REPO_DIR / "hooks"

    for event, scripts in HOOK_EVENTS.items():
        event_hooks = hooks.get(event, [])
        for script in scripts:
            command = f"uv run --project {REPO_DIR} python3 {hooks_dir / script}"
            # Check if already registered (also match legacy python3-only commands)
            # Check if already registered (match in hooks array or legacy top-level command)
            already = any(
                # New format: hooks array
                any(
                    hk.get("command") == command
                    or hk.get("command") == f"python3 {hooks_dir / script}"
                    for hk in h.get("hooks", [])
                )
                # Legacy format: command at top level
                or h.get("command") == command
                or h.get("command") == f"python3 {hooks_dir / script}"
                for h in event_hooks
            )
            if not already:
                event_hooks.append(
                    {
                        "matcher": "",
                        "hooks": [{"type": "command", "command": command}],
                    }
                )
        hooks[event] = event_hooks

    settings["hooks"] = hooks
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    print(f"  -> Patched {settings_path.relative_to(Path.home())}")


def _unpatch_settings() -> None:
    """Remove autodidact hooks from ~/.claude/settings.json."""
    settings_path = CLAUDE_DIR / "settings.json"
    if not settings_path.exists():
        return

    with open(settings_path) as f:
        settings = json.load(f)

    hooks = settings.get("hooks", {})
    hooks_dir = REPO_DIR / "hooks"
    changed = False

    for event in list(hooks.keys()):
        original = hooks[event]

        def _is_autodidact_hook(h: dict) -> bool:
            # Legacy format: command at top level
            cmd = h.get("command", "")
            if cmd.startswith(f"python3 {hooks_dir}") or cmd.startswith(
                f"uv run --project {REPO_DIR}"
            ):
                return True
            # New format: check hooks array
            for hk in h.get("hooks", []):
                hk_cmd = hk.get("command", "")
                if hk_cmd.startswith(f"python3 {hooks_dir}") or hk_cmd.startswith(
                    f"uv run --project {REPO_DIR}"
                ):
                    return True
            return False

        filtered = [h for h in original if not _is_autodidact_hook(h)]
        if len(filtered) != len(original):
            changed = True
            if filtered:
                hooks[event] = filtered
            else:
                del hooks[event]

    if changed:
        settings["hooks"] = hooks
        with open(settings_path, "w") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")
        print(f"  -> Unpatched {settings_path.relative_to(Path.home())}")


def install() -> None:
    print("Installing autodidact...")

    # Backup settings
    backup = _backup_settings()
    if backup:
        print(f"  -> Backed up settings to {backup.name}")

    # Symlink src/ -> ~/.claude/autodidact/
    _symlink(REPO_DIR / "src", AUTODIDACT_DIR / "src")

    # Symlink skills
    for skill in SKILL_DIRS:
        source = REPO_DIR / "skills" / skill
        if source.exists():
            _symlink(source, CLAUDE_DIR / "skills" / f"autodidact-{skill}")

    # Symlink agents
    for agent in AGENT_FILES:
        source = REPO_DIR / "agents" / agent
        if source.exists():
            _symlink(source, CLAUDE_DIR / "agents" / f"autodidact-{agent}")

    # Symlink commands (no prefix — user-facing)
    for cmd in COMMAND_FILES:
        source = REPO_DIR / "commands" / cmd
        if source.exists():
            _symlink(source, CLAUDE_DIR / "commands" / cmd)

    # Patch settings.json with hook registrations
    _patch_settings()

    # Initialize learning DB
    sys.path.insert(0, str(REPO_DIR))
    from src.db import LearningDB

    db = LearningDB()
    db.close()
    print(f"  -> Initialized learning DB at {db.db_path}")

    # Write installed marker
    INSTALLED_MARKER.parent.mkdir(parents=True, exist_ok=True)
    INSTALLED_MARKER.write_text(
        json.dumps(
            {
                "version": "0.1.0",
                "installed_at": datetime.now(UTC).isoformat(),
                "repo_dir": str(REPO_DIR),
            },
            indent=2,
        )
    )
    print(f"  -> Wrote {INSTALLED_MARKER.relative_to(CLAUDE_DIR)}")

    print("\nAutodidact installed successfully.")


def uninstall() -> None:
    print("Uninstalling autodidact...")

    # Remove symlinks
    src_link = AUTODIDACT_DIR / "src"
    if src_link.is_symlink():
        src_link.unlink()

    for skill in SKILL_DIRS:
        target = CLAUDE_DIR / "skills" / f"autodidact-{skill}"
        if target.is_symlink():
            target.unlink()
            print(f"  -> Removed skills/autodidact-{skill}")

    for agent in AGENT_FILES:
        target = CLAUDE_DIR / "agents" / f"autodidact-{agent}"
        if target.is_symlink():
            target.unlink()
            print(f"  -> Removed agents/autodidact-{agent}")

    for cmd in COMMAND_FILES:
        target = CLAUDE_DIR / "commands" / cmd
        if target.is_symlink():
            target.unlink()
            print(f"  -> Removed commands/{cmd}")

    # Unpatch settings
    _unpatch_settings()

    # Remove installed marker (but keep learning.db)
    if INSTALLED_MARKER.exists():
        INSTALLED_MARKER.unlink()

    print("\nAutodidact uninstalled. Learning DB preserved at ~/.claude/autodidact/learning.db")


if __name__ == "__main__":
    if "--uninstall" in sys.argv:
        uninstall()
    else:
        install()
