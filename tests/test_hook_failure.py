"""Tests for post_tool_use_failure.py debug suggestion feature."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add hooks dir to sys.path before any imports that reference hook modules
_HOOKS_DIR = str(Path(__file__).resolve().parent.parent / "hooks")
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

import post_tool_use_failure  # noqa: E402  (must come after sys.path update)


class TestFailureCountHelpers(unittest.TestCase):
    """Tests for the failure count tracking helpers."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self._tmpdir = Path(self._td.name)
        self.addCleanup(self._td.cleanup)

        self._counts_path = self._tmpdir / "failure_counts.json"
        self._patcher = patch("post_tool_use_failure._FAILURE_COUNTS_PATH", self._counts_path)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_load_failure_counts_empty_when_no_file(self) -> None:
        counts = post_tool_use_failure._load_failure_counts("sess-1")
        self.assertEqual(counts, {})

    def test_load_failure_counts_returns_empty_for_different_session(self) -> None:
        post_tool_use_failure._save_failure_counts("sess-1", {"abc": 5})
        counts = post_tool_use_failure._load_failure_counts("sess-2")
        self.assertEqual(counts, {})

    def test_load_failure_counts_returns_counts_for_same_session(self) -> None:
        post_tool_use_failure._save_failure_counts("sess-1", {"abc": 5, "def": 2})
        counts = post_tool_use_failure._load_failure_counts("sess-1")
        self.assertEqual(counts["abc"], 5)
        self.assertEqual(counts["def"], 2)

    def test_save_and_load_roundtrip(self) -> None:
        post_tool_use_failure._save_failure_counts("sess-x", {"hash1": 3})
        counts = post_tool_use_failure._load_failure_counts("sess-x")
        self.assertEqual(counts, {"hash1": 3})

    def test_increment_failure_count_increments(self) -> None:
        c1 = post_tool_use_failure._increment_failure_count("sess-1", "hash1")
        c2 = post_tool_use_failure._increment_failure_count("sess-1", "hash1")
        c3 = post_tool_use_failure._increment_failure_count("sess-1", "hash1")
        self.assertEqual(c1, 1)
        self.assertEqual(c2, 2)
        self.assertEqual(c3, 3)

    def test_increment_failure_count_resets_on_new_session(self) -> None:
        post_tool_use_failure._increment_failure_count("sess-1", "hash1")
        post_tool_use_failure._increment_failure_count("sess-1", "hash1")
        # New session — counts should start fresh
        c1 = post_tool_use_failure._increment_failure_count("sess-2", "hash1")
        self.assertEqual(c1, 1)

    def test_increment_tracks_separate_hashes_independently(self) -> None:
        post_tool_use_failure._increment_failure_count("sess-1", "hashA")
        post_tool_use_failure._increment_failure_count("sess-1", "hashA")
        c_b = post_tool_use_failure._increment_failure_count("sess-1", "hashB")
        self.assertEqual(c_b, 1)


class TestDebugTipInHookOutput(unittest.TestCase):
    """Integration tests: verify the hook emits the debug tip after 3+ failures."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self._tmpdir = Path(self._td.name)
        self.addCleanup(self._td.cleanup)

        self._counts_path = self._tmpdir / "failure_counts.json"

    def _run_main(self, error_text: str, session_id: str) -> dict:
        """Run the hook main() with mocked stdin and capture stdout output."""
        hook_input = json.dumps(
            {
                "tool_name": "Bash",
                "error": error_text,
                "session_id": session_id,
                "cwd": str(self._tmpdir),
            }
        )

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.get_by_error_signature.return_value = None
        mock_db.record.return_value = None

        stdout_capture = io.StringIO()

        with (
            patch("post_tool_use_failure._FAILURE_COUNTS_PATH", self._counts_path),
            patch("post_tool_use_failure._PENDING_FIX_PATH", self._tmpdir / "pending_fix.json"),
            patch("sys.stdin", io.StringIO(hook_input)),
            patch("sys.stdout", stdout_capture),
            patch("sys.exit"),
            patch("post_tool_use_failure.LearningDB", return_value=mock_db),
            patch("post_tool_use_failure.resolve_main_repo", return_value=""),
            patch("post_tool_use_failure._tee_output", return_value=None),
        ):
            post_tool_use_failure.main()

        output_text = stdout_capture.getvalue()
        return json.loads(output_text) if output_text else {}

    def test_no_tip_after_one_failure(self) -> None:
        result = self._run_main("SyntaxError: unexpected token", "sess-abc")
        context = result.get("additionalContext", "")
        self.assertNotIn("TIP: Run /do debug", context)

    def test_no_tip_after_two_failures(self) -> None:
        self._run_main("SyntaxError: unexpected token", "sess-abc")
        result = self._run_main("SyntaxError: unexpected token", "sess-abc")
        context = result.get("additionalContext", "")
        self.assertNotIn("TIP: Run /do debug", context)

    def test_tip_appears_after_three_failures(self) -> None:
        self._run_main("SyntaxError: unexpected token", "sess-abc")
        self._run_main("SyntaxError: unexpected token", "sess-abc")
        result = self._run_main("SyntaxError: unexpected token", "sess-abc")
        context = result.get("additionalContext", "")
        self.assertIn("TIP: Run /do debug", context)

    def test_tip_appears_after_four_failures(self) -> None:
        for _ in range(4):
            result = self._run_main("ImportError: no module", "sess-xyz")
        context = result.get("additionalContext", "")
        self.assertIn("TIP: Run /do debug", context)

    def test_tip_not_shown_for_different_error_signatures(self) -> None:
        """Different errors should not share counts."""
        self._run_main("SyntaxError: unexpected token", "sess-abc")
        self._run_main("SyntaxError: unexpected token", "sess-abc")
        # Different error — should not reach threshold
        result = self._run_main("ImportError: no module named foo", "sess-abc")
        context = result.get("additionalContext", "")
        self.assertNotIn("TIP: Run /do debug", context)


if __name__ == "__main__":
    unittest.main()
