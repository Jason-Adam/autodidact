#!/usr/bin/env python3
"""PostToolUseFailure hook: captures error signatures from failed tool uses.

Fires when a tool call fails (e.g., Bash exits non-zero). Records error
patterns in the learning DB so known fixes can be surfaced on recurrence.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import sys
import time
from pathlib import Path

_HOOKS = Path(__file__).resolve().parent
_REPO = _HOOKS.parent
sys.path.insert(0, str(_HOOKS))
sys.path.insert(0, str(_REPO))


from constants import normalize_error  # noqa: E402

from src.confidence import initial_confidence_for_outcome  # noqa: E402
from src.db import LearningDB  # noqa: E402
from src.git_utils import resolve_main_repo  # noqa: E402

_STATE_DIR = Path.home() / ".claude" / "autodidact"
_PENDING_FIX_PATH = _STATE_DIR / "pending_fix.json"
_TEE_DIR_NAME = ".planning/tee"
_TEE_MAX_BYTES = 1024 * 1024
_TEE_MAX_FILES = 20
_TEE_MIN_BYTES = 500


def _tee_output(tool_name: str, error_text: str, cwd: str) -> str | None:
    """Save full error output to disk; return a hint string or None."""
    if not cwd or len(error_text) < _TEE_MIN_BYTES:
        return None

    tee_dir = Path(cwd) / _TEE_DIR_NAME
    with contextlib.suppress(OSError):
        tee_dir.mkdir(parents=True, exist_ok=True)
        if tee_dir.resolve() != (Path(cwd) / _TEE_DIR_NAME).resolve():
            return None  # symlink was followed

        safe_name = re.sub(r"[^\w\-]", "_", tool_name)
        epoch = int(time.time())
        filename = f"{epoch}_{safe_name}_error.log"
        tee_path = tee_dir / filename
        content = error_text
        if len(content.encode()) > _TEE_MAX_BYTES:
            content = error_text.encode()[:_TEE_MAX_BYTES].decode("utf-8", errors="replace")
        tee_path.write_text(content)
        with contextlib.suppress(OSError):
            tee_path.chmod(0o600)

        existing = sorted(tee_dir.glob("*.log"), key=lambda p: p.stat().st_mtime)
        while len(existing) > _TEE_MAX_FILES:
            with contextlib.suppress(OSError):
                existing.pop(0).unlink()

        return f"[full error output: {_TEE_DIR_NAME}/{filename}]"
    return None


def _load_pending_fix() -> dict | None:
    if _PENDING_FIX_PATH.exists():
        try:
            return json.loads(_PENDING_FIX_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _save_pending_fix(signature: str, learning_id: int, session_id: str) -> None:
    with contextlib.suppress(OSError):
        _PENDING_FIX_PATH.write_text(
            json.dumps(
                {"signature": signature, "learning_id": learning_id, "session_id": session_id}
            )
        )


def _clear_pending_fix() -> None:
    with contextlib.suppress(OSError):
        _PENDING_FIX_PATH.unlink(missing_ok=True)


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    tool_name = hook_input.get("tool_name", "")
    error_text = hook_input.get("error", "")
    session_id = hook_input.get("session_id") or hook_input.get("sessionId") or ""
    cwd = hook_input.get("cwd", "")
    project_path = resolve_main_repo(cwd) if cwd else ""

    messages: list[str] = []

    if not error_text:
        json.dump({}, sys.stdout)
        sys.exit(0)

    try:
        with LearningDB() as db:
            tee_hint = _tee_output(tool_name, error_text, cwd)
            if tee_hint:
                messages.append(tee_hint)

            signature = normalize_error(error_text)
            sig_hash = hashlib.md5(signature.encode(), usedforsecurity=False).hexdigest()[:12]

            # Check if a previous fix suggestion failed to resolve the error
            pending_fix = _load_pending_fix()
            if (
                pending_fix
                and pending_fix.get("signature") == signature
                and pending_fix.get("session_id", "") == session_id
            ):
                db.decay(pending_fix["learning_id"])
                _clear_pending_fix()

            # Check if we know this error
            known = db.get_by_error_signature(signature)
            if known:
                db.boost(known["id"])
                msg = (
                    f"KNOWN ERROR [{known['key']}]: {known['value']} "
                    f"(conf: {known['confidence']:.2f})"
                )
                messages.append(msg)
                _save_pending_fix(signature, known["id"], session_id)
            else:
                db.record(
                    topic="error",
                    key=f"err_{sig_hash}",
                    value=f"Error in {tool_name}: {signature}",
                    category="error_fix",
                    confidence=initial_confidence_for_outcome("failure"),
                    source="error_learner",
                    project_path=project_path,
                    session_id=session_id,
                    error_signature=signature,
                    error_type=tool_name,
                    outcome="failure",
                )
                _clear_pending_fix()
    except Exception:
        pass  # Graceful degradation

    output: dict = {}
    if messages:
        output["additionalContext"] = "\n\n".join(messages)

    json.dump(output, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
