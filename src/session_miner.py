"""Mine Claude Code session JSONL files for error correction patterns.

Discovers sessions stored in ~/.claude/projects/, extracts Bash tool use
sequences, detects correction pairs (failed command followed by a similar
corrected command), and records them as learnings in the LearningDB.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.db import LearningDB

# ── Constants ────────────────────────────────────────────────────────────────

_PROJECTS_DIR = Path.home() / ".claude" / "projects"
_JACCARD_THRESHOLD = 0.6
_WINDOW_SIZE = 3
_MAX_SESSION_BYTES = 50 * 1024 * 1024  # 50 MB


# ── Path encoding ────────────────────────────────────────────────────────────


def _encode_path(project_path: str) -> str:
    """Encode a filesystem path to the Claude projects directory name format.

    /Users/foo/bar  →  -Users-foo-bar
    """
    return project_path.replace("/", "-")


# ── Session discovery ────────────────────────────────────────────────────────


def discover_sessions(project_path: str) -> list[Path]:
    """Walk ~/.claude/projects/ for JSONL files matching the encoded project path.

    Returns list of Path objects for matching session files.
    """
    if not project_path or not Path(project_path).is_absolute():
        return []
    encoded = _encode_path(project_path)
    if not _PROJECTS_DIR.exists():
        return []
    sessions: list[Path] = []
    for entry in _PROJECTS_DIR.iterdir():
        if entry.is_dir() and not entry.is_symlink() and entry.name == encoded:
            sessions.extend(entry.glob("*.jsonl"))
    return sessions


# ── Command extraction ───────────────────────────────────────────────────────


def extract_commands(session_path: Path) -> list[dict[str, Any]]:
    """Parse a JSONL session file and extract Bash tool use / result pairs.

    Returns list of dicts with keys:
      - command: str
      - output: str
      - is_error: bool
      - output_len: int
    """
    pending: dict[str, str] = {}  # tool_use_id → command
    results: list[dict[str, Any]] = []

    try:
        if session_path.stat().st_size > _MAX_SESSION_BYTES:
            return []
        text = session_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = obj.get("type")

        if msg_type == "tool_use" and obj.get("name") == "Bash":
            tool_id = obj.get("id", "")
            command = (obj.get("input") or {}).get("command", "")
            if tool_id and command:
                pending[tool_id] = command

        elif msg_type == "tool_result":
            tool_id = obj.get("tool_use_id", "")
            if tool_id not in pending:
                continue
            command = pending.pop(tool_id)
            content = obj.get("content", "")
            if isinstance(content, list):
                # content can be a list of content blocks
                parts: list[str] = []
                for block in content:
                    if isinstance(block, dict):
                        parts.append(block.get("text", ""))
                    else:
                        parts.append(str(block))
                output = "\n".join(parts)
            else:
                output = str(content) if content is not None else ""
            is_error = bool(obj.get("is_error", False))
            results.append(
                {
                    "command": command,
                    "output": output,
                    "is_error": is_error,
                    "output_len": len(output),
                }
            )

    return results


# ── Similarity ───────────────────────────────────────────────────────────────


def _jaccard_similarity(a: str, b: str) -> float:
    """Jaccard similarity between two strings tokenized by whitespace."""
    tokens_a = set(a.split())
    tokens_b = set(b.split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


# ── Pattern detection ────────────────────────────────────────────────────────


def find_error_patterns(commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect correction pairs using a sliding window of size 3.

    A correction pair is: a failed command followed within 1-2 steps by a
    similar command (Jaccard similarity >= threshold).

    Returns list of dicts with keys:
      - failed_command: str
      - correction: str
      - similarity: float
    """
    patterns: list[dict[str, Any]] = []
    n = len(commands)

    for i in range(n - 1):
        if not commands[i]["is_error"]:
            continue
        failed_cmd = commands[i]["command"]
        # Look ahead within window (positions i+1 and i+2)
        lookahead = min(_WINDOW_SIZE - 1, n - i - 1)
        for j in range(1, lookahead + 1):
            candidate = commands[i + j]["command"]
            sim = _jaccard_similarity(failed_cmd, candidate)
            if sim >= _JACCARD_THRESHOLD:
                patterns.append(
                    {
                        "failed_command": failed_cmd,
                        "correction": candidate,
                        "similarity": sim,
                    }
                )
                break  # only record the first correction per failure

    return patterns


# ── Orchestration ─────────────────────────────────────────────────────────────


def mine_and_record(project_path: str, db: LearningDB) -> dict[str, int]:
    """Orchestrate session mining and record correction patterns as learnings.

    Returns dict with:
      - sessions_scanned: int
      - commands_found: int
      - patterns_found: int
      - learnings_recorded: int
    """
    sessions = discover_sessions(project_path)
    sessions_scanned = len(sessions)
    commands_found = 0
    patterns_found = 0
    learnings_recorded = 0

    for session_path in sessions:
        commands = extract_commands(session_path)
        commands_found += len(commands)
        patterns = find_error_patterns(commands)
        patterns_found += len(patterns)
        for pattern in patterns:
            failed = pattern["failed_command"]
            correction = pattern["correction"]
            similarity = pattern["similarity"]
            key = hashlib.sha256(failed.encode()).hexdigest()[:16]
            value = (
                f"Command failed: {failed!r}. "
                f"Correction used: {correction!r}. "
                f"Similarity: {similarity:.2f}"
            )
            db.record(
                topic="session_miner",
                key=key,
                value=value,
                source="session_miner",
                confidence=0.5,
                project_path=project_path,
            )
            learnings_recorded += 1

    return {
        "sessions_scanned": sessions_scanned,
        "commands_found": commands_found,
        "patterns_found": patterns_found,
        "learnings_recorded": learnings_recorded,
    }
