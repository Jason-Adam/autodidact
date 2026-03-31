#!/usr/bin/env python3
"""PostToolUse hook: per-edit quality checks and observation capture.

Fires after successful tool use. Non-blocking (exit 0).
Error learning is handled by post_tool_use_failure.py (PostToolUseFailure event).

Responsibilities:
1. Run language-aware quality checks after file edits (ruff, mypy, eslint)
2. Capture observations from bash command outputs
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

_HOOKS = Path(__file__).resolve().parent
_REPO = _HOOKS.parent
sys.path.insert(0, str(_HOOKS))
sys.path.insert(0, str(_REPO))

from constants import TOOL_BASH, TOOL_EDIT, TOOL_WRITE, normalize_error  # noqa: E402

from src.confidence import (
    OBSERVATION_INITIAL_CONFIDENCE,
)
from src.db import LearningDB
from src.git_utils import resolve_main_repo

# ── Observation Capture ──────────────────────────────────────────────────

_OBSERVATION_MIN_OUTPUT_LEN = 20
_OBSERVATION_MAX_VALUE_LEN = 300
_OBSERVATION_TOOLS = (TOOL_BASH,)

_SKIP_COMMAND_PREFIXES = (
    "cat ",
    "echo ",
    "ls ",
    "cd ",
    "pwd",
    "head ",
    "tail ",
    "wc ",
    "which ",
    "type ",
    "file ",
    "stat ",
)


def _extract_observation(
    tool_name: str,
    tool_input: dict,
    tool_output: str,
) -> dict | None:
    """Extract a condensed observation from a successful tool call.

    Returns {"key": str, "value": str, "tags": str} or None if not worth recording.
    """
    if tool_name != TOOL_BASH:
        return None

    command = tool_input.get("command", "")
    if not command:
        return None

    # Unwrap RTK proxy to get the real command for filtering/tagging
    cmd_stripped = command.lstrip()
    if cmd_stripped.startswith("rtk proxy "):
        cmd_stripped = cmd_stripped[len("rtk proxy ") :].lstrip()

    # Skip noisy read-only commands
    for prefix in _SKIP_COMMAND_PREFIXES:
        if cmd_stripped.startswith(prefix):
            return None

    # Condense output
    condensed = " ".join(tool_output.split())[:_OBSERVATION_MAX_VALUE_LEN]

    # Generate deterministic key from unwrapped command + output
    sig = hashlib.md5((cmd_stripped + condensed).encode(), usedforsecurity=False).hexdigest()[:12]
    key = f"obs_{sig}"

    # Tags: tool name + first word of unwrapped command
    parts = cmd_stripped.split()
    first_word = parts[0] if parts else "unknown"
    tags = f"bash {first_word}"

    # Value: original command + condensed result
    value = f"Command: {cmd_stripped[:100]}\nResult: {condensed[:200]}"

    return {"key": key, "value": value, "tags": tags}


# Cache for tool availability (per-session via file)
_STATE_DIR = Path.home() / ".claude" / "autodidact"
with contextlib.suppress(OSError):
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
_TOOL_CACHE_PATH = _STATE_DIR / "tool_cache.json"


def _get_tool_cache() -> dict:
    if _TOOL_CACHE_PATH.exists():
        try:
            return json.loads(_TOOL_CACHE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _set_tool_cache(cache: dict) -> None:
    with contextlib.suppress(OSError):
        _TOOL_CACHE_PATH.write_text(json.dumps(cache))


def _has_tool(name: str) -> bool:
    cache = _get_tool_cache()
    if name in cache:
        return cache[name]
    result = shutil.which(name) is not None
    cache[name] = result
    _set_tool_cache(cache)
    return result


def _run_quality_check(file_path: str) -> list[str]:
    """Run language-aware quality checks on an edited file."""
    issues: list[str] = []
    path = Path(file_path)

    if not path.exists():
        return issues

    suffix = path.suffix.lower()

    if suffix == ".py":
        if _has_tool("ruff"):
            # Auto-fix lint issues (imports, style, upgrades) in-place
            with contextlib.suppress(subprocess.TimeoutExpired, OSError):
                subprocess.run(
                    ["ruff", "check", "--fix", str(path)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            # Auto-format in-place
            with contextlib.suppress(subprocess.TimeoutExpired, OSError):
                subprocess.run(
                    ["ruff", "format", str(path)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

            # Report remaining lint issues (non-auto-fixable)
            try:
                result = subprocess.run(
                    ["ruff", "check", str(path)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.stdout.strip():
                    issues.append(f"ruff: {result.stdout.strip()}")
            except (subprocess.TimeoutExpired, OSError):
                pass

        # mypy (only if project has mypy config)
        if _has_tool("mypy"):
            cwd = path.parent
            has_mypy_config = any(
                (cwd / f).exists() for f in ("mypy.ini", "setup.cfg", ".mypy.ini")
            ) or _pyproject_has_mypy(cwd)
            if has_mypy_config:
                try:
                    result = subprocess.run(
                        ["mypy", str(path), "--no-error-summary"],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if result.stdout.strip() and "error:" in result.stdout:
                        issues.append(f"mypy: {result.stdout.strip()}")
                except (subprocess.TimeoutExpired, OSError):
                    pass

    elif suffix in (".js", ".jsx"):
        if _has_tool("npx"):
            # Check for eslint config
            cwd = path.parent
            has_eslint = any(
                (cwd / f).exists()
                for f in (".eslintrc", ".eslintrc.js", ".eslintrc.json", ".eslintrc.yml")
            )
            if has_eslint:
                try:
                    result = subprocess.run(
                        ["npx", "eslint", str(path)],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    if result.stdout.strip():
                        issues.append(f"eslint: {result.stdout.strip()}")
                except (subprocess.TimeoutExpired, OSError):
                    pass

    return issues


def _pyproject_has_mypy(directory: Path) -> bool:
    """Check if pyproject.toml in directory has [tool.mypy] section."""
    pyproject = directory / "pyproject.toml"
    if not pyproject.exists():
        return False
    try:
        content = pyproject.read_text()
        return "[tool.mypy]" in content
    except OSError:
        return False


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})
    tool_output = hook_input.get("tool_output", "")
    session_id = hook_input.get("session_id") or hook_input.get("sessionId") or ""
    cwd = hook_input.get("cwd", "")
    project_path = resolve_main_repo(cwd) if cwd else ""

    messages: list[str] = []

    try:
        db = LearningDB()

        # Error learning is handled by post_tool_use_failure.py
        # (PostToolUse only fires on success; PostToolUseFailure handles errors)

        # Per-edit quality checks (PostToolUse only fires on success)
        if tool_name in (TOOL_EDIT, TOOL_WRITE):
            file_path = tool_input.get("file_path", "")
            if file_path:
                issues = _run_quality_check(file_path)
                if issues:
                    messages.append("QUALITY ISSUES:\n" + "\n".join(f"  {i}" for i in issues))
                    # Record new patterns in DB
                    for issue in issues:
                        issue_sig = normalize_error(issue)
                        sig_hash = hashlib.md5(
                            issue_sig.encode(), usedforsecurity=False
                        ).hexdigest()[:12]
                        db.record(
                            topic="quality",
                            key=f"qual_{sig_hash}",
                            value=issue_sig,
                            category="code_pattern",
                            confidence=0.3,
                            source="quality_check",
                            project_path=project_path,
                            session_id=session_id,
                        )

        # Observation capture (broad, confidence-gated)
        if (
            tool_name in _OBSERVATION_TOOLS
            and tool_output
            and len(tool_output) >= _OBSERVATION_MIN_OUTPUT_LEN
        ):
            obs = _extract_observation(tool_name, tool_input, tool_output)
            if obs:
                db.record(
                    topic="observation",
                    key=obs["key"],
                    value=obs["value"],
                    category="observation",
                    confidence=OBSERVATION_INITIAL_CONFIDENCE,
                    tags=obs["tags"],
                    source="observation",
                    project_path=project_path,
                    session_id=session_id,
                    outcome="interesting",
                )

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
