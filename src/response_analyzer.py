"""Parse Claude CLI JSON output to extract machine-readable signals.

Handles three output formats (array, object, flat) and extracts
structured status blocks, question patterns, rate limits, and
permission denials from Claude CLI responses.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass
class ResponseAnalysis:
    session_id: str | None = None
    exit_signal: bool = False
    work_summary: str = ""
    work_type: str = "unknown"
    files_modified: int = 0
    asking_questions: bool = False
    question_count: int = 0
    has_permission_denials: bool = False
    permission_denial_count: int = 0
    is_rate_limited: bool = False
    is_error: bool = False
    raw_status: str = "unknown"


# --- Question detection patterns ---

_QUESTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bshould I\b", re.IGNORECASE),
    re.compile(r"\bwould you\b", re.IGNORECASE),
    re.compile(r"\bdo you want\b", re.IGNORECASE),
    re.compile(r"\bwhich approach\b", re.IGNORECASE),
    re.compile(r"\bcan you clarify\b", re.IGNORECASE),
    re.compile(r"\bwhat would you prefer\b", re.IGNORECASE),
    re.compile(r"\bshall I\b", re.IGNORECASE),
    re.compile(r"\bdo you prefer\b", re.IGNORECASE),
    re.compile(r"\bwould you like\b", re.IGNORECASE),
    re.compile(r"\bcould you\b", re.IGNORECASE),
    re.compile(r"\bplease confirm\b", re.IGNORECASE),
    re.compile(r"\blet me know\b", re.IGNORECASE),
    re.compile(r"\bwhat do you think\b", re.IGNORECASE),
    re.compile(r"\bis that okay\b", re.IGNORECASE),
    re.compile(r"\bis that correct\b", re.IGNORECASE),
    re.compile(r"\bany preference\b", re.IGNORECASE),
    re.compile(r"\bbefore I proceed\b", re.IGNORECASE),
]

# --- Permission denial patterns ---

_PERMISSION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bpermission denied\b", re.IGNORECASE),
    re.compile(r"\bnot allowed\b", re.IGNORECASE),
    re.compile(r"\bdenied by user\b", re.IGNORECASE),
]

# --- Status block regex ---

_STATUS_BLOCK_RE = re.compile(
    r"---AUTODIDACT_STATUS---\s*\n(.*?)\n\s*---END_STATUS---",
    re.DOTALL,
)


def _detect_questions(text: str) -> tuple[bool, int]:
    """Detect question patterns in text, returning (has_questions, count)."""
    count = 0
    for pattern in _QUESTION_PATTERNS:
        count += len(pattern.findall(text))
    return (count > 0, count)


def _detect_rate_limit(output: str, exit_code: int) -> bool:
    """Detect rate limiting from output text.

    Layer 1: rate_limit_event with rejected
    Layer 2: "5 hour limit" or "hourly limit"
    Layer 3: "out of extra usage"
    (exit_code 124 is handled by the caller, not here)
    """
    if "rate_limit_event" in output and "rejected" in output:
        return True
    lower = output.lower()
    if "5 hour limit" in lower or "hourly limit" in lower:
        return True
    return "out of extra usage" in lower


def _detect_permission_denials(text: str) -> tuple[bool, int]:
    """Detect permission denial patterns in text."""
    count = 0
    for pattern in _PERMISSION_PATTERNS:
        count += len(pattern.findall(text))
    return (count > 0, count)


def _parse_status_block(text: str) -> dict[str, str]:
    """Extract key-value pairs from an AUTODIDACT_STATUS block."""
    match = _STATUS_BLOCK_RE.search(text)
    if not match:
        return {}
    block = match.group(1)
    pairs: dict[str, str] = {}
    for line in block.strip().splitlines():
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            pairs[key.strip().upper()] = value.strip()
    return pairs


def _extract_result_text_and_session(
    output: str,
) -> tuple[str, str | None]:
    """Parse JSON output and return (result_text, session_id).

    Handles array, object, and flat formats.
    """
    stripped = output.strip()
    if not stripped:
        return ("", None)

    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return (stripped, None)

    # Array format: [{type:"system",...}, ..., {type:"result",...}]
    if isinstance(data, list):
        session_id: str | None = None
        result_text = ""
        for entry in data:
            if not isinstance(entry, dict):
                continue
            if entry.get("type") == "system":
                session_id = entry.get("session_id") or entry.get("sessionId")
            if entry.get("type") == "result":
                result_text = entry.get("result", "")
                if not session_id:
                    session_id = entry.get("session_id") or entry.get("sessionId")
        return (result_text, session_id)

    if isinstance(data, dict):
        # Object format: {result: "...", sessionId: "...", metadata: {...}}
        if "result" in data:
            session_id = data.get("sessionId") or data.get("session_id")
            return (data["result"], session_id)

        # Flat format: direct fields
        return (json.dumps(data), data.get("session_id") or data.get("sessionId"))

    return (stripped, None)


def analyze(output: str, exit_code: int) -> ResponseAnalysis:
    """Analyze Claude CLI output and return structured signals."""
    analysis = ResponseAnalysis()

    if not output or not output.strip():
        return analysis

    # Extract result text and session id from JSON
    result_text, session_id = _extract_result_text_and_session(output)
    analysis.session_id = session_id

    # Check rate limiting on raw output
    analysis.is_rate_limited = _detect_rate_limit(output, exit_code)

    # Check for errors via exit code
    if exit_code != 0 and not analysis.is_rate_limited:
        analysis.is_error = True

    # Parse status block from result text
    status_fields = _parse_status_block(result_text)

    if status_fields:
        raw_status = status_fields.get("STATUS", "unknown")
        analysis.raw_status = raw_status

        exit_signal_str = status_fields.get("EXIT_SIGNAL", "false").lower()
        analysis.exit_signal = exit_signal_str == "true"

        analysis.work_type = status_fields.get("WORK_TYPE", "unknown")
        analysis.work_summary = status_fields.get("SUMMARY", "")

        try:
            analysis.files_modified = int(status_fields.get("FILES_MODIFIED", "0"))
        except ValueError:
            analysis.files_modified = 0

    # Detect questions in result text
    asking, q_count = _detect_questions(result_text)
    analysis.asking_questions = asking
    analysis.question_count = q_count

    # Detect permission denials in result text
    has_denials, denial_count = _detect_permission_denials(result_text)
    analysis.has_permission_denials = has_denials
    analysis.permission_denial_count = denial_count

    return analysis
