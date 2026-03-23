"""Socratic interview engine and ambiguity scorer.

Tracks interview state, scores ambiguity across weighted dimensions,
and determines when requirements are clear enough to proceed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AMBIGUITY_THRESHOLD = 0.2  # Must be <= 0.2 to proceed (80%+ clarity)
MAX_ROUNDS = 5

# Brownfield detection: files that indicate an existing project
_PROJECT_INDICATORS = [
    "package.json", "pyproject.toml", "setup.py", "setup.cfg",
    "go.mod", "Cargo.toml", "pom.xml", "build.gradle",
    "Makefile", "CMakeLists.txt", "requirements.txt",
]

_PROJECT_DIRS = ["src", "lib", "app", "pkg", "internal"]


@dataclass
class DimensionScore:
    """Score for a single ambiguity dimension."""
    name: str
    clarity: float  # 0.0 (unclear) to 1.0 (crystal clear)
    weight: float
    justification: str = ""


@dataclass
class AmbiguityScore:
    """Overall ambiguity assessment."""
    overall: float  # 0.0 (clear) to 1.0 (ambiguous)
    dimensions: list[DimensionScore]
    is_ready: bool = False

    @property
    def clarity(self) -> float:
        return 1.0 - self.overall


@dataclass
class InterviewRound:
    """A single question-answer round."""
    round_number: int
    question: str
    answer: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class InterviewState:
    """Full interview state, serializable to JSON."""
    interview_id: str
    initial_context: str
    rounds: list[InterviewRound] = field(default_factory=list)
    is_brownfield: bool = False
    codebase_summary: str = ""
    ambiguity_score: float | None = None
    ambiguity_breakdown: dict[str, Any] | None = None
    status: str = "in_progress"  # in_progress | completed | aborted

    def to_dict(self) -> dict[str, Any]:
        return {
            "interview_id": self.interview_id,
            "initial_context": self.initial_context,
            "rounds": [
                {
                    "round_number": r.round_number,
                    "question": r.question,
                    "answer": r.answer,
                    "timestamp": r.timestamp,
                }
                for r in self.rounds
            ],
            "is_brownfield": self.is_brownfield,
            "codebase_summary": self.codebase_summary,
            "ambiguity_score": self.ambiguity_score,
            "ambiguity_breakdown": self.ambiguity_breakdown,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InterviewState:
        state = cls(
            interview_id=data["interview_id"],
            initial_context=data["initial_context"],
            is_brownfield=data.get("is_brownfield", False),
            codebase_summary=data.get("codebase_summary", ""),
            ambiguity_score=data.get("ambiguity_score"),
            ambiguity_breakdown=data.get("ambiguity_breakdown"),
            status=data.get("status", "in_progress"),
        )
        for r in data.get("rounds", []):
            state.rounds.append(InterviewRound(
                round_number=r["round_number"],
                question=r["question"],
                answer=r.get("answer"),
                timestamp=r.get("timestamp", ""),
            ))
        return state


def detect_brownfield(project_path: str) -> bool:
    """Check if a directory contains an existing project."""
    if not project_path:
        return False
    path = Path(project_path)
    if not path.is_dir():
        return False
    # Check for project indicator files
    for indicator in _PROJECT_INDICATORS:
        if (path / indicator).exists():
            return True
    # Check for project directories
    for dirname in _PROJECT_DIRS:
        if (path / dirname).is_dir():
            return True
    return False


def get_scoring_dimensions(is_brownfield: bool) -> list[tuple[str, float]]:
    """Return (dimension_name, weight) pairs for scoring."""
    if is_brownfield:
        return [
            ("scope", 0.30),
            ("constraints", 0.25),
            ("acceptance", 0.25),
            ("integration", 0.20),
        ]
    else:
        return [
            ("scope", 0.40),
            ("constraints", 0.30),
            ("acceptance", 0.30),
        ]


def compute_ambiguity(dimension_scores: list[DimensionScore]) -> AmbiguityScore:
    """Compute overall ambiguity from dimension scores.

    ambiguity = 1.0 - sum(clarity_i * weight_i)
    """
    weighted_clarity = sum(d.clarity * d.weight for d in dimension_scores)
    overall = max(0.0, min(1.0, 1.0 - weighted_clarity))
    return AmbiguityScore(
        overall=overall,
        dimensions=dimension_scores,
        is_ready=overall <= AMBIGUITY_THRESHOLD,
    )


def generate_clarification_targets(dimensions: list[DimensionScore]) -> list[str]:
    """Identify which dimensions need more clarity (below 0.8)."""
    targets = []
    for d in dimensions:
        if d.clarity < 0.8:
            targets.append(d.name)
    return targets


def generate_question_hints(weak_dimensions: list[str], is_brownfield: bool) -> list[str]:
    """Generate question suggestions for weak dimensions."""
    hints: list[str] = []
    for dim in weak_dimensions:
        if dim == "scope":
            hints.append("What specific problem are you solving?")
            hints.append("What is the primary deliverable?")
        elif dim == "constraints":
            hints.append("Are there technical constraints or limitations?")
            hints.append("What should be excluded from scope?")
        elif dim == "acceptance":
            hints.append("How will you know when this is done?")
            hints.append("What features are essential vs nice-to-have?")
        elif dim == "integration" and is_brownfield:
            hints.append("Which existing components should this integrate with?")
            hints.append("What patterns from the existing codebase must be followed?")
    return hints


def save_state(state: InterviewState, state_dir: Path | None = None) -> Path:
    """Persist interview state to disk."""
    if state_dir is None:
        state_dir = Path.home() / ".claude" / "autodidact" / "interviews"
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / f"interview_{state.interview_id}.json"
    path.write_text(json.dumps(state.to_dict(), indent=2))
    return path


def load_state(interview_id: str, state_dir: Path | None = None) -> InterviewState | None:
    """Load interview state from disk."""
    if state_dir is None:
        state_dir = Path.home() / ".claude" / "autodidact" / "interviews"
    path = state_dir / f"interview_{interview_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return InterviewState.from_dict(data)
