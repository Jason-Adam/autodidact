"""Shared constants and helpers for Claude Code hook scripts."""

from __future__ import annotations

import re

# Tool name constants — keep in sync with Claude Code tool names.
TOOL_BASH = "Bash"
TOOL_EDIT = "Edit"
TOOL_SEND_MESSAGE = "SendMessage"
TOOL_WRITE = "Write"


def normalize_error(error_text: str) -> str:
    """Create a normalized signature from an error message.

    Strips linter file:line:col prefixes, absolute paths, line numbers,
    and dates so that the same error type on different lines produces
    an identical signature.
    """
    # Strip linter file:line:col: prefix BEFORE path normalization
    # Handles ruff ("file.py:42:5: CODE") and mypy ("file.py:174: error:")
    normalized = re.sub(
        r"^(\w+:\s)?[\w./\\-]+:\d+(?::\d+)?:\s*",
        r"\1",
        error_text,
        flags=re.MULTILINE,
    )
    # Remove absolute file paths, line numbers, and timestamps
    normalized = re.sub(r"/[\w/.-]+", "<PATH>", normalized)
    normalized = re.sub(r"line \d+", "line N", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\d{4}-\d{2}-\d{2}", "<DATE>", normalized)
    # Take first meaningful line
    for line in normalized.splitlines():
        line = line.strip()
        if line and not line.startswith(("Traceback", "File ", "  ")):
            return line[:200]
    return normalized[:200]
