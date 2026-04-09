#!/usr/bin/env python3
"""Verify documentation stays in sync with the actual codebase.

Checks:
  1. Component counts in README.md and CLAUDE.md match reality
  2. Every skill directory has an entry in the README skill table
  3. Every skill directory has a section in docs/commands.md (except 'do')
  4. Test count in README.md is not stale

Exit 0 if everything is in sync, exit 1 with a summary of drift.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def get_root() -> Path:
    """Return the repository root."""
    return Path(__file__).resolve().parent.parent


def count_dirs(path: Path) -> set[str]:
    """Return set of directory names under path."""
    if not path.is_dir():
        return set()
    return {d.name for d in path.iterdir() if d.is_dir() and not d.name.startswith(".")}


def count_py_files(path: Path) -> int:
    """Return count of .py files under path."""
    if not path.is_dir():
        return 0
    return len([f for f in path.iterdir() if f.suffix == ".py"])


def count_src_modules(path: Path) -> int:
    """Return count of .py modules (excluding __init__.py) under src/."""
    if not path.is_dir():
        return 0
    return len([f for f in path.iterdir() if f.suffix == ".py" and f.name != "__init__.py"])


def extract_readme_counts(readme: str) -> dict[str, int]:
    """Extract component counts from the README Components table."""
    counts = {}
    for match in re.finditer(
        r"\|\s*\*\*(\w[\w\s]*?)\*\*\s*\|\s*(\d+)",
        readme,
    ):
        label = match.group(1).strip().lower()
        counts[label] = int(match.group(2))
    return counts


def extract_claude_md_counts(text: str) -> dict[str, int]:
    """Extract component counts from CLAUDE.md architecture bullets."""
    counts = {}
    # Pattern: - **hooks/**: 10 Python files ...
    for match in re.finditer(
        r"-\s*\*\*(\w+)/?\*\*:\s*(\d+)",
        text,
    ):
        label = match.group(1).strip().lower()
        counts[label] = int(match.group(2))
    return counts


def extract_readme_skill_names(readme: str) -> set[str]:
    """Extract skill names from the README skill table."""
    names = set()
    for match in re.finditer(r"^\|\s*([\w-]+)\s*\|", readme, re.MULTILINE):
        name = match.group(1).strip()
        # Skip table headers, separator rows, and other tables
        if name.lower() in ("skill", "layer", "tool") or set(name) <= {"-"}:
            continue
        names.add(name)
    return names


def extract_commands_md_sections(text: str) -> set[str]:
    """Extract skill names from docs/commands.md section headings."""
    names = set()
    for match in re.finditer(r"^##\s+([\w-]+)\s+--", text, re.MULTILINE):
        name = match.group(1).strip()
        if name != "/do":
            names.add(name)
    return names


def extract_readme_test_count(readme: str) -> int | None:
    """Extract the test count from README."""
    match = re.search(r"(\d+)\s+tests\s+covering", readme)
    if match:
        return int(match.group(1))
    return None


def get_actual_test_count(root: Path) -> int | None:
    """Run pytest --collect-only to get actual test count."""
    try:
        result = subprocess.run(
            ["uv", "run", "python3", "-m", "pytest", "tests/", "--collect-only", "-q"],
            capture_output=True,
            text=True,
            cwd=root,
            timeout=30,
        )
        # Last line: "510 tests collected in 0.11s"
        for line in result.stdout.strip().splitlines():
            match = re.search(r"(\d+)\s+tests?\s+collected", line)
            if match:
                return int(match.group(1))
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def extract_readme_install_hook_count(readme: str) -> int | None:
    """Extract hook count from the installation section."""
    match = re.search(r"Register\s+(\d+)\s+hooks?\s+in", readme)
    if match:
        return int(match.group(1))
    return None


def main() -> int:
    root = get_root()
    errors: list[str] = []

    # Read doc files
    readme_path = root / "README.md"
    claude_md_path = root / "CLAUDE.md"
    commands_md_path = root / "docs" / "commands.md"

    readme = readme_path.read_text() if readme_path.exists() else ""
    claude_md = claude_md_path.read_text() if claude_md_path.exists() else ""
    commands_md = commands_md_path.read_text() if commands_md_path.exists() else ""

    # Actual counts
    skill_dirs = count_dirs(root / "skills")
    agent_files = (
        {f.stem for f in (root / "agents").iterdir() if f.suffix == ".md"}
        if (root / "agents").is_dir()
        else set()
    )
    hook_count = count_py_files(root / "hooks")
    src_count = count_src_modules(root / "src")

    # --- Check 1: README component counts ---
    readme_counts = extract_readme_counts(readme)

    expected = {
        "skills": len(skill_dirs),
        "agents": len(agent_files),
        "hooks": hook_count,
        "core library": src_count,
    }

    for label, actual in expected.items():
        documented = readme_counts.get(label)
        if documented is not None and documented != actual:
            errors.append(
                f"README.md Components table: {label} says {documented}, actual is {actual}"
            )

    # --- Check 2: CLAUDE.md counts ---
    claude_counts = extract_claude_md_counts(claude_md)

    claude_expected = {
        "src": src_count,
        "hooks": hook_count,
        "skills": len(skill_dirs),
        "agents": len(agent_files),
    }

    for label, actual in claude_expected.items():
        documented = claude_counts.get(label)
        if documented is not None and documented != actual:
            errors.append(f"CLAUDE.md: {label} says {documented}, actual is {actual}")

    # --- Check 3: README installation hook count ---
    install_hook_count = extract_readme_install_hook_count(readme)
    if install_hook_count is not None and install_hook_count != hook_count:
        errors.append(
            f"README.md Installation section: says {install_hook_count} hooks,"
            f" actual is {hook_count}"
        )

    # --- Check 4: Every skill dir has a README table entry ---
    readme_skills = extract_readme_skill_names(readme)
    # 'do' is a command, not listed in the skill table
    skill_dirs_for_table = skill_dirs - {"do"}

    missing_from_readme = skill_dirs_for_table - readme_skills
    if missing_from_readme:
        errors.append(
            f"README.md skill table missing entries for: {', '.join(sorted(missing_from_readme))}"
        )

    extra_in_readme = readme_skills - skill_dirs_for_table
    if extra_in_readme:
        extras = ", ".join(sorted(extra_in_readme))
        errors.append(f"README.md skill table has entries with no skill directory: {extras}")

    # --- Check 5: Every skill dir has a docs/commands.md section ---
    commands_sections = extract_commands_md_sections(commands_md)
    # 'do' and 'loop' have their own docs, not required in commands.md
    # Actually 'loop' IS in commands.md, and 'do' is the entry point section
    skill_dirs_for_commands = skill_dirs - {"do"}

    missing_from_commands = skill_dirs_for_commands - commands_sections
    if missing_from_commands:
        errors.append(
            f"docs/commands.md missing sections for: {', '.join(sorted(missing_from_commands))}"
        )

    extra_in_commands = commands_sections - skill_dirs_for_commands
    if extra_in_commands:
        extras = ", ".join(sorted(extra_in_commands))
        errors.append(f"docs/commands.md has sections with no skill directory: {extras}")

    # --- Check 6: Test count ---
    readme_test_count = extract_readme_test_count(readme)
    actual_test_count = get_actual_test_count(root)

    if (
        readme_test_count is not None
        and actual_test_count is not None
        and readme_test_count != actual_test_count
    ):
        errors.append(
            f"README.md test count says {readme_test_count}, actual is {actual_test_count}"
        )

    # --- Report ---
    if errors:
        print("Documentation drift detected:\n")
        for e in errors:
            print(f"  - {e}")
        print(f"\n{len(errors)} issue(s) found. Update docs to match the codebase.")
        return 1

    print("All documentation is in sync.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
