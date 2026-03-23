"""Document persistence for research and plan outputs.

Handles filename generation, YAML frontmatter, saving/loading documents
to .planning/{research|plans}/ directories.
"""

from __future__ import annotations

import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def _slugify(text: str, max_length: int = 50) -> str:
    """Convert text to a kebab-case slug suitable for filenames."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug[:max_length].rstrip("-")


def _git_info(cwd: str) -> dict[str, str]:
    """Get current git commit, branch, and remote info."""
    info: dict[str, str] = {"commit": "", "branch": "", "repository": ""}
    if not cwd:
        return info
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            info["commit"] = result.stdout.strip()

        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            info["branch"] = result.stdout.strip()

        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            # Extract org/repo from git URL
            match = re.search(r"[:/]([^/]+/[^/.]+?)(?:\.git)?$", url)
            if match:
                info["repository"] = match.group(1)
    except (subprocess.TimeoutExpired, OSError):
        pass
    return info


def _current_user() -> str:
    """Get the current system username."""
    try:
        result = subprocess.run(
            ["whoami"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else "autodidact"
    except (subprocess.TimeoutExpired, OSError):
        return "autodidact"


def generate_filename(topic: str) -> str:
    """Generate a document filename: YYYY-MM-DD-{slug}.md"""
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    slug = _slugify(topic)
    if not slug:
        slug = "untitled"
    return f"{date_str}-{slug}.md"


def generate_frontmatter(topic: str, cwd: str = "", tags: list[str] | None = None) -> str:
    """Generate YAML frontmatter for research documents.

    Plans do NOT get frontmatter (flat markdown per convention).
    """
    now = datetime.now(UTC)
    git = _git_info(cwd)

    if tags is None:
        tags = ["research", "codebase"]

    tag_str = ", ".join(tags)
    lines = [
        "---",
        f'date: "{now.isoformat()}"',
        "type: research",
        f"git_commit: {git['commit']}",
        f"branch: {git['branch']}",
        f"repository: {git['repository']}",
        f'topic: "{topic}"',
        f"tags: [{tag_str}]",
        "status: complete",
        f'last_updated: "{now.strftime("%Y-%m-%d")}"',
        "last_updated_by: autodidact",
        "---",
        "",
    ]
    return "\n".join(lines)


def save_document(
    content: str,
    doc_type: str,
    topic: str,
    cwd: str,
) -> Path:
    """Save a document to .planning/{research|plans}/.

    Research documents get YAML frontmatter prepended.
    Plan documents are saved as-is (flat markdown).

    Returns the path to the saved file.
    """
    if doc_type not in ("research", "plans"):
        raise ValueError(f"doc_type must be 'research' or 'plans', got '{doc_type}'")

    target_dir = Path(cwd) / ".planning" / doc_type
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = generate_filename(topic)
    filepath = target_dir / filename

    if doc_type == "research":
        frontmatter = generate_frontmatter(topic, cwd)
        full_content = frontmatter + content
    else:
        full_content = content

    filepath.write_text(full_content)
    return filepath


def load_document(path: Path) -> str:
    """Load a document from disk."""
    return path.read_text()


def list_documents(cwd: str, doc_type: str) -> list[Path]:
    """List all documents of a given type, sorted by modification time (newest first)."""
    target_dir = Path(cwd) / ".planning" / doc_type
    if not target_dir.exists():
        return []
    docs = sorted(target_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return docs


def get_latest_plan(cwd: str) -> Path | None:
    """Get the most recent plan document, if any."""
    plans = list_documents(cwd, "plans")
    return plans[0] if plans else None


def get_latest_research(cwd: str) -> Path | None:
    """Get the most recent research document, if any."""
    docs = list_documents(cwd, "research")
    return docs[0] if docs else None
