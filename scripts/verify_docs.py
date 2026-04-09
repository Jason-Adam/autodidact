#!/usr/bin/env python3
"""Verify documentation stays in sync with the actual codebase.

Checks:
  1. Component counts in README.md and CLAUDE.md match reality
  2. Every skill directory has an entry in the README skill table
  3. Every skill directory has a section in docs/commands.md (except 'do')
  4. Test count in README.md is not stale

Exit 0 if everything is in sync, exit 1 with a summary of drift.
"""

import re
import subprocess
import sys
from pathlib import Path


def get_root() -> Path:
    """Return the repository root."""
    return Path(__file__).resolve().parent.parent


def dir_names(path: Path) -> set[str]:
    """Return set of directory names under path."""
    if not path.is_dir():
        return set()
    return {d.name for d in path.iterdir() if d.is_dir() and not d.name.startswith((".", "__"))}


def count_py_files(path: Path, *, exclude: set[str] | None = None) -> int:
    """Return count of .py files under path, optionally excluding names."""
    if not path.is_dir():
        return 0
    exclude = exclude or set()
    return len([f for f in path.iterdir() if f.suffix == ".py" and f.name not in exclude])


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
        if name.lower() in ("skill", "layer", "tool") or set(name) <= {"-"}:
            continue
        names.add(name)
    return names


def extract_commands_md_sections(text: str) -> set[str]:
    """Extract skill names from docs/commands.md section headings."""
    names = set()
    for match in re.finditer(r"^##\s+([\w-]+)\s+--", text, re.MULTILINE):
        names.add(match.group(1).strip())
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
        match = re.search(r"(\d+)\s+tests?\s+collected", result.stdout)
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


def _check_counts(
    errors: list[str],
    source: str,
    documented: dict[str, int],
    expected: dict[str, int],
) -> None:
    """Check documented counts against expected, flagging mismatches and missing."""
    for label, actual in expected.items():
        doc_val = documented.get(label)
        if doc_val is None:
            errors.append(f"{source}: missing entry for {label} (actual is {actual})")
        elif doc_val != actual:
            errors.append(f"{source}: {label} says {doc_val}, actual is {actual}")


def main() -> int:
    root = get_root()
    errors: list[str] = []

    readme_path = root / "README.md"
    claude_md_path = root / "CLAUDE.md"
    commands_md_path = root / "docs" / "commands.md"

    readme = readme_path.read_text() if readme_path.exists() else ""
    claude_md = claude_md_path.read_text() if claude_md_path.exists() else ""
    commands_md = commands_md_path.read_text() if commands_md_path.exists() else ""

    # Actual counts
    skill_dirs = dir_names(root / "skills")
    agent_files = (
        {f.stem for f in (root / "agents").iterdir() if f.suffix == ".md"}
        if (root / "agents").is_dir()
        else set()
    )
    hook_count = count_py_files(root / "hooks")
    src_count = count_py_files(root / "src", exclude={"__init__.py"})

    # --- Check 1: README component counts ---
    _check_counts(
        errors,
        "README.md Components table",
        extract_readme_counts(readme),
        {
            "skills": len(skill_dirs),
            "agents": len(agent_files),
            "hooks": hook_count,
            "core library": src_count,
        },
    )

    # --- Check 2: CLAUDE.md counts ---
    _check_counts(
        errors,
        "CLAUDE.md",
        extract_claude_md_counts(claude_md),
        {
            "src": src_count,
            "hooks": hook_count,
            "skills": len(skill_dirs),
            "agents": len(agent_files),
        },
    )

    # --- Check 3: README installation hook count ---
    install_hook_count = extract_readme_install_hook_count(readme)
    if install_hook_count is not None and install_hook_count != hook_count:
        errors.append(
            f"README.md Installation section: says {install_hook_count} hooks,"
            f" actual is {hook_count}"
        )

    # --- Check 4: Every skill dir has a README table entry ---
    readme_skills = extract_readme_skill_names(readme)
    # 'do' is the router entry point, not listed in the skill table
    skill_dirs_for_docs = skill_dirs - {"do"}

    missing_from_readme = skill_dirs_for_docs - readme_skills
    if missing_from_readme:
        errors.append(
            f"README.md skill table missing entries for: {', '.join(sorted(missing_from_readme))}"
        )

    extra_in_readme = readme_skills - skill_dirs_for_docs
    if extra_in_readme:
        extras = ", ".join(sorted(extra_in_readme))
        errors.append(f"README.md skill table has entries with no skill directory: {extras}")

    # --- Check 5: Every skill dir has a docs/commands.md section ---
    commands_sections = extract_commands_md_sections(commands_md)

    missing_from_commands = skill_dirs_for_docs - commands_sections
    if missing_from_commands:
        errors.append(
            f"docs/commands.md missing sections for: {', '.join(sorted(missing_from_commands))}"
        )

    extra_in_commands = commands_sections - skill_dirs_for_docs
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
