"""Tests for the graduation-to-memory system."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.graduate import (
    MEMORY_INDEX_CAP,
    _build_memory_content,
    _count_memory_entries,
    _encode_project_path,
    _escape_yaml,
    _sanitize_filename,
    _should_skip,
    graduate_to_memory,
)


class TestHelpers(unittest.TestCase):
    def test_encode_project_path(self) -> None:
        self.assertEqual(
            _encode_project_path("/Users/jason/code/myproject"),
            "-Users-jason-code-myproject",
        )

    def test_sanitize_filename(self) -> None:
        self.assertEqual(_sanitize_filename("my_key-name!"), "my_key_name")
        self.assertEqual(_sanitize_filename("UPPER Case"), "upper_case")
        # Long names get truncated
        long_name = "a" * 100
        self.assertLessEqual(len(_sanitize_filename(long_name)), 60)

    def test_escape_yaml_quotes(self) -> None:
        self.assertEqual(_escape_yaml('say "hello"'), 'say \\"hello\\"')

    def test_escape_yaml_newlines(self) -> None:
        self.assertEqual(_escape_yaml("line1\nline2"), "line1 line2")

    def test_escape_yaml_backslash(self) -> None:
        self.assertEqual(_escape_yaml("path\\to"), "path\\\\to")

    def test_should_skip_error_signature(self) -> None:
        self.assertTrue(_should_skip({"error_signature": "abc123"}))
        self.assertFalse(_should_skip({"error_signature": ""}))
        self.assertFalse(_should_skip({}))

    def test_count_memory_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            md = Path(tmpdir) / "MEMORY.md"
            md.write_text("# Index\n\n- [a.md](a.md) — desc\n- [b.md](b.md) — desc\n")
            self.assertEqual(_count_memory_entries(md), 2)

    def test_count_memory_entries_missing_file(self) -> None:
        self.assertEqual(_count_memory_entries(Path("/nonexistent/MEMORY.md")), 0)


class TestBuildMemoryContent(unittest.TestCase):
    def test_produces_frontmatter(self) -> None:
        candidate = {
            "key": "always_check_types",
            "topic": "python",
            "value": "Always run mypy before committing.",
            "confidence": 0.95,
            "observation_count": 7,
        }
        filename, description, content = _build_memory_content(candidate)
        self.assertEqual(filename, "graduated_always_check_types.md")
        self.assertIn("python/always_check_types", description)
        self.assertIn("---", content)
        self.assertIn("type: feedback", content)
        self.assertIn("Always run mypy", content)
        self.assertIn("0.95", content)
        self.assertIn("7 observations", content)

    def test_escapes_yaml_special_chars(self) -> None:
        candidate = {
            "key": 'use "quotes" carefully',
            "topic": "style",
            "value": "Avoid unescaped quotes in YAML.",
            "confidence": 0.92,
            "observation_count": 6,
        }
        _, _, content = _build_memory_content(candidate)
        # The frontmatter name field should have escaped quotes
        self.assertIn('\\"quotes\\"', content)
        # Should still be valid YAML structure (no unescaped inner quotes)
        lines = content.split("\n")
        name_line = [ln for ln in lines if ln.startswith("name:")][0]
        # Count quotes — should be balanced (opening + closing + escaped pairs)
        self.assertTrue(name_line.startswith('name: "'))
        self.assertTrue(name_line.endswith('"'))


class TestGraduateToMemory(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.project_path = f"{self.tmpdir}/fakerepo"
        Path(self.project_path).mkdir(parents=True)
        self.mem_dir = Path(self.tmpdir) / "memory"
        self._patcher = patch("src.graduate._memory_dir", return_value=self.mem_dir)
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()

    def _make_candidate(
        self,
        *,
        id: int = 1,
        key: str = "test_key",
        topic: str = "test",
        value: str = "Test value",
        confidence: float = 0.95,
        observation_count: int = 7,
        error_signature: str = "",
    ) -> dict:
        return {
            "id": id,
            "key": key,
            "topic": topic,
            "value": value,
            "confidence": confidence,
            "observation_count": observation_count,
            "error_signature": error_signature,
        }

    def test_skips_error_signature_candidates(self) -> None:
        candidates = [self._make_candidate(error_signature="hash123")]
        results = graduate_to_memory(candidates, self.project_path)
        self.assertEqual(results, [])

    def test_empty_candidates(self) -> None:
        self.assertEqual(graduate_to_memory([], self.project_path), [])

    def test_empty_project_path(self) -> None:
        candidates = [self._make_candidate()]
        self.assertEqual(graduate_to_memory(candidates, ""), [])

    def test_writes_memory_file_and_index(self) -> None:
        candidates = [self._make_candidate(key="use_ruff")]
        results = graduate_to_memory(candidates, self.project_path)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["key"], "use_ruff")

        # Memory file exists
        memory_file = self.mem_dir / "graduated_use_ruff.md"
        self.assertTrue(memory_file.exists())
        content = memory_file.read_text()
        self.assertIn("type: feedback", content)
        self.assertIn("Test value", content)

        # MEMORY.md updated
        memory_md = self.mem_dir / "MEMORY.md"
        self.assertTrue(memory_md.exists())
        index_content = memory_md.read_text()
        self.assertIn("graduated_use_ruff.md", index_content)

    def test_skips_existing_memory_file(self) -> None:
        """If a memory file already exists, still return it but don't overwrite."""
        self.mem_dir.mkdir(parents=True)
        (self.mem_dir / "MEMORY.md").write_text("# Memory Index\n\n")

        # Pre-create the memory file
        existing = self.mem_dir / "graduated_existing_key.md"
        existing.write_text("original content")

        candidates = [self._make_candidate(key="existing_key")]
        results = graduate_to_memory(candidates, self.project_path)

        self.assertEqual(len(results), 1)
        # File should NOT be overwritten
        self.assertEqual(existing.read_text(), "original content")

    def test_existing_file_graduated_even_at_cap(self) -> None:
        """Already-written files are returned regardless of cap."""
        self.mem_dir.mkdir(parents=True)

        # Fill MEMORY.md to cap
        lines = ["# Memory Index\n\n"]
        for i in range(MEMORY_INDEX_CAP):
            lines.append(f"- [f{i}.md](f{i}.md) — desc\n")
        (self.mem_dir / "MEMORY.md").write_text("".join(lines))

        # Pre-create the memory file
        existing = self.mem_dir / "graduated_at_cap.md"
        existing.write_text("already here")

        candidates = [self._make_candidate(key="at_cap")]
        results = graduate_to_memory(candidates, self.project_path)

        # Should still be returned — exists check comes before cap check
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["key"], "at_cap")

    def test_respects_memory_index_cap(self) -> None:
        """Stop graduating when MEMORY.md hits the cap."""
        self.mem_dir.mkdir(parents=True)

        # Pre-fill MEMORY.md to cap
        lines = ["# Memory Index\n\n"]
        for i in range(MEMORY_INDEX_CAP):
            lines.append(f"- [f{i}.md](f{i}.md) — desc\n")
        (self.mem_dir / "MEMORY.md").write_text("".join(lines))

        candidates = [self._make_candidate(id=1, key="overflow_key")]
        results = graduate_to_memory(candidates, self.project_path)

        # Should be empty — cap reached and file doesn't already exist
        self.assertEqual(results, [])

    def test_multiple_candidates_mixed(self) -> None:
        """Mix of error-signature (skipped) and normal (graduated) candidates."""
        candidates = [
            self._make_candidate(id=1, key="normal_one"),
            self._make_candidate(id=2, key="error_one", error_signature="hash"),
            self._make_candidate(id=3, key="normal_two"),
        ]
        results = graduate_to_memory(candidates, self.project_path)

        self.assertEqual(len(results), 2)
        keys = [r["key"] for r in results]
        self.assertIn("normal_one", keys)
        self.assertIn("normal_two", keys)
        self.assertNotIn("error_one", keys)

    def test_batch_appends_to_memory_md(self) -> None:
        """Multiple new entries should be appended in one write."""
        candidates = [
            self._make_candidate(id=1, key="first"),
            self._make_candidate(id=2, key="second"),
        ]
        results = graduate_to_memory(candidates, self.project_path)

        self.assertEqual(len(results), 2)
        memory_md = self.mem_dir / "MEMORY.md"
        content = memory_md.read_text()
        self.assertIn("graduated_first.md", content)
        self.assertIn("graduated_second.md", content)


if __name__ == "__main__":
    unittest.main()
