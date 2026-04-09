"""Tests for the doc verification script."""

import unittest

from verify_docs import (
    extract_claude_md_counts,
    extract_commands_md_sections,
    extract_readme_counts,
    extract_readme_install_hook_count,
    extract_readme_skill_names,
    extract_readme_test_count,
)


class TestExtractReadmeCounts(unittest.TestCase):
    def test_extracts_all_component_counts(self):
        table = (
            "| **Core library** | 22 modules | ... |\n"
            "| **Hooks** | 10 | ... |\n"
            "| **Skills** | 18 | ... |\n"
            "| **Agents** | 13 | ... |\n"
            "| **Commands** | 1 | ... |\n"
        )
        counts = extract_readme_counts(table)
        self.assertEqual(counts["core library"], 22)
        self.assertEqual(counts["hooks"], 10)
        self.assertEqual(counts["skills"], 18)
        self.assertEqual(counts["agents"], 13)
        self.assertEqual(counts["commands"], 1)

    def test_empty_string(self):
        self.assertEqual(extract_readme_counts(""), {})


class TestExtractClaudeMdCounts(unittest.TestCase):
    def test_extracts_bullet_counts(self):
        text = (
            "- **src/**: 22-module flat Python stdlib library\n"
            "- **hooks/**: 10 Python files\n"
            "- **skills/**: 18 markdown skill definitions\n"
            "- **agents/**: 13 agent personas\n"
        )
        counts = extract_claude_md_counts(text)
        self.assertEqual(counts["src"], 22)
        self.assertEqual(counts["hooks"], 10)
        self.assertEqual(counts["skills"], 18)
        self.assertEqual(counts["agents"], 13)


class TestExtractReadmeSkillNames(unittest.TestCase):
    def test_extracts_skill_names(self):
        table = (
            "| Skill | Purpose | Docs |\n"
            "|-------|---------|------|\n"
            "| plan | Clarify pipeline | [ref](...) |\n"
            "| run | Single-session | [ref](...) |\n"
            "| learn-status | Stats | [ref](...) |\n"
        )
        names = extract_readme_skill_names(table)
        self.assertEqual(names, {"plan", "run", "learn-status"})

    def test_skips_separator_rows(self):
        table = "| Skill | Purpose |\n|-------|---------|\n| plan | test |\n"
        names = extract_readme_skill_names(table)
        self.assertNotIn("-------", names)
        self.assertNotIn("------", names)

    def test_skips_header_labels(self):
        table = "| Skill | Purpose |\n|-------|---------|\n| Layer | Count |\n| Tool | Required |\n"
        names = extract_readme_skill_names(table)
        self.assertEqual(names, set())


class TestExtractCommandsMdSections(unittest.TestCase):
    def test_extracts_section_names(self):
        text = (
            "## plan -- clarify, research, design\n\n"
            "## run -- single-session orchestration\n\n"
            "## debug -- structured debugging\n\n"
        )
        sections = extract_commands_md_sections(text)
        self.assertEqual(sections, {"plan", "run", "debug"})

    def test_ignores_non_skill_headings(self):
        text = "## Overview\n\nSome text.\n"
        sections = extract_commands_md_sections(text)
        self.assertEqual(sections, set())


class TestExtractReadmeTestCount(unittest.TestCase):
    def test_extracts_count(self):
        text = "510 tests covering the learning DB, confidence math..."
        self.assertEqual(extract_readme_test_count(text), 510)

    def test_returns_none_when_missing(self):
        self.assertIsNone(extract_readme_test_count("no test info here"))


class TestExtractReadmeInstallHookCount(unittest.TestCase):
    def test_extracts_count(self):
        text = "2. Register 10 hooks in `~/.claude/settings.json`"
        self.assertEqual(extract_readme_install_hook_count(text), 10)

    def test_returns_none_when_missing(self):
        self.assertIsNone(extract_readme_install_hook_count("no hooks mentioned"))


if __name__ == "__main__":
    unittest.main()
