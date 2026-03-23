"""HANDOFF block generator.

Produces compact state transfer blocks (<150 words, 3-5 bullets)
for communication between skills, agents, and sessions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HandoffBlock:
    """A compact state transfer between skills/agents/sessions."""

    source: str  # skill or agent that produced this
    summary: str  # 1-line summary
    completed: list[str]  # what was done
    decisions: list[str]  # key decisions made
    next_steps: list[str]  # what should happen next
    context_files: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.context_files is None:
            self.context_files = []

    def format(self) -> str:
        """Format as a HANDOFF block (<150 words target)."""
        lines = [f"HANDOFF: {self.source} — {self.summary}"]

        if self.completed:
            lines.append("- Done: " + "; ".join(self.completed[:3]))
        if self.decisions:
            lines.append("- Decisions: " + "; ".join(self.decisions[:2]))
        if self.next_steps:
            lines.append("- Next: " + "; ".join(self.next_steps[:3]))
        if self.context_files:
            lines.append("- Files: " + ", ".join(self.context_files[:5]))

        return "\n".join(lines)

    def word_count(self) -> int:
        return len(self.format().split())
