"""Tests for router integration with path-scoped overrides."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src import router


def _write_plan(cwd: Path) -> None:
    plans = cwd / ".planning" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    (plans / "2026-01-01-test.md").write_text("## Plan\n### Phase 1: Do it\n- [ ] task\n")


def _write_config(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps(data))
    return path


@pytest.fixture
def cwd_with_plan(tmp_path: Path) -> Path:
    _write_plan(tmp_path)
    return tmp_path


def _set_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cfg: dict) -> Path:
    path = _write_config(tmp_path, cfg)
    monkeypatch.setenv("AUTODIDACT_OVERRIDES_PATH", str(path))
    return path


# ── Map rewrites ───────────────────────────────────────────────────────


def test_tier0_skill_rewritten_when_path_matches(
    cwd_with_plan: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    _set_config(
        monkeypatch,
        cfg_dir,
        {
            "path_overrides": [
                {
                    "prefix": os.path.realpath(str(cwd_with_plan)),
                    "map": {"plan": "someplugin:plan-skill"},
                }
            ]
        },
    )
    result = router.classify("/do plan", cwd=str(cwd_with_plan))
    assert result.skill == "someplugin:plan-skill"
    assert result.tier == 0
    assert "override_map" in result.reasoning


def test_tier2_skill_rewritten_when_path_matches(
    cwd_with_plan: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    _set_config(
        monkeypatch,
        cfg_dir,
        {
            "path_overrides": [
                {
                    "prefix": os.path.realpath(str(cwd_with_plan)),
                    "map": {"polish": "someplugin:polish-skill"},
                }
            ]
        },
    )
    # Tier 2 match: "code review" -> polish
    result = router.classify("please do a code review", cwd=str(cwd_with_plan))
    assert result.skill == "someplugin:polish-skill"
    assert "override_map" in result.reasoning


def test_pattern_respects_plan_gate_when_no_plan_doc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pattern mapping to a bare implementation skill must still hit the plan gate."""
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    proj = tmp_path / "proj"
    proj.mkdir()
    _set_config(
        monkeypatch,
        cfg_dir,
        {
            "path_overrides": [
                {
                    "prefix": os.path.realpath(str(proj)),
                    "patterns": [{"regex": r"^deploy", "skill": "run"}],
                }
            ]
        },
    )
    # No plan doc in proj → plan gate should redirect "run" to autodidact-plan
    result = router.classify("deploy now", cwd=str(proj))
    assert result.skill == "autodidact-plan"
    assert "Plan gate" in result.reasoning


