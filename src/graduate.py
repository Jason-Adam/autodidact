"""Graduate high-confidence learnings to the Claude Code memory system.

Writes memory files to ~/.claude/projects/{encoded-path}/memory/ and updates
MEMORY.md index. Error-signature learnings stay in the DB (surfaced via FTS5).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Maximum entries in MEMORY.md before we stop graduating to avoid overflow.
# Claude Code truncates after ~200 lines; leave headroom for manual entries.
MEMORY_INDEX_CAP = 150


def _encode_project_path(project_path: str) -> str:
    """Encode a project path the way Claude Code does: replace / with -."""
    return project_path.replace("/", "-")


def _memory_dir(project_path: str) -> Path:
    """Resolve the Claude Code memory directory for a project."""
    encoded = _encode_project_path(project_path)
    return Path.home() / ".claude" / "projects" / encoded / "memory"


def _sanitize_filename(text: str) -> str:
    """Turn a learning key into a safe filename slug."""
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:60]  # cap length


def _escape_yaml(text: str) -> str:
    """Escape a string for use inside YAML double-quoted scalars."""
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _count_memory_entries(memory_md: Path) -> int:
    """Count non-empty link entries in MEMORY.md."""
    if not memory_md.exists():
        return 0
    count = 0
    for line in memory_md.read_text().splitlines():
        if line.strip().startswith("- ["):
            count += 1
    return count


def _should_skip(candidate: dict[str, Any]) -> bool:
    """Error-signature learnings stay in DB — they're surfaced via FTS5 on demand."""
    return bool(candidate.get("error_signature"))


def _build_memory_content(candidate: dict[str, Any]) -> tuple[str, str, str]:
    """Build memory file content from a learning candidate.

    Returns (filename, description, file_content).
    """
    key = candidate["key"]
    topic = candidate["topic"]
    value = candidate["value"]

    slug = _sanitize_filename(key)
    filename = f"graduated_{slug}.md"
    value_preview = value[:80] + ("..." if len(value) > 80 else "")
    description = f"Graduated learning [{topic}/{key}]: {value_preview}"

    conf = candidate["confidence"]
    obs = candidate["observation_count"]

    safe_key = _escape_yaml(key)
    safe_desc = _escape_yaml(description[:120])

    content = f"""---
name: "{safe_key}"
description: "{safe_desc}"
type: feedback
---

{value}

**Why:** Validated by autodidact (confidence {conf:.2f}, {obs} observations).

**How to apply:** Apply this pattern when working in similar contexts.
"""
    return filename, description, content


def graduate_to_memory(
    candidates: list[dict[str, Any]],
    project_path: str,
) -> list[dict[str, Any]]:
    """Graduate eligible learnings to memory files.

    Returns list of dicts with 'id', 'key', and 'memory_path' for each
    successfully graduated learning. Skips error-signature learnings.
    """
    if not project_path or not candidates:
        return []

    mem_dir = _memory_dir(project_path)
    memory_md = mem_dir / "MEMORY.md"

    # Ensure memory directory exists
    mem_dir.mkdir(parents=True, exist_ok=True)

    # Ensure MEMORY.md exists with header
    if not memory_md.exists():
        memory_md.write_text("# Memory Index\n\n")

    # Check overflow before starting
    current_count = _count_memory_entries(memory_md)

    graduated: list[dict[str, Any]] = []
    new_entries: list[str] = []

    for candidate in candidates:
        if _should_skip(candidate):
            continue

        filename, description, content = _build_memory_content(candidate)
        memory_file = mem_dir / filename

        # Already-written files still count as graduated (idempotent)
        if memory_file.exists():
            graduated.append(
                {
                    "id": candidate["id"],
                    "key": candidate["key"],
                    "memory_path": str(memory_file),
                }
            )
            continue

        # Cap check applies only to new writes
        if current_count >= MEMORY_INDEX_CAP:
            break

        # Write memory file
        memory_file.write_text(content)

        # Collect MEMORY.md entry for batch append
        short_desc = description[:120]
        new_entries.append(f"- [{filename}]({filename}) — {short_desc}\n")

        current_count += 1
        graduated.append(
            {
                "id": candidate["id"],
                "key": candidate["key"],
                "memory_path": str(memory_file),
            }
        )

    # Batch-append all new entries to MEMORY.md (single write, not per-item)
    if new_entries:
        with open(memory_md, "a") as f:
            f.writelines(new_entries)

    return graduated
