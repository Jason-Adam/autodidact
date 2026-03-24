"""Cost-ascending /do router.

Tiers 0-2 are deterministic (zero/low cost). Tier 3 signals to the
/do skill markdown to perform LLM-based classification.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RouterResult:
    skill: str
    confidence: float
    tier: int
    reasoning: str = ""


# ── Tier 0: Pattern Match ──────────────────────────────────────────────

_DIRECT_PATTERNS: list[tuple[str, str]] = [
    (r"^/?(do\s+)?interview\b", "plan"),  # consolidated into /plan (Clarify phase)
    (r"^/?(do\s+)?research\b", "plan"),  # consolidated into /plan (Research phase)
    (r"^/?(do\s+)?plan\b", "plan"),
    (r"^/?(do\s+)?fleet\b", "fleet"),
    (r"^/do\s+run\b", "run"),  # requires /do prefix to avoid matching "run the tests"
    (r"^/?run$", "run"),  # bare "run" with no arguments
    (r"^/?(do\s+)?marshal\b", "run"),  # legacy alias
    (r"^/?(do\s+)?campaign\b", "campaign"),
    (r"^/?(do\s+)?archon\b", "campaign"),  # legacy alias
    (r"^/?(do\s+)?learn\b", "learn"),
    (r"^/?(do\s+)?review\b", "review"),
    (r"^/?(do\s+)?handoff\b", "handoff"),
    (r"^/?(do\s+)?publish\b", "publish"),
    (r"^/?(do\s+)?forget\b", "forget"),
    (r"^/?(do\s+)?learn.?status\b", "learn_status"),
    (r"^/?(do\s+)?experiment\b", "experiment"),
]


def _tier0_pattern_match(prompt: str) -> RouterResult | None:
    """Regex match against known command patterns. Zero cost."""
    normalized = prompt.strip().lower()
    for pattern, skill in _DIRECT_PATTERNS:
        if re.match(pattern, normalized):
            return RouterResult(skill=skill, confidence=1.0, tier=0)
    return None


# ── Tier 1: Active State Check ─────────────────────────────────────────


def _tier1_active_state(cwd: str) -> RouterResult | None:
    """Check for active campaigns/fleet/run state. Zero cost."""
    if not cwd:
        return None

    planning = Path(cwd) / ".planning"

    # Active campaign?
    campaigns = planning / "campaigns"
    if campaigns.exists():
        for f in campaigns.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                if data.get("status") == "in_progress":
                    return RouterResult(
                        skill="campaign",
                        confidence=0.9,
                        tier=1,
                        reasoning=f"Active campaign: {data.get('name', f.stem)}",
                    )
            except (json.JSONDecodeError, KeyError):
                pass

    # Active run state?
    run_state = planning / "run_state.json"
    if run_state.exists():
        try:
            data = json.loads(run_state.read_text())
            if data.get("status") == "in_progress":
                return RouterResult(
                    skill="run",
                    confidence=0.9,
                    tier=1,
                    reasoning="Active run sequence",
                )
        except (json.JSONDecodeError, KeyError):
            pass

    # Active fleet?
    fleet_state = planning / "fleet" / "active.json"
    if fleet_state.exists():
        try:
            data = json.loads(fleet_state.read_text())
            if data.get("status") == "in_progress":
                return RouterResult(
                    skill="fleet",
                    confidence=0.9,
                    tier=1,
                    reasoning="Active fleet session",
                )
        except (json.JSONDecodeError, KeyError):
            pass

    return None


# ── Tier 2: Keyword Heuristic ──────────────────────────────────────────

_KEYWORD_SCORES: dict[str, list[tuple[str, float]]] = {
    "fleet": [
        ("parallel", 0.4),
        ("worktree", 0.5),
        ("concurrent", 0.3),
        ("wave", 0.3),
        ("simultaneously", 0.3),
    ],
    "run": [
        ("steps", 0.3),
        ("phases", 0.3),
        ("sequence", 0.3),
        ("multi-step", 0.5),
        ("orchestrate", 0.3),
        ("execute", 0.2),
    ],
    "campaign": [
        ("campaign", 0.5),
        ("multi-session", 0.5),
        ("long-running", 0.4),
        ("persist", 0.2),
        ("continue tomorrow", 0.4),
    ],
    "plan": [
        ("plan", 0.5),
        ("design", 0.3),
        ("approach", 0.3),
        ("strategy", 0.3),
        ("implementation plan", 0.5),
        # Former /interview keywords
        ("clarify", 0.4),
        ("unclear", 0.4),
        ("ambiguous", 0.4),
        ("requirements", 0.3),
        ("scope", 0.2),
        # Former /research keywords
        ("explore", 0.3),
        ("investigate", 0.4),
        ("understand", 0.2),
        ("how does", 0.3),
        ("architecture", 0.2),
    ],
    "review": [
        ("review", 0.5),
        ("code review", 0.6),
        ("check quality", 0.4),
        ("audit", 0.3),
        ("inspect", 0.3),
    ],
    "handoff": [
        ("handoff", 0.6),
        ("hand off", 0.6),
        ("transfer", 0.3),
        ("session summary", 0.4),
        ("context transfer", 0.5),
    ],
    "experiment": [
        ("experiment", 0.5),
        ("optimize", 0.4),
        ("benchmark", 0.3),
        ("metric", 0.3),
        ("iterate", 0.2),
        ("try different", 0.3),
        ("improve performance", 0.4),
    ],
}


def _tier2_keyword_heuristic(prompt: str) -> RouterResult | None:
    """Score prompt against keyword tables. Low cost."""
    normalized = prompt.strip().lower()
    best_skill = ""
    best_score = 0.0

    for skill, keywords in _KEYWORD_SCORES.items():
        score = sum(weight for kw, weight in keywords if kw in normalized)
        if score > best_score:
            best_score = score
            best_skill = skill

    if best_score >= 0.6:
        return RouterResult(
            skill=best_skill,
            confidence=min(best_score, 1.0),
            tier=2,
            reasoning=f"Keyword match: {best_skill} (score: {best_score:.2f})",
        )
    return None


# ── Public API ──────────────────────────────────────────────────────────


def classify(prompt: str, cwd: str = "") -> RouterResult:
    """Cost-ascending classification. Tiers 0-2 are deterministic.

    Tier 3 returns skill="classify" to signal that LLM classification
    is needed (handled by the /do skill markdown).
    """
    # Tier 0: Pattern match
    result = _tier0_pattern_match(prompt)
    if result:
        return result

    # Tier 1: Active state
    result = _tier1_active_state(cwd)
    if result:
        return result

    # Tier 2: Keyword heuristic
    result = _tier2_keyword_heuristic(prompt)
    if result:
        return result

    # Tier 3: Signal for LLM classification
    return RouterResult(
        skill="classify",
        confidence=0.0,
        tier=3,
        reasoning="No deterministic match; LLM classification needed",
    )
