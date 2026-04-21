"""Tests for src.overrides — config-driven routing overrides."""

from __future__ import annotations

import json
import os
import re
import warnings
from pathlib import Path

import pytest

from src import overrides
from src.overrides import (
    OverrideConfig,
    PathOverride,
    PatternRule,
    effective_plan_dirs,
    find_matching_prefix,
    load_overrides,
    match_pattern,
    rewrite_skill,
)


def _write_config(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "routing-overrides.json"
    path.write_text(json.dumps(data))
    return path


# ── load_overrides ─────────────────────────────────────────────────────


def test_missing_file_returns_empty_config(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.json"
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        cfg = load_overrides(missing)
    assert cfg == OverrideConfig()
    assert captured == []


def test_malformed_json_returns_empty_with_warning(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        cfg = load_overrides(bad)
    assert cfg == OverrideConfig()
    assert len(captured) == 1
    assert "could not parse" in str(captured[0].message)


def test_minimal_valid_config_parses(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        {"path_overrides": [{"prefix": str(tmp_path), "map": {"plan": "p:plan"}}]},
    )
    cfg = load_overrides(path)
    assert len(cfg.path_overrides) == 1
    entry = cfg.path_overrides[0]
    assert entry.map == {"plan": "p:plan"}
    assert entry.patterns == ()
    assert entry.plan_dirs is None


def test_full_config_with_patterns_and_plan_dirs(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        {
            "plan_dirs": ["global/plans"],
            "path_overrides": [
                {
                    "prefix": str(tmp_path),
                    "map": {"plan": "p:plan", "run": "p:run"},
                    "patterns": [{"regex": r"^hello\b", "skill": "p:greet"}],
                    "plan_dirs": ["custom/plans"],
                }
            ],
        },
    )
    cfg = load_overrides(path)
    assert cfg.plan_dirs == ("global/plans",)
    entry = cfg.path_overrides[0]
    assert entry.map == {"plan": "p:plan", "run": "p:run"}
    assert len(entry.patterns) == 1
    assert entry.patterns[0].skill == "p:greet"
    assert entry.patterns[0].regex.pattern == r"^hello\b"
    assert entry.plan_dirs == ("custom/plans",)


def test_invalid_schema_returns_empty_with_warning(tmp_path: Path) -> None:
    path = _write_config(tmp_path, {"path_overrides": "not-a-list"})
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        cfg = load_overrides(path)
    assert cfg == OverrideConfig()
    assert len(captured) == 1
    assert "invalid schema" in str(captured[0].message)


def test_plan_dirs_traversal_segment_rejected(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        {
            "path_overrides": [
                {
                    "prefix": str(tmp_path),
                    "plan_dirs": ["../../../etc"],
                }
            ]
        },
    )
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        cfg = load_overrides(path)
    assert cfg == OverrideConfig()
    assert any("'..'" in str(w.message) for w in captured)


def test_plan_dirs_absolute_path_rejected(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        {
            "path_overrides": [
                {
                    "prefix": str(tmp_path),
                    "plan_dirs": ["/etc"],
                }
            ]
        },
    )
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        cfg = load_overrides(path)
    assert cfg == OverrideConfig()
    assert any("relative" in str(w.message) for w in captured)


def test_invalid_regex_rejected(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        {
            "path_overrides": [
                {
                    "prefix": str(tmp_path),
                    "patterns": [{"regex": "(", "skill": "p:bad"}],
                }
            ]
        },
    )
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        cfg = load_overrides(path)
    assert cfg == OverrideConfig()
    assert any("invalid pattern regex" in str(w.message) for w in captured)


def test_prefix_with_trailing_separator_matches_descendants(tmp_path: Path) -> None:
    """A prefix ending in os.sep should still match descendant paths."""
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    trailing = os.path.realpath(str(tmp_path)) + os.sep
    override = PathOverride(prefix=trailing, map={"plan": "p:plan"})
    cfg = OverrideConfig(path_overrides=(override,))
    result = find_matching_prefix(str(nested), cfg)
    assert result is not None


def test_empty_map_value_rejected(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        {"path_overrides": [{"prefix": str(tmp_path), "map": {"plan": ""}}]},
    )
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        cfg = load_overrides(path)
    assert cfg == OverrideConfig()
    assert any("non-empty" in str(w.message) for w in captured)


def test_env_var_overrides_default_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _write_config(
        tmp_path,
        {"path_overrides": [{"prefix": str(tmp_path), "map": {"plan": "p:plan"}}]},
    )
    monkeypatch.setenv("AUTODIDACT_OVERRIDES_PATH", str(path))
    cfg = load_overrides()
    assert len(cfg.path_overrides) == 1
    assert cfg.path_overrides[0].map == {"plan": "p:plan"}


def test_env_var_ignored_when_explicit_path_provided(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    env_path = _write_config(
        tmp_path,
        {"path_overrides": [{"prefix": str(tmp_path), "map": {"plan": "ENV:plan"}}]},
    )
    arg_path = _write_config(
        sub,
        {"path_overrides": [{"prefix": str(tmp_path), "map": {"plan": "ARG:plan"}}]},
    )
    monkeypatch.setenv("AUTODIDACT_OVERRIDES_PATH", str(env_path))
    cfg = load_overrides(arg_path)
    assert cfg.path_overrides[0].map == {"plan": "ARG:plan"}


# ── find_matching_prefix ───────────────────────────────────────────────


def _cfg_with_prefix(prefix: str, **extra: object) -> OverrideConfig:
    entry = PathOverride(prefix=os.path.realpath(prefix), **extra)  # type: ignore[arg-type]
    return OverrideConfig(path_overrides=(entry,))


def test_find_matching_prefix_no_match(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    cfg = _cfg_with_prefix(str(tmp_path / "not-a-real-dir"))
    assert find_matching_prefix(str(other), cfg) is None


def test_find_matching_prefix_exact_cwd(tmp_path: Path) -> None:
    cfg = _cfg_with_prefix(str(tmp_path))
    result = find_matching_prefix(str(tmp_path), cfg)
    assert result is not None
    assert result.prefix == os.path.realpath(str(tmp_path))


def test_find_matching_prefix_nested_returns_longest(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    short = PathOverride(prefix=os.path.realpath(str(tmp_path)), map={"plan": "short:plan"})
    long_ = PathOverride(prefix=os.path.realpath(str(tmp_path / "a")), map={"plan": "long:plan"})
    cfg = OverrideConfig(path_overrides=(short, long_))
    result = find_matching_prefix(str(nested), cfg)
    assert result is not None
    assert result.map == {"plan": "long:plan"}


def test_find_matching_prefix_does_not_match_sibling(tmp_path: Path) -> None:
    (tmp_path / "foo").mkdir()
    (tmp_path / "foobar").mkdir()
    cfg = _cfg_with_prefix(str(tmp_path / "foo"))
    # /tmp/foobar should NOT match prefix /tmp/foo (not a directory boundary)
    assert find_matching_prefix(str(tmp_path / "foobar"), cfg) is None


def test_find_matching_prefix_resolves_symlinks(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    cfg = _cfg_with_prefix(str(real))
    result = find_matching_prefix(str(link), cfg)
    assert result is not None


def test_find_matching_prefix_empty_cwd_returns_none() -> None:
    cfg = _cfg_with_prefix("/tmp")
    assert find_matching_prefix("", cfg) is None


def test_find_matching_prefix_empty_overrides_returns_none(tmp_path: Path) -> None:
    cfg = OverrideConfig()
    assert find_matching_prefix(str(tmp_path), cfg) is None


# ── rewrite_skill ──────────────────────────────────────────────────────


def test_rewrite_skill_mapped_returns_name() -> None:
    override = PathOverride(prefix="/x", map={"plan": "p:plan"})
    assert rewrite_skill("plan", override) == "p:plan"


def test_rewrite_skill_unmapped_returns_none() -> None:
    override = PathOverride(prefix="/x", map={"plan": "p:plan"})
    assert rewrite_skill("research", override) is None


# ── match_pattern ──────────────────────────────────────────────────────


def test_match_pattern_first_match_wins() -> None:
    override = PathOverride(
        prefix="/x",
        patterns=(
            PatternRule(regex=re.compile(r"^hello"), skill="p:greet"),
            PatternRule(regex=re.compile(r"^hello\s+world"), skill="p:greet-world"),
        ),
    )
    assert match_pattern("hello world", override) == "p:greet"


def test_match_pattern_no_match_returns_none() -> None:
    override = PathOverride(
        prefix="/x",
        patterns=(PatternRule(regex=re.compile(r"^hello"), skill="p:greet"),),
    )
    assert match_pattern("goodbye", override) is None


# ── effective_plan_dirs ────────────────────────────────────────────────


def test_effective_plan_dirs_path_scoped_wins() -> None:
    override = PathOverride(prefix="/x", plan_dirs=("scoped/plans",))
    cfg = OverrideConfig(plan_dirs=("global/plans",))
    assert effective_plan_dirs(override, cfg) == ("scoped/plans",)


def test_effective_plan_dirs_falls_back_to_global() -> None:
    override = PathOverride(prefix="/x", plan_dirs=None)
    cfg = OverrideConfig(plan_dirs=("global/plans",))
    assert effective_plan_dirs(override, cfg) == ("global/plans",)


def test_effective_plan_dirs_none_override_falls_back() -> None:
    cfg = OverrideConfig(plan_dirs=("global/plans",))
    assert effective_plan_dirs(None, cfg) == ("global/plans",)


def test_effective_plan_dirs_defaults_when_unset() -> None:
    cfg = OverrideConfig()  # uses default
    assert effective_plan_dirs(None, cfg) == (".planning/plans",)


# ── end-to-end: example file loads ─────────────────────────────────────


def test_example_config_file_parses() -> None:
    example = Path(__file__).resolve().parent.parent / "examples" / "routing-overrides.json"
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        cfg = overrides.load_overrides(example)
    assert captured == []
    assert len(cfg.path_overrides) >= 1
