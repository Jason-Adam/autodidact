#!/usr/bin/env python3
"""PostToolUse hook: error learner, success tracker, per-edit quality checks.

Fires after every tool use. Non-blocking (exit 0).

Responsibilities:
1. Capture error signatures from failed tool uses -> record in learning DB
2. Check if output matches a known error -> inject fix suggestion
3. Run language-aware quality checks after file edits (ruff, eslint)
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from src.db import LearningDB
from src.git_utils import resolve_main_repo

# Cache for tool availability (per-session via file)
_TOOL_CACHE_PATH = Path("/tmp/autodidact_tool_cache.json")


def _get_tool_cache() -> dict:
    if _TOOL_CACHE_PATH.exists():
        try:
            return json.loads(_TOOL_CACHE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _set_tool_cache(cache: dict) -> None:
    import contextlib

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


def _normalize_error(error_text: str) -> str:
    """Create a normalized signature from an error message."""
    # Remove file paths, line numbers, and timestamps
    normalized = re.sub(r"/[\w/.-]+", "<PATH>", error_text)
    normalized = re.sub(r"line \d+", "line N", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\d{4}-\d{2}-\d{2}", "<DATE>", normalized)
    # Take first meaningful line
    for line in normalized.splitlines():
        line = line.strip()
        if line and not line.startswith(("Traceback", "File ", "  ")):
            return line[:200]
    return normalized[:200]


def _run_quality_check(file_path: str) -> list[str]:
    """Run language-aware quality checks on an edited file."""
    issues: list[str] = []
    path = Path(file_path)

    if not path.exists():
        return issues

    suffix = path.suffix.lower()

    if suffix == ".py":
        # ruff check
        if _has_tool("ruff"):
            try:
                result = subprocess.run(
                    ["ruff", "check", "--select=E,F", str(path)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.stdout.strip():
                    issues.append(f"ruff: {result.stdout.strip()}")
            except (subprocess.TimeoutExpired, OSError):
                pass

        # ruff format check
        if _has_tool("ruff"):
            try:
                result = subprocess.run(
                    ["ruff", "format", "--check", str(path)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode != 0:
                    issues.append(f"ruff format: {path.name} needs formatting")
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
    is_error = hook_input.get("is_error", False)
    session_id = hook_input.get("session_id", "")
    cwd = hook_input.get("cwd", "")
    project_path = resolve_main_repo(cwd) if cwd else ""

    messages: list[str] = []

    try:
        db = LearningDB()

        # Error learning
        if is_error and tool_output:
            error_text = str(tool_output)
            signature = _normalize_error(error_text)
            sig_hash = hashlib.md5(signature.encode()).hexdigest()[:12]

            # Check if we know this error
            known = db.get_by_error_signature(signature)
            if known:
                db.boost(known["id"])
                msg = (
                    f"KNOWN ERROR [{known['key']}]: {known['value']} "
                    f"(conf: {known['confidence']:.2f})"
                )
                messages.append(msg)
            else:
                # Record new error
                db.record(
                    topic="error",
                    key=f"err_{sig_hash}",
                    value=f"Error in {tool_name}: {signature}",
                    category="error_fix",
                    confidence=0.5,
                    source="error_learner",
                    project_path=project_path,
                    session_id=session_id,
                    error_signature=signature,
                    error_type=tool_name,
                )

        # Per-edit quality checks
        if tool_name in ("Edit", "Write") and not is_error:
            file_path = tool_input.get("file_path", "")
            if file_path:
                issues = _run_quality_check(file_path)
                if issues:
                    messages.append("QUALITY ISSUES:\n" + "\n".join(f"  {i}" for i in issues))
                    # Record new patterns in DB
                    for issue in issues:
                        issue_sig = _normalize_error(issue)
                        sig_hash = hashlib.md5(issue_sig.encode()).hexdigest()[:12]
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
