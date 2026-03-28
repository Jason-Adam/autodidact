"""Tests for pre_tool_use safety gate."""

from __future__ import annotations

import io
import json
import sys
import unittest
from unittest.mock import patch

_REPO = __import__("pathlib").Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from hooks.pre_tool_use import main  # noqa: E402


def _run_hook(tool_name: str, tool_input: dict) -> tuple[int, dict]:
    """Run the hook with given input and return (exit_code, json_output)."""
    payload = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
    stdout = io.StringIO()
    with (
        patch("sys.stdin", io.StringIO(payload)),
        patch("sys.stdout", stdout),
    ):
        try:
            main()
        except SystemExit as e:
            exit_code = e.code
        else:
            exit_code = 0
    output = json.loads(stdout.getvalue()) if stdout.getvalue() else {}
    return exit_code, output


class TestSendMessageGuard(unittest.TestCase):
    def test_blocks_missing_summary(self) -> None:
        code, out = _run_hook("SendMessage", {"to": "interviewer", "message": "yes"})
        self.assertEqual(code, 2)
        self.assertEqual(out["decision"], "block")
        self.assertIn("summary", out["reason"])

    def test_blocks_empty_summary(self) -> None:
        code, out = _run_hook("SendMessage", {"to": "interviewer", "message": "yes", "summary": ""})
        self.assertEqual(code, 2)
        self.assertEqual(out["decision"], "block")

    def test_allows_with_summary(self) -> None:
        code, out = _run_hook(
            "SendMessage",
            {"to": "interviewer", "message": "yes", "summary": "Round 1 complete"},
        )
        self.assertEqual(code, 0)
        self.assertNotIn("decision", out)

    def test_allows_non_string_message(self) -> None:
        """Non-string messages (e.g., dicts) don't require summary."""
        code, out = _run_hook("SendMessage", {"to": "interviewer", "message": {"key": "value"}})
        self.assertEqual(code, 0)
        self.assertNotIn("decision", out)

    def test_allows_missing_message_key(self) -> None:
        """SendMessage with no message field should not trigger the guard."""
        code, out = _run_hook("SendMessage", {"to": "interviewer"})
        self.assertEqual(code, 0)
        self.assertNotIn("decision", out)


class TestFileProtection(unittest.TestCase):
    def test_blocks_env_write(self) -> None:
        code, out = _run_hook("Edit", {"file_path": "/app/.env"})
        self.assertEqual(code, 2)
        self.assertEqual(out["decision"], "block")

    def test_allows_normal_edit(self) -> None:
        code, out = _run_hook("Edit", {"file_path": "/app/src/main.py"})
        self.assertEqual(code, 0)


class TestDangerousCommands(unittest.TestCase):
    def test_blocks_rm_rf_root(self) -> None:
        code, out = _run_hook("Bash", {"command": "rm -rf /"})
        self.assertEqual(code, 2)

    def test_allows_normal_bash(self) -> None:
        code, out = _run_hook("Bash", {"command": "ls -la"})
        self.assertEqual(code, 0)


class TestPassthrough(unittest.TestCase):
    def test_unknown_tool_allowed(self) -> None:
        code, out = _run_hook("Read", {"file_path": "/etc/hosts"})
        self.assertEqual(code, 0)
