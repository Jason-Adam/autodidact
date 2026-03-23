#!/usr/bin/env python3
"""PreToolUse hook: unified safety gate.

Blocks dangerous operations, protects critical files.
This is the ONLY blocking hook (exit 2 to block).
"""

from __future__ import annotations

import json
import re
import sys


# Protected file patterns (block writes)
PROTECTED_PATTERNS = [
    r"\.env$",
    r"\.env\.local$",
    r"credentials\.json$",
    r"\.claude/settings\.json$",
    r"\.git/",
]

# Dangerous shell commands (block execution)
DANGEROUS_COMMANDS = [
    r"rm\s+-rf\s+[/~]",        # rm -rf on root or home
    r"git\s+push\s+--force",    # force push
    r"git\s+reset\s+--hard",    # hard reset
    r"chmod\s+-R\s+777",        # world-writable
    r">\s*/dev/sd",             # write to block device
]


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
                json.dump({
                    "decision": "block",
                    "reason": f"Protected file: {file_path} matches {pattern}",
                }, sys.stdout)
                sys.exit(2)

    # Check dangerous commands on Bash
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        for pattern in DANGEROUS_COMMANDS:
            if re.search(pattern, command):
                json.dump({
                    "decision": "block",
                    "reason": f"Dangerous command blocked: matches {pattern}",
                }, sys.stdout)
                sys.exit(2)

    # Allow everything else
    json.dump({}, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