def test_pattern_short_circuits_tiers(
    cwd_with_plan: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    _set_config(
        monkeypatch,
        cfg_dir,
        {
            "path_overrides": [
                {
                    "prefix": os.path.realpath(str(cwd_with_plan)),
                    "patterns": [{"regex": r"^/?deploy\b", "skill": "someplugin:deploy"}],
                }
            ]
        },
    )
    result = router.classify("deploy to staging", cwd=str(cwd_with_plan))
    assert result.skill == "someplugin:deploy"
    assert result.tier == 0
    assert result.reasoning == "override_pattern"


def test_no_path_match_no_rewrite(
    cwd_with_plan: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    other = tmp_path / "other-project"
    other.mkdir()
    _set_config(
        monkeypatch,
        cfg_dir,
        {
            "path_overrides": [
                {
                    "prefix": os.path.realpath(str(other)),
                    "map": {"plan": "someplugin:plan-skill"},
                }
            ]
        },
    )
    result = router.classify("/do plan", cwd=str(cwd_with_plan))
    assert result.skill == "autodidact-plan"


def test_no_config_preserves_default_behavior(
    cwd_with_plan: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTODIDACT_OVERRIDES_PATH", "/nonexistent/nowhere.json")
    result = router.classify("/do plan", cwd=str(cwd_with_plan))
    assert result.skill == "autodidact-plan"
    assert result.tier == 0


def test_implementation_skills_not_rewritten(
    cwd_with_plan: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Bare signal values direct/batch/classify are never mapped.

    The only way to hit these deterministically is Tier 2.5 plan
    analysis. We write a single-phase plan to force a ``direct`` result,
    then confirm the map does not touch it.
    """
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()

    # Replace the existing multi-phase plan with a single-phase plan
    plans = cwd_with_plan / ".planning" / "plans"
    for f in plans.glob("*.md"):
        f.unlink()
    (plans / "2026-01-02-single.md").write_text("## Plan\n### Phase 1: go\n- [ ] x\n")

    _set_config(
        monkeypatch,
        cfg_dir,
        {
            "path_overrides": [
                {
                    "prefix": os.path.realpath(str(cwd_with_plan)),
                    "map": {"direct": "someplugin:direct-should-be-ignored"},
                }
            ]
        },
    )
    # An unclassified prompt in a cwd with a 1-phase plan lands at tier 2.5 -> direct
    result = router.classify("foo bar baz qux", cwd=str(cwd_with_plan))
    assert result.skill == "direct"


# ── _qualify_skill ─────────────────────────────────────────────────────


def test_qualify_skill_passes_colon_namespaced_through() -> None:
    assert router._qualify_skill("someplugin:plan") == "someplugin:plan"
    assert router._qualify_skill("someplugin:custom-skill") == "someplugin:custom-skill"


def test_qualify_skill_still_prefixes_bare_autodidact_skills() -> None:
    assert router._qualify_skill("plan") == "autodidact-plan"
    assert router._qualify_skill("run") == "autodidact-run"


def test_qualify_skill_passes_unknown_bare_names_through() -> None:
    assert router._qualify_skill("direct") == "direct"
    assert router._qualify_skill("classify") == "classify"
    assert router._qualify_skill("batch") == "batch"


# ── _has_plan_doc with configured plan_dirs ────────────────────────────


def test_has_plan_doc_uses_configured_plan_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Hermetic: force no user config so developer's home config cannot
    # accidentally satisfy the plan gate for this tmp_path.
    monkeypatch.setenv("AUTODIDACT_OVERRIDES_PATH", "/nonexistent/nowhere.json")

    # No plan in default location
    assert router._has_plan_doc(str(tmp_path)) is False

    # Write a plan in a custom dir
    custom = tmp_path / "tmp" / "plans"
    custom.mkdir(parents=True)
    (custom / "plan.md").write_text("# Plan\n")

    # Without config: still False (custom path not searched)
    assert router._has_plan_doc(str(tmp_path)) is False

    # With config pointing to the custom dir: True
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    cfg_path = cfg_dir / "overrides.json"
    cfg_path.write_text(
        json.dumps(
            {
                "path_overrides": [
                    {
                        "prefix": os.path.realpath(str(tmp_path)),
                        "plan_dirs": ["tmp/plans"],
                    }
                ]
            }
        )
    )
    monkeypatch.setenv("AUTODIDACT_OVERRIDES_PATH", str(cfg_path))
    assert router._has_plan_doc(str(tmp_path)) is True


def test_has_plan_doc_explicit_plan_dirs_arg_wins(tmp_path: Path) -> None:
    # Plan in custom dir
    custom = tmp_path / "my" / "plans"
    custom.mkdir(parents=True)
    (custom / "plan.md").write_text("# Plan\n")
    assert router._has_plan_doc(str(tmp_path), plan_dirs=["my/plans"]) is True
    assert router._has_plan_doc(str(tmp_path), plan_dirs=["elsewhere"]) is False


# ── plan gate with overrides ───────────────────────────────────────────


def test_plan_gate_redirect_is_itself_rewritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the plan gate redirects to ``plan``, the override map still applies.

    This means a user with ``"plan": "p:plan"`` gets ``p:plan`` instead of
    ``autodidact-plan`` when the gate fires — they get to pick which plan
    skill enforces the gate.
    """
    # No plan doc present; implementation skill request should trip the gate
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    cfg_path = cfg_dir / "overrides.json"
    cfg_path.write_text(
        json.dumps(
            {
                "path_overrides": [
                    {
                        "prefix": os.path.realpath(str(tmp_path)),
                        "map": {"plan": "someplugin:plan-skill"},
                    }
                ]
            }
        )
    )
    monkeypatch.setenv("AUTODIDACT_OVERRIDES_PATH", str(cfg_path))

    result = router.classify("/do run something", cwd=str(tmp_path))
    assert result.skill == "someplugin:plan-skill"
    assert "Plan gate" in result.reasoning
    assert "override_map" in result.reasoning
