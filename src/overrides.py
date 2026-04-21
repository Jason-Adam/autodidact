"""Path-scoped routing overrides for the /do router.

Loads a user-provided JSON config that rewrites classifier output and
short-circuits classification when the working directory matches a
configured prefix. Absence of the config file is equivalent to no
overrides — the router's default behavior is preserved.

Config path resolution (highest priority first):
1. Explicit ``path`` argument to :func:`load_overrides`
2. ``$AUTODIDACT_OVERRIDES_PATH`` environment variable
3. ``~/.claude/autodidact/routing-overrides.json``

Schema (all top-level keys optional):

    {
      "plan_dirs": [".planning/plans"],
      "path_overrides": [
        {
          "prefix": "/absolute/path/to/project",
          "map": {"plan": "someplugin:plan-skill"},
          "patterns": [{"regex": "^hello", "skill": "someplugin:greet"}],
          "plan_dirs": ["custom/plan/dir"]
        }
      ]
    }
"""

from __future__ import annotations

import json
import os
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".claude" / "autodidact" / "routing-overrides.json"
_DEFAULT_PLAN_DIRS: tuple[str, ...] = (".planning/plans",)


@dataclass(frozen=True)
class PatternRule:
    regex: re.Pattern[str]
    skill: str


@dataclass(frozen=True)
class PathOverride:
    prefix: str
    map: dict[str, str] = field(default_factory=dict)
    patterns: tuple[PatternRule, ...] = ()
    plan_dirs: tuple[str, ...] | None = None


@dataclass(frozen=True)
class OverrideConfig:
    path_overrides: tuple[PathOverride, ...] = ()
    plan_dirs: tuple[str, ...] = _DEFAULT_PLAN_DIRS


def _resolve_config_path(path: Path | None) -> Path:
    if path is not None:
        return path
    env = os.environ.get("AUTODIDACT_OVERRIDES_PATH")
    if env:
        return Path(env)
    return DEFAULT_CONFIG_PATH


def _parse_plan_dirs(raw: object, field_name: str) -> tuple[str, ...]:
    """Validate a list of plan-dir strings. Rejects traversal ('..') segments
    so a malicious config cannot probe paths outside the cwd."""
    if not isinstance(raw, list) or not all(isinstance(d, str) for d in raw):
        raise ValueError(f"{field_name!r} must be a list of strings")
    for d in raw:
        if ".." in Path(d).parts or os.path.isabs(d):
            raise ValueError(
                f"{field_name!r} entry {d!r} must be relative and must not contain '..'"
            )
    return tuple(raw)


def _parse_path_override(entry: dict[str, object]) -> PathOverride:
    prefix_raw = entry["prefix"]
    if not isinstance(prefix_raw, str) or not prefix_raw:
        raise ValueError("'prefix' must be a non-empty string")
    prefix = os.path.realpath(prefix_raw)

    mapping_raw = entry.get("map", {})
    if not isinstance(mapping_raw, dict):
        raise ValueError("'map' must be an object")
    mapping: dict[str, str] = {}
    for k, v in mapping_raw.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise ValueError("'map' keys and values must be strings")
        if not v:
            raise ValueError(f"'map' value for {k!r} must be non-empty")
        mapping[k] = v

    patterns_raw = entry.get("patterns", [])
    if not isinstance(patterns_raw, list):
        raise ValueError("'patterns' must be a list")
    patterns: list[PatternRule] = []
    for rule in patterns_raw:
        if not isinstance(rule, dict) or "regex" not in rule or "skill" not in rule:
            raise ValueError("each pattern rule must have 'regex' and 'skill'")
        regex_str = rule["regex"]
        skill = rule["skill"]
        if not isinstance(regex_str, str) or not isinstance(skill, str):
            raise ValueError("pattern 'regex' and 'skill' must be strings")
        patterns.append(PatternRule(regex=re.compile(regex_str), skill=skill))

    plan_dirs_raw = entry.get("plan_dirs")
    plan_dirs: tuple[str, ...] | None = (
        None if plan_dirs_raw is None else _parse_plan_dirs(plan_dirs_raw, "plan_dirs")
    )

    return PathOverride(
        prefix=prefix,
        map=mapping,
        patterns=tuple(patterns),
        plan_dirs=plan_dirs,
    )


def load_overrides(path: Path | None = None) -> OverrideConfig:
    """Load overrides from the resolved config path.

    Returns an empty :class:`OverrideConfig` if the file is missing,
    malformed, or violates the schema. In the malformed/invalid cases
    a :class:`UserWarning` is emitted.
    """
    cfg_path = _resolve_config_path(path)
    if not cfg_path.is_file():
        return OverrideConfig()

    try:
        raw = json.loads(cfg_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        warnings.warn(f"autodidact: could not parse {cfg_path}: {exc}", stacklevel=2)
        return OverrideConfig()

    if not isinstance(raw, dict):
        warnings.warn(f"autodidact: {cfg_path} root must be an object", stacklevel=2)
        return OverrideConfig()

    try:
        global_plan_dirs_raw = raw.get("plan_dirs")
        if global_plan_dirs_raw is None:
            global_plan_dirs = _DEFAULT_PLAN_DIRS
        else:
            global_plan_dirs = _parse_plan_dirs(global_plan_dirs_raw, "plan_dirs")

        path_overrides_raw = raw.get("path_overrides", [])
        if not isinstance(path_overrides_raw, list):
            raise ValueError("'path_overrides' must be a list")
        path_overrides = tuple(_parse_path_override(e) for e in path_overrides_raw)
    except (ValueError, KeyError, TypeError) as exc:
        warnings.warn(f"autodidact: invalid schema in {cfg_path}: {exc}", stacklevel=2)
        return OverrideConfig()

    return OverrideConfig(
        path_overrides=path_overrides,
        plan_dirs=global_plan_dirs,
    )


def find_matching_prefix(cwd: str, config: OverrideConfig) -> PathOverride | None:
    """Return the longest-prefix match for ``cwd`` among ``config.path_overrides``.

    Matches are directory-aware: ``cwd`` matches ``prefix`` only when it
    equals ``prefix`` or is under ``prefix + os.sep``.
    """
    if not cwd or not config.path_overrides:
        return None
    resolved = os.path.realpath(cwd)
    best: PathOverride | None = None
    best_len = -1
    for entry in config.path_overrides:
        prefix = entry.prefix
        if (resolved == prefix or resolved.startswith(prefix + os.sep)) and len(prefix) > best_len:
            best = entry
            best_len = len(prefix)
    return best


def rewrite_skill(bare: str, override: PathOverride) -> str | None:
    """Look up ``bare`` in the override's map. Returns the mapped name or None."""
    return override.map.get(bare)


def match_pattern(prompt: str, override: PathOverride) -> str | None:
    """Return the skill for the first pattern whose regex matches ``prompt``."""
    for rule in override.patterns:
        if rule.regex.search(prompt):
            return rule.skill
    return None


def effective_plan_dirs(override: PathOverride | None, config: OverrideConfig) -> tuple[str, ...]:
    """Path-scoped plan_dirs win over global; falls back to the default."""
    if override is not None and override.plan_dirs is not None:
        return override.plan_dirs
    return config.plan_dirs
