#!/usr/bin/env python3
"""PreToolUse hook: unified safety gate.

Blocks dangerous operations, protects critical files.
This is the ONLY blocking hook (exit 2 to block).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

# Protected file patterns (block writes)
PROTECTED_PATTERNS = [
    r"\.env$",
    r"\.env\.local$",
    r"credentials\.json$",
    r"\.claude/settings\.json$",
    r"\.git/",
]

# Always-dangerous shell commands (blocked on any branch)
DANGEROUS_COMMANDS = [
    r"rm\s+-rf\s+[/~]",  # rm -rf on root or home
    r"chmod\s+-R\s+777",  # world-writable
    r">\s*/dev/sd",  # write to block device
]

# Dangerous only on default branch (allowed on feature branches)
DEFAULT_BRANCH_ONLY_COMMANDS = [
    r"git\s+push\s+--force",  # force push
    r"git\s+reset\s+--hard",  # hard reset
]


def _get_current_branch() -> str | None:
    """Return current git branch name, or None if not in a repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _get_default_branch() -> str:
    """Return the repo's default branch (main or master), defaulting to 'main'."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", "refs/remotes/origin/main"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return "main"
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", "refs/remotes/origin/master"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return "master"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return "main"


def _on_default_branch() -> bool:
    """Return True if the current branch is the default branch."""
    current = _get_current_branch()
    if current is None:
        return True  # fail safe: block if we can't determine
    return current == _get_default_branch()


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    # Check file protection on Edit/Write
    if tool_name in ("Edit", "Write"):
        file_path = tool_input.get("file_path", "")
        for pattern in PROTECTED_PATTERNS:
            if re.search(pattern, file_path):
                json.dump(
                    {
                        "decision": "block",
                        "reason": f"Protected file: {file_path} matches {pattern}",
                    },
                    sys.stdout,
                )
                sys.exit(2)

    # Check dangerous commands on Bash
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        for pattern in DANGEROUS_COMMANDS:
            if re.search(pattern, command):
                json.dump(
                    {
                        "decision": "block",
                        "reason": f"Dangerous command blocked: matches {pattern}",
                    },
                    sys.stdout,
                )
                sys.exit(2)
        # Block certain git commands only on the default branch
        for pattern in DEFAULT_BRANCH_ONLY_COMMANDS:
            if re.search(pattern, command) and _on_default_branch():
                json.dump(
                    {
                        "decision": "block",
                        "reason": f"Dangerous command blocked on default branch: matches {pattern}",
                    },
                    sys.stdout,
                )
                sys.exit(2)

    # Allow everything else
    json.dump({}, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
