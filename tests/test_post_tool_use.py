"""Tests for post_tool_use observation extraction."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from hooks.post_tool_use import _extract_observation  # noqa: E402


class TestExtractObservation(unittest.TestCase):
    def test_bash_command_produces_observation(self) -> None:
        result = _extract_observation(
            "Bash",
            {"command": "git status"},
            "On branch main\nYour branch is up to date with 'origin/main'.\nnothing to commit",
        )
        assert result is not None
        self.assertIn("git status", result["value"])
        self.assertEqual(result["tags"], "bash git")
        self.assertTrue(result["key"].startswith("obs_"))

    def test_non_bash_tool_returns_none(self) -> None:
        result = _extract_observation(
            "Read",
            {"file_path": "/some/file.py"},
            "file contents here " * 10,
        )
        self.assertIsNone(result)

    def test_skip_cat_command(self) -> None:
        result = _extract_observation(
            "Bash",
            {"command": "cat /etc/hosts"},
            "127.0.0.1 localhost\n" * 5,
        )
        self.assertIsNone(result)

    def test_skip_echo_command(self) -> None:
        result = _extract_observation(
            "Bash",
            {"command": "echo hello world"},
            "hello world " * 10,
        )
        self.assertIsNone(result)

    def test_skip_ls_command(self) -> None:
        result = _extract_observation(
            "Bash",
            {"command": "ls -la /some/dir"},
            "total 100\ndrwxr-xr-x " * 5,
        )
        self.assertIsNone(result)

    def test_rtk_command_captured(self) -> None:
        result = _extract_observation(
            "Bash",
            {"command": "rtk git status"},
            "On branch main " * 10,
        )
        self.assertIsNotNone(result)

    def test_rtk_proxy_unwrapped(self) -> None:
        result = _extract_observation(
            "Bash",
            {"command": "rtk proxy git log --oneline"},
            "abc1234 Some commit message " * 5,
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("git", result["tags"])
        self.assertNotIn("rtk proxy", result["value"])

    def test_rtk_proxy_skip_still_applies(self) -> None:
        result = _extract_observation(
            "Bash",
            {"command": "rtk proxy cat file.txt"},
            "file contents here " * 5,
        )
        self.assertIsNone(result)

    def test_skip_pwd_command(self) -> None:
        result = _extract_observation(
            "Bash",
            {"command": "pwd"},
            "/Users/someone/code/project " * 3,
        )
        self.assertIsNone(result)

    def test_empty_command_returns_none(self) -> None:
        result = _extract_observation(
            "Bash",
            {"command": ""},
            "some output " * 10,
        )
        self.assertIsNone(result)

    def test_missing_command_returns_none(self) -> None:
        result = _extract_observation(
            "Bash",
            {},
            "some output " * 10,
        )
        self.assertIsNone(result)

    def test_deterministic_key(self) -> None:
        args = (
            "Bash",
            {"command": "npm test"},
            "PASS src/test.js\nTests: 5 passed, 5 total " * 3,
        )
        r1 = _extract_observation(*args)
        r2 = _extract_observation(*args)
        assert r1 is not None and r2 is not None
        self.assertEqual(r1["key"], r2["key"])

    def test_value_truncation(self) -> None:
        result = _extract_observation(
            "Bash",
            {"command": "python3 -m pytest"},
            "x" * 1000,
        )
        assert result is not None
        # Command portion: max 100 chars + "Command: \nResult: " overhead
        # Result portion: max 200 chars
        self.assertLessEqual(len(result["value"]), 350)

    def test_tag_extraction(self) -> None:
        result = _extract_observation(
            "Bash",
            {"command": "python3 -m pytest tests/"},
            "collected 10 items\n" + "PASSED " * 20,
        )
        assert result is not None
        self.assertEqual(result["tags"], "bash python3")


if __name__ == "__main__":
    unittest.main()
