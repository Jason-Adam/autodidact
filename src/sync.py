"""Post-pull sync: verify symlinks, run DB migrations, update hook registrations.

Usage: python3 -m src.sync
"""

from __future__ import annotations

import json
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
AUTODIDACT_DIR = CLAUDE_DIR / "autodidact"
INSTALLED_MARKER = AUTODIDACT_DIR / ".installed"


def check_installation() -> dict[str, bool]:
    """Verify the autodidact installation is intact."""
    issues: dict[str, bool] = {}

    if not INSTALLED_MARKER.exists():
        issues["not_installed"] = True
        return issues

    marker = json.loads(INSTALLED_MARKER.read_text())
    repo_dir = Path(marker.get("repo_dir", ""))

    if not repo_dir.exists():
        issues["repo_missing"] = True
        return issues

    # Check src symlink
    src_link = AUTODIDACT_DIR / "src"
    if not src_link.is_symlink():
        issues["src_symlink_broken"] = True

    # Check settings.json has hooks
    settings_path = CLAUDE_DIR / "settings.json"
    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
        hooks = settings.get("hooks", {})
        hooks_dir = repo_dir / "hooks"
        for event in ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"]:
            event_hooks = hooks.get(event, [])
            has_autodidact = any(
                str(hooks_dir) in h.get("command", "")
                for h in event_hooks
            )
            if not has_autodidact:
                issues[f"hook_missing_{event}"] = True

    return issues


def sync() -> None:
    """Run sync: check installation, fix issues, migrate DB."""
    issues = check_installation()

    if issues.get("not_installed"):
        print("Autodidact not installed. Run: python3 install.py")
        return

    if issues.get("repo_missing"):
        print("Autodidact repo directory not found. Reinstall needed.")
        return

    if any(k.startswith("hook_missing_") for k in issues):
        print("Some hooks are missing from settings.json. Re-running install...")
        # Import and re-patch
        import importlib
        install_mod = importlib.import_module("install")
        install_mod._patch_settings()

    if issues.get("src_symlink_broken"):
        print("Source symlink broken. Re-running install...")
        import importlib
        install_mod = importlib.import_module("install")
        install_mod.install()
        return

    # Run DB migrations
    from src.db import LearningDB
    db = LearningDB()
    db.close()
    print("Sync complete. All good.")


if __name__ == "__main__":
    sync()
