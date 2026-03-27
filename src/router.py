"""Cost-ascending /do router.

Tiers 0-2 are deterministic (zero/low cost). Tier 3 signals to the
/do skill markdown to perform LLM-based classification.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_MAX_PLAN_BYTES = 256 * 1024  # 256 KB cap for plan file reads


@dataclass
class RouterResult:
    skill: str
    confidence: float
    tier: int
    reasoning: str = ""
    model: str = ""


SKILL_MODEL_MAP: dict[str, str] = {
    # Haiku tier — cheap, fast
    "learn_status": "haiku",
    "forget": "haiku",
    "direct": "haiku",
    # Sonnet tier — standard work
    "research": "opus",
    "plan": "sonnet",
    "run": "sonnet",
    "fleet": "sonnet",
    "review": "sonnet",
    "polish": "sonnet",
    "handoff": "sonnet",
    "experiment": "sonnet",
    "sync-thoughts": "sonnet",
    "learn": "sonnet",
    # Opus tier — complex reasoning
    "campaign": "opus",
    "loop": "opus",
    "classify": "opus",
    "do": "opus",
}


# ── Tier 0: Pattern Match ──────────────────────────────────────────────

_DIRECT_PATTERNS: list[tuple[str, str]] = [
    (r"^/?(do\s+)?interview\b", "plan"),  # consolidated into /plan (Clarify phase)
    (r"^/?(do\s+)?research\b", "research"),
    (r"^/?(do\s+)?plan\b", "plan"),
    (r"^/?(do\s+)?fleet\b", "fleet"),
    (r"^/do\s+run\b", "run"),  # requires /do prefix to avoid matching "run the tests"
    (r"^/?run$", "run"),  # bare "run" with no arguments
    (r"^/?(do\s+)?marshal\b", "run"),  # legacy alias
    (r"^/?(do\s+)?campaign\b", "campaign"),
    (r"^/?(do\s+)?archon\b", "campaign"),  # legacy alias
    (r"^/?(do\s+)?learn\b", "learn"),
    (r"^/?(do\s+)?review\b", "review"),
    (r"^/?(do\s+)?polish\b", "polish"),
    (r"^/?(do\s+)?handoff\b", "handoff"),
    (r"^/?(do\s+)?sync.?thoughts\b", "sync-thoughts"),
    (r"^/?(do\s+)?forget\b", "forget"),
    (r"^/?(do\s+)?learn.?status\b", "learn_status"),
    (r"^/?(do\s+)?experiment\b", "experiment"),
    (r"^/do\s+loop\b", "loop"),  # requires /do prefix to avoid matching "loop through..."
    (r"^/?loop$", "loop"),  # bare "loop" with no arguments
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

    # (path_or_glob, is_glob, skill, reasoning_template)
    _checks: list[tuple[Path, bool, str, str]] = [
        (planning / "campaigns", True, "campaign", "Active campaign: {name}"),
        (planning / "run_state.json", False, "run", "Active run sequence"),
        (planning / "fleet" / "active.json", False, "fleet", "Active fleet session"),
    ]

    for path, is_glob, skill, reasoning_tpl in _checks:
        if not path.exists():
            continue
        files = sorted(path.glob("*.json"), reverse=True) if is_glob else [path]
        for f in files:
            try:
                data = json.loads(f.read_text())
                if data.get("status") == "in_progress":
                    return RouterResult(
                        skill=skill,
                        confidence=0.9,
                        tier=1,
                        reasoning=reasoning_tpl.format(name=data.get("name", f.stem)),
                    )
            except (json.JSONDecodeError, KeyError):
                pass

    return None


# ── Tier 2.5: Plan Structure Analysis ─────────────────────────────────


def _parse_plan_phases(text: str) -> list[dict[str, list[str]]]:
    """Extract phases and their file references from a plan markdown doc.

    Returns a list of dicts, each with key "files" listing paths mentioned
    in that phase's steps.
    """
    phases: list[dict[str, list[str]]] = []
    current_files: list[str] = []
    in_phase = False

    for line in text.splitlines():
        # Phase headers: "### Phase 1: ..." or "## Phase 1: ..."
        if re.match(r"^#{2,3}\s+Phase\s+\d+", line, re.IGNORECASE):
            if in_phase:
                phases.append({"files": current_files})
            current_files = []
            in_phase = True
            continue
        # Next non-phase heading ends the current phase
        if in_phase and re.match(r"^#{2,3}\s+(?!Phase\s+\d+)", line):
            phases.append({"files": current_files})
            current_files = []
            in_phase = False
            continue
        # Collect file paths: backticked paths or common extensions
        if in_phase:
            for match in re.finditer(r"`([^`]+\.(?:py|ts|js|md|json|yaml|yml|toml|sql|sh))`", line):
                current_files.append(match.group(1))

    # Close last open phase
    if in_phase:
        phases.append({"files": current_files})

    return phases


def _phases_are_independent(phases: list[dict[str, list[str]]]) -> bool:
    """Check if phases touch disjoint file sets (parallelizable)."""
    if len(phases) < 2:
        return False

    # Need at least some file references to judge independence
    all_files: set[str] = set()
    for phase in phases:
        all_files.update(phase.get("files", []))
    if not all_files:
        return False

    from src.task_graph import TaskGraph, TaskNode

    graph = TaskGraph(max_per_wave=len(phases))  # no wave-size limit for this check
    for i, phase in enumerate(phases):
        graph.add_task(
            TaskNode(
                task_id=f"phase-{i}",
                description="",
                target_files=phase.get("files", []),
            )
        )

    try:
        waves = graph.partition_waves()
    except ValueError:
        return False

    # All phases in exactly one wave = fully independent (no overlaps)
    return len(waves) == 1


def _tier25_plan_analysis(cwd: str) -> RouterResult | None:
    """Analyze existing plan structure to pick orchestrator. Zero cost."""
    if not cwd:
        return None

    plans_dir = Path(cwd) / ".planning" / "plans"
    if not plans_dir.exists():
        return None

    # Find the most recent plan (sorted by filename which is date-prefixed)
    plan_files = sorted(plans_dir.glob("*.md"), reverse=True)
    if not plan_files:
        return None

    text = plan_files[0].read_bytes()[:_MAX_PLAN_BYTES].decode("utf-8", errors="replace")
    phases = _parse_plan_phases(text)
    phase_count = len(phases)

    if phase_count == 0:
        return None

    # Trivial plan — single phase or very small
    if phase_count == 1:
        return RouterResult(
            skill="direct",
            confidence=0.8,
            tier=2,
            reasoning=f"Plan has 1 phase — direct execution (plan: {plan_files[0].name})",
        )

    # Parallelizable — phases touch disjoint files
    if _phases_are_independent(phases):
        return RouterResult(
            skill="fleet",
            confidence=0.85,
            tier=2,
            reasoning=f"Plan has {phase_count} independent phases"
            f" — fleet (plan: {plan_files[0].name})",
        )

    # Large plan — likely multi-session
    if phase_count > 5:
        return RouterResult(
            skill="campaign",
            confidence=0.85,
            tier=2,
            reasoning=f"Plan has {phase_count} phases — campaign (plan: {plan_files[0].name})",
        )

    # Default: sequential multi-phase, single session
    return RouterResult(
        skill="run",
        confidence=0.85,
        tier=2,
        reasoning=f"Plan has {phase_count} sequential phases — run (plan: {plan_files[0].name})",
    )


# ── Tier 2: Keyword Heuristic ──────────────────────────────────────────

_KEYWORD_SCORES: dict[str, list[tuple[str, float]]] = {
    "fleet": [
        ("parallel", 0.4),
        ("worktree", 0.5),
        ("concurrent", 0.3),
        ("concurrently", 0.3),
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
    "research": [
        ("research", 0.5),
        ("explore", 0.3),
        ("investigate", 0.4),
        ("understand", 0.2),
        ("how does", 0.3),
        ("architecture", 0.2),
        ("trace", 0.3),
        ("analyze", 0.3),
        ("deep dive", 0.5),
    ],
    "plan": [
        ("plan", 0.5),
        ("design", 0.3),
        ("approach", 0.3),
        ("strategy", 0.3),
        ("implementation plan", 0.5),
        ("clarify", 0.4),
        ("unclear", 0.4),
        ("ambiguous", 0.4),
        ("requirements", 0.3),
        ("scope", 0.2),
    ],
    "review": [
        ("review", 0.5),
        ("code review", 0.6),
        ("check quality", 0.4),
        ("audit", 0.3),
        ("inspect", 0.3),
    ],
    "polish": [
        ("polish", 0.6),
        ("clean up", 0.4),
        ("simplify", 0.4),
        ("security review", 0.65),
        ("fix issues", 0.3),
        ("tidy", 0.3),
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
    "learn_status": [
        ("token savings", 0.6),
        ("token economics", 0.6),
        ("rtk", 0.5),
        ("savings", 0.3),
        ("learning stats", 0.6),
        ("knowledge inventory", 0.6),
        ("confidence stats", 0.6),
        ("graduation candidates", 0.6),
    ],
}


# Pre-compiled patterns and pre-sorted keyword lists (built once at import).
_KEYWORD_PATTERNS: dict[str, list[tuple[str, re.Pattern[str], float]]] = {
    skill: sorted(
        [(kw, re.compile(r"\b" + re.escape(kw) + r"\b"), w) for kw, w in keywords],
        key=lambda x: len(x[0]),
        reverse=True,
    )
    for skill, keywords in _KEYWORD_SCORES.items()
}

_TIER2_THRESHOLD = 0.3


def _tier2_keyword_heuristic(prompt: str) -> RouterResult | None:
    """Score prompt against keyword tables. Low cost."""
    normalized = prompt.strip().lower()
    best_skill = ""
    best_score = 0.0

    for skill, patterns in _KEYWORD_PATTERNS.items():
        matched: list[str] = []
        score = 0.0
        for kw, pattern, weight in patterns:
            if not pattern.search(normalized):
                continue
            # Skip if this keyword is a substring of an already-matched keyword
            if any(kw in m for m in matched):
                continue
            matched.append(kw)
            score += weight
        if score > best_score:
            best_score = score
            best_skill = skill

    if best_score >= _TIER2_THRESHOLD:
        return RouterResult(
            skill=best_skill,
            confidence=min(best_score, 1.0),
            tier=2,
            reasoning=f"Keyword match: {best_skill} (score: {best_score:.2f})",
        )
    return None


# ── Public API ──────────────────────────────────────────────────────────

# Skills that are installed with the autodidact- prefix under ~/.claude/skills/.
# The router returns fully-qualified names so Claude Code never confuses them
# with project-scoped skills (e.g. crsdigital:create-plan vs autodidact-plan).
_AUTODIDACT_SKILLS: frozenset[str] = frozenset(
    {
        "research",
        "plan",
        "run",
        "fleet",
        "campaign",
        "learn",
        "handoff",
        "experiment",
        "loop",
        "polish",
        "sync-thoughts",
        "do",
    }
)


def _qualify_skill(name: str) -> str:
    """Add the autodidact- prefix for installed skills.

    Signal values (``direct``, ``classify``) and command-only entries
    (``review``, ``forget``, ``learn_status``) are returned bare.
    """
    if name in _AUTODIDACT_SKILLS:
        return f"autodidact-{name}"
    return name


_PLAN_SKILL_TO_LOOP_MODE: dict[str, str] = {
    "direct": "run",
    "run": "run",
    "fleet": "fleet",
    "campaign": "campaign",
}


def select_loop_mode(cwd: str) -> str:
    """Pick loop mode (run/campaign/fleet) based on workspace state.

    Priority:
    1. Active state (campaign/fleet/run) from Tier 1
    2. Plan structure analysis from Tier 2.5
    3. Default: run
    """
    # Active state takes priority
    result = _tier1_active_state(cwd)
    if result and result.skill in ("campaign", "fleet", "run"):
        return result.skill

    # Plan structure analysis
    result = _tier25_plan_analysis(cwd)
    if result:
        return _PLAN_SKILL_TO_LOOP_MODE.get(result.skill, "run")

    return "run"


def _assign_model(result: RouterResult) -> RouterResult:
    """Assign model tier based on skill. Mutates and returns result."""
    # Strip autodidact- prefix to look up base skill name
    base = result.skill.removeprefix("autodidact-")
    result.model = SKILL_MODEL_MAP.get(base, "sonnet")
    return result


def classify(prompt: str, cwd: str = "") -> RouterResult:
    """Cost-ascending classification. Tiers 0-2 are deterministic.

    Tier 3 returns skill="classify" to signal that LLM classification
    is needed (handled by the /do skill markdown).

    Skill names are returned with the ``autodidact-`` prefix so that
    Claude Code resolves them unambiguously, even when project-scoped
    skills (e.g. ``crsdigital:create-plan``) are also available.
    """
    # Cost-ascending: run each tier until one matches.
    for result in (
        _tier0_pattern_match(prompt),
        _tier1_active_state(cwd),
        _tier2_keyword_heuristic(prompt),
        _tier25_plan_analysis(cwd),
    ):
        if result:
            result.skill = _qualify_skill(result.skill)
            return _assign_model(result)

    # Tier 3: Signal for LLM classification (no prefix needed)
    return _assign_model(
        RouterResult(
            skill="classify",
            confidence=0.0,
            tier=3,
            reasoning="No deterministic match; LLM classification needed",
        )
    )
