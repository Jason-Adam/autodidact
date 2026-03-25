"""Self-assessment module for circuit breaker HALF_OPEN diagnostics.

When the autonomous loop's circuit breaker enters HALF_OPEN, this module
provides structured self-assessment: parsing a delimited block from Claude's
output, scoring execution-phase dimensions, and producing an assessment
result that guides the next iteration.

Reuses DimensionScore and compute_ambiguity from src.interview.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.interview import AmbiguityScore, DimensionScore, compute_ambiguity

# Execution-phase dimensions with weights summing to 1.0
ASSESSMENT_DIMENSIONS: list[tuple[str, float]] = [
    ("blocker_id", 0.35),
    ("approach_viability", 0.30),
    ("scope_alignment", 0.20),
    ("unblocking_paths", 0.15),
]

# Below this threshold on approach_viability, inject a pivot directive
PIVOT_THRESHOLD = 0.5

_BLOCK_RE = re.compile(
    r"---SELF_ASSESSMENT---\s*\n(.*?)\n\s*---END_SELF_ASSESSMENT---",
    re.DOTALL,
)


@dataclass
class AssessmentResult:
    """Parsed and scored self-assessment from a HALF_OPEN iteration."""

    scores: list[DimensionScore]
    overall_clarity: float
    strategy_adjustment: str = ""

    @property
    def should_pivot(self) -> bool:
        """True when approach_viability is below the pivot threshold."""
        for s in self.scores:
            if s.name == "approach_viability":
                return s.clarity < PIVOT_THRESHOLD
        return False


def parse_assessment_block(text: str) -> dict[str, str] | None:
    """Extract key-value pairs from a ---SELF_ASSESSMENT--- block.

    Returns None if the block is not found.
    Expected format inside the block:
        blocker_id: 0.3 | description text
        approach_viability: 0.7 | still viable
        scope_alignment: 0.8 | on track
        unblocking_paths: 0.6 | two options identified
        strategy_adjustment: pivot to alternative approach
    """
    match = _BLOCK_RE.search(text)
    if not match:
        return None
    block = match.group(1).strip()
    result: dict[str, str] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        result[key.strip()] = value.strip()
    return result


def score_assessment(parsed: dict[str, str]) -> AssessmentResult:
    """Score a parsed assessment block against execution-phase dimensions.

    Each dimension value is expected as "float | justification" or just "float".
    """
    dim_scores: list[DimensionScore] = []
    for name, weight in ASSESSMENT_DIMENSIONS:
        raw = parsed.get(name, "0.0")
        # Split on pipe to separate score from justification
        parts = raw.split("|", 1)
        try:
            clarity = max(0.0, min(1.0, float(parts[0].strip())))
        except ValueError:
            clarity = 0.0
        justification = parts[1].strip() if len(parts) > 1 else ""
        dim_scores.append(
            DimensionScore(
                name=name,
                clarity=clarity,
                weight=weight,
                justification=justification,
            )
        )

    ambiguity: AmbiguityScore = compute_ambiguity(dim_scores)
    strategy = parsed.get("strategy_adjustment", "")

    return AssessmentResult(
        scores=dim_scores,
        overall_clarity=ambiguity.clarity,
        strategy_adjustment=strategy,
    )


def build_assessment_prompt() -> str:
    """Build the self-assessment prompt injected during HALF_OPEN iterations."""
    dim_list = ", ".join(f"{name} (weight {w})" for name, w in ASSESSMENT_DIMENSIONS)
    return (
        "CIRCUIT BREAKER HALF_OPEN: You have made no progress for 2+ iterations. "
        "Before continuing work, emit a self-assessment block:\n"
        "---SELF_ASSESSMENT---\n"
        f"Score each dimension 0.0-1.0: {dim_list}\n"
        "Format: dimension_name: score | justification\n"
        "strategy_adjustment: describe what to change\n"
        "---END_SELF_ASSESSMENT---"
    )
