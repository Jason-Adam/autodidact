"""Confidence scoring logic for the autodidact learning system.

Provides pure functions for confidence calculations used by hooks and the DB.
"""

from __future__ import annotations

# ── Thresholds ──────────────────────────────────────────────────────────

BOOST_DEFAULT = 0.15
DECAY_DEFAULT = 0.10
TIME_DECAY_RATE = 0.01  # per day since last_seen
CONFIDENCE_FLOOR = 0.1  # time_decay never goes below this
CONFIDENCE_CAP = 1.0
CONFIDENCE_MIN = 0.0

GRADUATION_CONFIDENCE = 0.9
GRADUATION_MIN_OBSERVATIONS = 5

PRUNE_CONFIDENCE = 0.1
PRUNE_MAX_AGE_DAYS = 90

INJECTION_MIN_CONFIDENCE = 0.3
INJECTION_LIMIT = 5


# ── Pure Functions ──────────────────────────────────────────────────────


def boost(current: float, amount: float = BOOST_DEFAULT) -> float:
    """Increase confidence, capped at 1.0."""
    return min(current + amount, CONFIDENCE_CAP)


def decay(current: float, amount: float = DECAY_DEFAULT) -> float:
    """Decrease confidence, floored at 0.0."""
    return max(current - amount, CONFIDENCE_MIN)


def time_decay(current: float, days_since_last_seen: int, rate: float = TIME_DECAY_RATE) -> float:
    """Apply time-based decay. Never drops below CONFIDENCE_FLOOR."""
    if days_since_last_seen <= 0:
        return current
    return max(current - (days_since_last_seen * rate), CONFIDENCE_FLOOR)


def is_graduation_eligible(confidence: float, observation_count: int) -> bool:
    """Check if a learning is ready to be promoted to a skill/CLAUDE.md."""
    return confidence >= GRADUATION_CONFIDENCE and observation_count >= GRADUATION_MIN_OBSERVATIONS


def is_prunable(confidence: float, days_since_last_seen: int) -> bool:
    """Check if a learning should be deleted."""
    return confidence < PRUNE_CONFIDENCE and days_since_last_seen > PRUNE_MAX_AGE_DAYS


def initial_confidence(source: str) -> float:
    """Determine starting confidence based on knowledge source."""
    return {
        "user_teach": 0.7,
        "error_learner": 0.5,
        "subagent_discovery": 0.4,
        "routing_gap": 0.3,
    }.get(source, 0.5)


def initial_confidence_for_outcome(outcome: str) -> float:
    """Return starting confidence based on outcome type."""
    return {
        "interesting": 0.4,
        "thought": 0.35,
        "success": 0.6,
        "failure": 0.5,
    }.get(outcome, 0.5)
