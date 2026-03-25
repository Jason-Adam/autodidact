"""Tests for src/session_miner.py."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.db import LearningDB
from src.session_miner import (
    _jaccard_similarity,
    discover_sessions,
    extract_commands,
    find_error_patterns,
    mine_and_record,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    with path.open("w") as fh:
        for obj in lines:
            fh.write(json.dumps(obj) + "\n")


# ── Test: discover_sessions ───────────────────────────────────────────────────


class TestDiscoverSessions(unittest.TestCase):
    def test_returns_jsonl_files_for_matching_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = Path(tmpdir) / "projects"
            encoded = "-Users-foo-myproject"
            session_dir = projects_dir / encoded
            session_dir.mkdir(parents=True)
            # Create two JSONL files and one non-JSONL
            (session_dir / "session1.jsonl").touch()
            (session_dir / "session2.jsonl").touch()
            (session_dir / "other.txt").touch()

            with patch("src.session_miner._PROJECTS_DIR", projects_dir):
                results = discover_sessions("/Users/foo/myproject")

        self.assertEqual(len(results), 2)
        names = {r.name for r in results}
        self.assertIn("session1.jsonl", names)
        self.assertIn("session2.jsonl", names)

    def test_returns_empty_when_no_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = Path(tmpdir) / "projects"
            projects_dir.mkdir()

            with patch("src.session_miner._PROJECTS_DIR", projects_dir):
                results = discover_sessions("/Users/foo/other")

        self.assertEqual(results, [])

    def test_returns_empty_when_projects_dir_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "nonexistent"
            with patch("src.session_miner._PROJECTS_DIR", missing):
                results = discover_sessions("/Users/foo/bar")
        self.assertEqual(results, [])


# ── Test: extract_commands ────────────────────────────────────────────────────


class TestExtractCommands(unittest.TestCase):
    def _make_session(self, lines: list[dict]) -> Path:
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            for obj in lines:
                f.write(json.dumps(obj) + "\n")
            return Path(f.name)

    def test_extracts_paired_tool_use_and_result(self) -> None:
        session = self._make_session(
            [
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "id": "t1",
                    "input": {"command": "git status"},
                },
                {
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "content": "On branch main",
                    "is_error": False,
                },
            ]
        )
        cmds = extract_commands(session)
        self.assertEqual(len(cmds), 1)
        self.assertEqual(cmds[0]["command"], "git status")
        self.assertEqual(cmds[0]["output"], "On branch main")
        self.assertFalse(cmds[0]["is_error"])
        self.assertEqual(cmds[0]["output_len"], len("On branch main"))

    def test_detects_error_flag(self) -> None:
        session = self._make_session(
            [
                {"type": "tool_use", "name": "Bash", "id": "t2", "input": {"command": "bad cmd"}},
                {
                    "type": "tool_result",
                    "tool_use_id": "t2",
                    "content": "Error: not found",
                    "is_error": True,
                },
            ]
        )
        cmds = extract_commands(session)
        self.assertEqual(len(cmds), 1)
        self.assertTrue(cmds[0]["is_error"])

    def test_skips_malformed_lines(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            f.write("not json\n")
            f.write(
                json.dumps(
                    {"type": "tool_use", "name": "Bash", "id": "t3", "input": {"command": "ls"}}
                )
                + "\n"
            )
            f.write(
                json.dumps({"type": "tool_result", "tool_use_id": "t3", "content": "file.txt"})
                + "\n"
            )
            path = Path(f.name)
        cmds = extract_commands(path)
        self.assertEqual(len(cmds), 1)
        self.assertEqual(cmds[0]["command"], "ls")

    def test_ignores_non_bash_tool_uses(self) -> None:
        session = self._make_session(
            [
                {"type": "tool_use", "name": "Read", "id": "t4", "input": {"file_path": "/foo"}},
                {"type": "tool_result", "tool_use_id": "t4", "content": "content"},
            ]
        )
        cmds = extract_commands(session)
        self.assertEqual(cmds, [])

    def test_handles_list_content(self) -> None:
        session = self._make_session(
            [
                {"type": "tool_use", "name": "Bash", "id": "t5", "input": {"command": "echo hi"}},
                {
                    "type": "tool_result",
                    "tool_use_id": "t5",
                    "content": [{"text": "hi"}, {"text": " there"}],
                    "is_error": False,
                },
            ]
        )
        cmds = extract_commands(session)
        self.assertEqual(len(cmds), 1)
        self.assertIn("hi", cmds[0]["output"])


# ── Test: _jaccard_similarity ─────────────────────────────────────────────────


class TestJaccardSimilarity(unittest.TestCase):
    def test_identical_strings(self) -> None:
        self.assertAlmostEqual(_jaccard_similarity("a b c", "a b c"), 1.0)

    def test_disjoint_strings(self) -> None:
        self.assertAlmostEqual(_jaccard_similarity("a b c", "d e f"), 0.0)

    def test_partial_overlap(self) -> None:
        # tokens_a = {git, status}, tokens_b = {git, log}
        # intersection = {git} = 1, union = {git, status, log} = 3
        result = _jaccard_similarity("git status", "git log")
        self.assertAlmostEqual(result, 1 / 3)

    def test_empty_string(self) -> None:
        self.assertAlmostEqual(_jaccard_similarity("", "git status"), 0.0)
        self.assertAlmostEqual(_jaccard_similarity("git status", ""), 0.0)

    def test_high_similarity(self) -> None:
        # Should be >= threshold (0.6) for correction detection
        sim = _jaccard_similarity("git commit -m msg", "git commit -m 'fixed msg'")
        self.assertGreater(sim, 0.0)


# ── Test: find_error_patterns ─────────────────────────────────────────────────


class TestFindErrorPatterns(unittest.TestCase):
    def test_detects_correction_pair(self) -> None:
        commands = [
            {"command": "git commit -m msg", "output": "error", "is_error": True, "output_len": 5},
            {"command": "git commit -m 'msg'", "output": "ok", "is_error": False, "output_len": 2},
        ]
        patterns = find_error_patterns(commands)
        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0]["failed_command"], "git commit -m msg")
        self.assertEqual(patterns[0]["correction"], "git commit -m 'msg'")
        self.assertGreaterEqual(patterns[0]["similarity"], 0.6)

    def test_returns_empty_for_unrelated_commands(self) -> None:
        commands = [
            {"command": "git status", "output": "error", "is_error": True, "output_len": 5},
            {
                "command": "python -m pytest tests/",
                "output": "ok",
                "is_error": False,
                "output_len": 2,
            },
        ]
        patterns = find_error_patterns(commands)
        self.assertEqual(patterns, [])

    def test_window_lookahead_of_two(self) -> None:
        # Correction is 2 steps after the failure
        commands = [
            {"command": "git commit -m msg", "output": "error", "is_error": True, "output_len": 5},
            {"command": "echo unrelated", "output": "ok", "is_error": False, "output_len": 2},
            {"command": "git commit -m 'msg'", "output": "ok", "is_error": False, "output_len": 2},
        ]
        patterns = find_error_patterns(commands)
        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0]["correction"], "git commit -m 'msg'")

    def test_no_false_positive_for_success_then_different(self) -> None:
        commands = [
            {"command": "ls -la", "output": "ok", "is_error": False, "output_len": 2},
            {"command": "ls -l", "output": "ok", "is_error": False, "output_len": 2},
        ]
        patterns = find_error_patterns(commands)
        self.assertEqual(patterns, [])

    def test_empty_list(self) -> None:
        self.assertEqual(find_error_patterns([]), [])

    def test_single_command(self) -> None:
        commands = [{"command": "git status", "output": "err", "is_error": True, "output_len": 3}]
        self.assertEqual(find_error_patterns(commands), [])


# ── Test: mine_and_record ─────────────────────────────────────────────────────


class TestMineAndRecord(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "test.db"
        self.db = LearningDB(self.db_path)

    def tearDown(self) -> None:
        self.db.close()

    def test_end_to_end_with_correction_pattern(self) -> None:
        # Build a fake projects dir
        projects_dir = Path(self.tmpdir) / "projects"
        encoded = "-Users-test-myproject"
        session_dir = projects_dir / encoded
        session_dir.mkdir(parents=True)

        session_file = session_dir / "session1.jsonl"
        _write_jsonl(
            session_file,
            [
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "id": "t1",
                    "input": {"command": "git commit -m msg"},
                },
                {
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "content": "error: something failed",
                    "is_error": True,
                },
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "id": "t2",
                    "input": {"command": "git commit -m 'msg'"},
                },
                {
                    "type": "tool_result",
                    "tool_use_id": "t2",
                    "content": "[main abc1234] msg",
                    "is_error": False,
                },
            ],
        )

        with patch("src.session_miner._PROJECTS_DIR", projects_dir):
            result = mine_and_record("/Users/test/myproject", self.db)

        self.assertEqual(result["sessions_scanned"], 1)
        self.assertEqual(result["commands_found"], 2)
        self.assertEqual(result["patterns_found"], 1)
        self.assertEqual(result["learnings_recorded"], 1)

        # Verify the learning was persisted
        learnings = self.db.get_top_learnings(limit=10)
        self.assertEqual(len(learnings), 1)
        self.assertEqual(learnings[0]["topic"], "session_miner")
        self.assertEqual(learnings[0]["source"], "session_miner")
        self.assertAlmostEqual(learnings[0]["confidence"], 0.5)

    def test_no_sessions_returns_zeros(self) -> None:
        projects_dir = Path(self.tmpdir) / "empty_projects"
        projects_dir.mkdir()

        with patch("src.session_miner._PROJECTS_DIR", projects_dir):
            result = mine_and_record("/Users/test/noproject", self.db)

        self.assertEqual(
            result,
            {
                "sessions_scanned": 0,
                "commands_found": 0,
                "patterns_found": 0,
                "learnings_recorded": 0,
            },
        )

    def test_no_error_patterns_records_nothing(self) -> None:
        projects_dir = Path(self.tmpdir) / "projects2"
        encoded = "-Users-test-clean"
        session_dir = projects_dir / encoded
        session_dir.mkdir(parents=True)

        session_file = session_dir / "session.jsonl"
        _write_jsonl(
            session_file,
            [
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "id": "t1",
                    "input": {"command": "git status"},
                },
                {
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "content": "On branch main",
                    "is_error": False,
                },
            ],
        )

        with patch("src.session_miner._PROJECTS_DIR", projects_dir):
            result = mine_and_record("/Users/test/clean", self.db)

        self.assertEqual(result["sessions_scanned"], 1)
        self.assertEqual(result["commands_found"], 1)
        self.assertEqual(result["patterns_found"], 0)
        self.assertEqual(result["learnings_recorded"], 0)


if __name__ == "__main__":
    unittest.main()
