"""Tests for the response analyzer."""

from __future__ import annotations

import json
import unittest

from src.response_analyzer import analyze


class TestResponseAnalyzer(unittest.TestCase):
    def test_parse_array_format(self) -> None:
        """Array with system init + result entries."""
        data = [
            {"type": "system", "session_id": "sess-abc123"},
            {"type": "assistant", "content": "working..."},
            {
                "type": "result",
                "result": "All done. Created 3 files.",
                "session_id": "sess-abc123",
            },
        ]
        result = analyze(json.dumps(data), exit_code=0)
        self.assertEqual(result.session_id, "sess-abc123")
        self.assertFalse(result.is_error)

    def test_parse_object_format(self) -> None:
        """{result, sessionId, metadata} format."""
        data = {
            "result": "Completed the refactoring.",
            "sessionId": "sess-obj-456",
            "metadata": {"model": "claude-4"},
        }
        result = analyze(json.dumps(data), exit_code=0)
        self.assertEqual(result.session_id, "sess-obj-456")
        self.assertFalse(result.is_error)

    def test_parse_flat_format(self) -> None:
        """Direct fields in flat format."""
        data = {
            "status": "complete",
            "session_id": "sess-flat-789",
        }
        result = analyze(json.dumps(data), exit_code=0)
        self.assertEqual(result.session_id, "sess-flat-789")

    def test_extract_session_id_from_array(self) -> None:
        """Session ID extracted from system init message in array."""
        data = [
            {"type": "system", "session_id": "sess-init-001"},
            {"type": "result", "result": "Done."},
        ]
        result = analyze(json.dumps(data), exit_code=0)
        self.assertEqual(result.session_id, "sess-init-001")

    def test_parse_valid_status_block(self) -> None:
        """Full AUTODIDACT_STATUS block in result text."""
        status_block = (
            "Here is my summary.\n"
            "---AUTODIDACT_STATUS---\n"
            "STATUS: IN_PROGRESS\n"
            "EXIT_SIGNAL: false\n"
            "WORK_TYPE: implementation\n"
            "FILES_MODIFIED: 3\n"
            "SUMMARY: Added three new modules\n"
            "---END_STATUS---\n"
        )
        data = {"result": status_block, "sessionId": "sess-status"}
        result = analyze(json.dumps(data), exit_code=0)
        self.assertEqual(result.raw_status, "IN_PROGRESS")
        self.assertFalse(result.exit_signal)
        self.assertEqual(result.work_type, "implementation")
        self.assertEqual(result.files_modified, 3)
        self.assertEqual(result.work_summary, "Added three new modules")

    def test_missing_status_block(self) -> None:
        """Graceful defaults when no status block present."""
        data = {"result": "Just some plain text response.", "sessionId": "sess-no-block"}
        result = analyze(json.dumps(data), exit_code=0)
        self.assertFalse(result.exit_signal)
        self.assertEqual(result.work_type, "unknown")
        self.assertEqual(result.raw_status, "unknown")
        self.assertEqual(result.files_modified, 0)

    def test_detect_questions_positive(self) -> None:
        """Text with question patterns returns True with count."""
        data = {
            "result": (
                "I have a question. Should I refactor the module? "
                "Would you like me to also update tests?"
            ),
            "sessionId": "sess-q",
        }
        result = analyze(json.dumps(data), exit_code=0)
        self.assertTrue(result.asking_questions)
        self.assertGreaterEqual(result.question_count, 2)

    def test_detect_questions_negative(self) -> None:
        """Normal text without question patterns."""
        data = {
            "result": "I completed the implementation. All tests pass.",
            "sessionId": "sess-noq",
        }
        result = analyze(json.dumps(data), exit_code=0)
        self.assertFalse(result.asking_questions)
        self.assertEqual(result.question_count, 0)

    def test_detect_rate_limit_event(self) -> None:
        """Output containing rate_limit_event + rejected."""
        output = json.dumps(
            {
                "result": "rate_limit_event was rejected by the server",
                "sessionId": "sess-rl",
            }
        )
        result = analyze(output, exit_code=0)
        self.assertTrue(result.is_rate_limited)

    def test_detect_rate_limit_hourly(self) -> None:
        """Output containing 'hourly limit'."""
        output = json.dumps(
            {
                "result": "You have hit your hourly limit. Please wait.",
                "sessionId": "sess-rl2",
            }
        )
        result = analyze(output, exit_code=0)
        self.assertTrue(result.is_rate_limited)

    def test_detect_rate_limit_extra_usage(self) -> None:
        """Output containing 'out of extra usage'."""
        output = json.dumps(
            {
                "result": "You are out of extra usage for this billing period.",
                "sessionId": "sess-rl3",
            }
        )
        result = analyze(output, exit_code=0)
        self.assertTrue(result.is_rate_limited)

    def test_detect_rate_limit_negative(self) -> None:
        """Normal output, no rate limit."""
        output = json.dumps(
            {
                "result": "Everything completed successfully.",
                "sessionId": "sess-ok",
            }
        )
        result = analyze(output, exit_code=0)
        self.assertFalse(result.is_rate_limited)

    def test_detect_permission_denials(self) -> None:
        """Text with 'permission denied'."""
        data = {
            "result": "Error: permission denied when accessing /etc/shadow",
            "sessionId": "sess-perm",
        }
        result = analyze(json.dumps(data), exit_code=1)
        self.assertTrue(result.has_permission_denials)
        self.assertGreaterEqual(result.permission_denial_count, 1)

    def test_handle_malformed_json(self) -> None:
        """Garbage input returns safe defaults."""
        result = analyze("{not valid json at all!!!", exit_code=1)
        self.assertFalse(result.exit_signal)
        self.assertFalse(result.is_rate_limited)
        self.assertEqual(result.work_type, "unknown")
        self.assertIsNone(result.session_id)

    def test_handle_empty_output(self) -> None:
        """Empty string returns safe defaults."""
        result = analyze("", exit_code=0)
        self.assertFalse(result.exit_signal)
        self.assertFalse(result.asking_questions)
        self.assertIsNone(result.session_id)
        self.assertEqual(result.files_modified, 0)

    def test_exit_signal_true_in_status_block(self) -> None:
        """EXIT_SIGNAL: true parsed correctly."""
        status_block = (
            "---AUTODIDACT_STATUS---\n"
            "STATUS: COMPLETE\n"
            "EXIT_SIGNAL: true\n"
            "WORK_TYPE: testing\n"
            "FILES_MODIFIED: 1\n"
            "SUMMARY: All tests pass\n"
            "---END_STATUS---\n"
        )
        data = {"result": status_block, "sessionId": "sess-exit"}
        result = analyze(json.dumps(data), exit_code=0)
        self.assertTrue(result.exit_signal)
        self.assertEqual(result.raw_status, "COMPLETE")

    def test_explicit_exit_signal_false(self) -> None:
        """EXIT_SIGNAL: false is not overridden by STATUS: COMPLETE."""
        status_block = (
            "---AUTODIDACT_STATUS---\n"
            "STATUS: COMPLETE\n"
            "EXIT_SIGNAL: false\n"
            "WORK_TYPE: documentation\n"
            "FILES_MODIFIED: 2\n"
            "SUMMARY: Docs updated\n"
            "---END_STATUS---\n"
        )
        data = {"result": status_block, "sessionId": "sess-noex"}
        result = analyze(json.dumps(data), exit_code=0)
        self.assertFalse(result.exit_signal)
        self.assertEqual(result.raw_status, "COMPLETE")


if __name__ == "__main__":
    unittest.main()
