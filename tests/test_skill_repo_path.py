"""Guard against the un-discoverable REPO_PATH placeholder in skill snippets.

Skills are globally installed and normally run inside an unrelated project, so
they cannot hardcode the autodidact repo path. Snippets must resolve `src/`
through the global install anchor ``~/.claude/autodidact`` (which carries a
``src`` symlink to the repo) instead of a ``REPO_PATH`` placeholder the agent
has no reliable way to substitute.

Regression for: research/plan reporting "documents.py persistence helper wasn't
found" and falling back to writing .planning/ directly.
"""

from __future__ import annotations

import re
import unittest
from collections.abc import Callable
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
ANCHOR = "os.path.expanduser('~/.claude/autodidact')"

# Read each skill doc once; every check below scans the cached text.
_SKILL_DOCS = {path: path.read_text() for path in sorted(SKILLS_DIR.glob("*/skill.md"))}


def _scan_lines(predicate: Callable[[str], bool]) -> list[str]:
    """Return `relpath:lineno: line` for every line matching `predicate`."""
    offenders = []
    for path, text in _SKILL_DOCS.items():
        for lineno, line in enumerate(text.splitlines(), 1):
            if predicate(line):
                offenders.append(f"{path.relative_to(SKILLS_DIR.parent)}:{lineno}: {line.strip()}")
    return offenders


class TestNoRepoPathPlaceholder(unittest.TestCase):
    def test_skills_dir_discovered(self) -> None:
        # Sanity: the glob must actually find skill files, else the other
        # assertions pass vacuously.
        self.assertTrue(_SKILL_DOCS, f"no skill.md files under {SKILLS_DIR}")

    def test_no_repo_path_placeholder(self) -> None:
        """No skill may contain the bare REPO_PATH placeholder."""
        offenders = _scan_lines(lambda line: "REPO_PATH" in line)
        self.assertEqual(
            offenders,
            [],
            "REPO_PATH placeholder is un-discoverable from non-autodidact projects; "
            f"use {ANCHOR} instead:\n" + "\n".join(offenders),
        )

    def test_sys_path_inserts_use_anchor(self) -> None:
        """Every sys.path.insert in a skill snippet must use the global anchor."""
        pattern = re.compile(r"sys\.path\.insert\(\s*0\s*,")
        offenders = _scan_lines(lambda line: bool(pattern.search(line)) and ANCHOR not in line)
        self.assertEqual(
            offenders,
            [],
            f"sys.path.insert in a skill must resolve src/ via {ANCHOR}:\n" + "\n".join(offenders),
        )

    def test_uv_run_project_reads_install_marker(self) -> None:
        """`uv run --project` cannot use the anchor (needs pyproject.toml);
        it must read the real repo_dir from the install marker."""
        offenders = [
            str(path.relative_to(SKILLS_DIR.parent))
            for path, text in _SKILL_DOCS.items()
            if "uv run --project" in text and ".installed" not in text
        ]
        self.assertEqual(
            offenders,
            [],
            "`uv run --project` must derive the repo dir from ~/.claude/autodidact/.installed "
            "(the anchor dir lacks pyproject.toml):\n" + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
