"""Tests for _tee_output in hooks/post_tool_use_failure.py."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure the repo root is on the path so hooks.post_tool_use_failure is importable
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from hooks.post_tool_use_failure import _TEE_MAX_FILES, _TEE_MIN_BYTES, _tee_output  # noqa: E402


class TestTeeOutputSmallOutput(unittest.TestCase):
    """_tee_output returns None when output is below the minimum size."""

    def test_returns_none_for_small_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _tee_output("Bash", "x" * (_TEE_MIN_BYTES - 1), tmpdir)
            self.assertIsNone(result)

    def test_returns_none_for_empty_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _tee_output("Bash", "", tmpdir)
            self.assertIsNone(result)

    def test_returns_none_for_exactly_499_bytes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _tee_output("Bash", "a" * 499, tmpdir)
            self.assertIsNone(result)


class TestTeeOutputWritesFile(unittest.TestCase):
    """_tee_output writes a file and returns a hint for large outputs."""

    def test_writes_file_and_returns_hint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = "E" * 600
            result = _tee_output("Bash", output, tmpdir)

            self.assertIsNotNone(result)
            assert result is not None
            self.assertIn(".planning/tee/", result)
            self.assertIn("Bash", result)
            self.assertTrue(result.startswith("[full error output: .planning/tee/"))
            self.assertTrue(result.endswith("]"))

            # Verify file was actually written
            tee_dir = Path(tmpdir) / ".planning" / "tee"
            logs = list(tee_dir.glob("*.log"))
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].read_text(), output)

    def test_creates_tee_directory_if_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tee_dir = Path(tmpdir) / ".planning" / "tee"
            self.assertFalse(tee_dir.exists())

            _tee_output("Edit", "x" * 600, tmpdir)

            self.assertTrue(tee_dir.exists())

    def test_hint_contains_tool_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _tee_output("MyTool", "y" * 600, tmpdir)
            self.assertIsNotNone(result)
            assert result is not None
            self.assertIn("MyTool", result)

    def test_exactly_500_bytes_triggers_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _tee_output("Bash", "z" * 500, tmpdir)
            self.assertIsNotNone(result)


class TestTeeOutputRotation(unittest.TestCase):
    """_tee_output rotates files to keep at most _TEE_MAX_FILES."""

    def test_rotation_keeps_only_max_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tee_dir = Path(tmpdir) / ".planning" / "tee"
            tee_dir.mkdir(parents=True)

            # Pre-populate with _TEE_MAX_FILES existing log files, each with
            # distinct mtime so sorting is deterministic
            for i in range(_TEE_MAX_FILES):
                f = tee_dir / f"100000{i:02d}_OldTool.log"
                f.write_text("old")
                mtime = 1000000 + i
                os.utime(f, (mtime, mtime))

            # Adding one more should trigger rotation
            output = "N" * 600
            _tee_output("NewTool", output, tmpdir)

            remaining = list(tee_dir.glob("*.log"))
            self.assertEqual(len(remaining), _TEE_MAX_FILES)

    def test_rotation_deletes_oldest_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tee_dir = Path(tmpdir) / ".planning" / "tee"
            tee_dir.mkdir(parents=True)

            # Create _TEE_MAX_FILES files with known names and ordered mtimes
            for i in range(_TEE_MAX_FILES):
                f = tee_dir / f"1000000{i:02d}_OldTool.log"
                f.write_text("old")
                mtime = 1000000 + i
                os.utime(f, (mtime, mtime))

            # The oldest file (index 0) should be deleted after adding one more
            oldest = tee_dir / "100000000_OldTool.log"
            self.assertTrue(oldest.exists())

            _tee_output("NewTool", "N" * 600, tmpdir)

            self.assertFalse(oldest.exists())


class TestTeeOutputTruncation(unittest.TestCase):
    """_tee_output truncates files larger than 1MB."""

    def test_truncates_large_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            large_output = "X" * (1024 * 1024 + 5000)
            _tee_output("Bash", large_output, tmpdir)

            tee_dir = Path(tmpdir) / ".planning" / "tee"
            logs = list(tee_dir.glob("*.log"))
            self.assertEqual(len(logs), 1)
            written_bytes = len(logs[0].read_bytes())
            self.assertLessEqual(written_bytes, 1024 * 1024)

    def test_small_output_not_truncated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = "Y" * 1000
            _tee_output("Bash", output, tmpdir)

            tee_dir = Path(tmpdir) / ".planning" / "tee"
            logs = list(tee_dir.glob("*.log"))
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].read_text(), output)


class TestTeeOutputGracefulFailure(unittest.TestCase):
    """_tee_output returns None and raises no exception when writes fail."""

    def test_returns_none_when_mkdir_fails(self):
        # Use a cwd that is a file (so mkdir will fail with OSError)
        with tempfile.NamedTemporaryFile() as tmpfile:
            # tmpfile.name is a file, so mkdir on a subpath will fail
            result = _tee_output("Bash", "E" * 600, tmpfile.name)
            # Should return None without raising
            self.assertIsNone(result)

    def test_no_exception_on_write_failure(self):
        """Patch Path.write_text to raise OSError and verify graceful handling."""
        with tempfile.TemporaryDirectory() as tmpdir:
            original_write_text = Path.write_text

            def failing_write_text(self, *args, **kwargs):
                if ".planning/tee" in str(self):
                    raise OSError("disk full")
                return original_write_text(self, *args, **kwargs)

            with patch.object(Path, "write_text", failing_write_text):
                try:
                    _tee_output("Bash", "E" * 600, tmpdir)
                    # If we get here without exception, the test passes
                except OSError:
                    self.fail("_tee_output raised OSError instead of suppressing it")


if __name__ == "__main__":
    unittest.main()
