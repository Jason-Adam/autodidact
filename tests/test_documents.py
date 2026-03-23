"""Tests for document persistence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.documents import (
    _slugify,
    generate_filename,
    generate_frontmatter,
    get_latest_plan,
    list_documents,
    load_document,
    save_document,
)


class TestSlugify(unittest.TestCase):

    def test_basic(self) -> None:
        self.assertEqual(_slugify("Rate Limiting API"), "rate-limiting-api")

    def test_special_chars(self) -> None:
        self.assertEqual(_slugify("What's the auth flow?"), "whats-the-auth-flow")

    def test_multiple_spaces(self) -> None:
        self.assertEqual(_slugify("too   many   spaces"), "too-many-spaces")

    def test_truncation(self) -> None:
        long = "a" * 100
        result = _slugify(long, max_length=10)
        self.assertEqual(len(result), 10)

    def test_empty(self) -> None:
        self.assertEqual(_slugify(""), "")


class TestGenerateFilename(unittest.TestCase):

    def test_format(self) -> None:
        filename = generate_filename("Rate Limiting")
        self.assertRegex(filename, r"^\d{4}-\d{2}-\d{2}-rate-limiting\.md$")

    def test_empty_topic(self) -> None:
        filename = generate_filename("")
        self.assertIn("untitled", filename)


class TestGenerateFrontmatter(unittest.TestCase):

    def test_contains_required_fields(self) -> None:
        fm = generate_frontmatter("Test Topic")
        self.assertIn("---", fm)
        self.assertIn("type: research", fm)
        self.assertIn('topic: "Test Topic"', fm)
        self.assertIn("status: complete", fm)
        self.assertIn("last_updated_by: autodidact", fm)

    def test_custom_tags(self) -> None:
        fm = generate_frontmatter("Test", tags=["api", "auth"])
        self.assertIn("tags: [api, auth]", fm)


class TestSaveAndLoad(unittest.TestCase):

    def test_save_research_has_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = save_document(
                "# Research\n\nFindings here.",
                doc_type="research",
                topic="Auth Flow",
                cwd=tmpdir,
            )
            self.assertTrue(path.exists())
            content = load_document(path)
            self.assertIn("---", content)
            self.assertIn("type: research", content)
            self.assertIn("# Research", content)

    def test_save_plan_no_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = save_document(
                "# Plan\n\n## Phase 1",
                doc_type="plans",
                topic="Rate Limiting",
                cwd=tmpdir,
            )
            self.assertTrue(path.exists())
            content = load_document(path)
            self.assertTrue(content.startswith("# Plan"))
            self.assertNotIn("type: research", content)

    def test_save_creates_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = save_document("test", doc_type="research", topic="test", cwd=tmpdir)
            self.assertTrue((Path(tmpdir) / ".planning" / "research").is_dir())
            self.assertTrue(path.exists())

    def test_invalid_doc_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(ValueError):
                save_document("test", doc_type="invalid", topic="test", cwd=tmpdir)


class TestListDocuments(unittest.TestCase):

    def test_list_returns_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_document("doc1", doc_type="plans", topic="first", cwd=tmpdir)
            save_document("doc2", doc_type="plans", topic="second", cwd=tmpdir)
            docs = list_documents(tmpdir, "plans")
            self.assertEqual(len(docs), 2)
            # Newest first
            self.assertIn("second", docs[0].name)

    def test_list_empty_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            docs = list_documents(tmpdir, "plans")
            self.assertEqual(docs, [])


class TestGetLatest(unittest.TestCase):

    def test_get_latest_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_document("old", doc_type="plans", topic="old-plan", cwd=tmpdir)
            save_document("new", doc_type="plans", topic="new-plan", cwd=tmpdir)
            latest = get_latest_plan(tmpdir)
            self.assertIsNotNone(latest)
            assert latest is not None
            self.assertIn("new-plan", latest.name)

    def test_get_latest_plan_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertIsNone(get_latest_plan(tmpdir))


if __name__ == "__main__":
    unittest.main()
