"""Parse and evaluate machine-checkable fitness expressions from plan documents."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass


@dataclass
class FitnessExpression:
    """A single machine-checkable fitness criterion extracted from a plan."""

    raw: str
    metric_command: str
    comparator: str
    target_value: float
    description: str = ""


@dataclass
class FitnessResult:
    """The outcome of evaluating a FitnessExpression."""

    passed: bool
    actual_value: float
    target_value: float
    comparator: str
    expression: str


# Matches lines like:  - `shell command` >= 85.0
_LINE_RE = re.compile(r"-\s+`(?P<cmd>[^`]+)`\s+(?P<cmp>>=|<=|==|>|<)\s+(?P<val>-?\d+(?:\.\d+)?)")

_SECTION_RE = re.compile(r"^###\s+Fitness\s*$", re.IGNORECASE | re.MULTILINE)
_NEXT_HEADING_RE = re.compile(r"^###", re.MULTILINE)


def parse_fitness_block(plan_text: str) -> list[FitnessExpression]:
    """Extract fitness expressions from a plan's ### Fitness section.

    Expected format per line:
        - `shell command here` >= 85.0
        - `python3 -m pytest --tb=no -q 2>&1 | tail -1 | grep -c passed` >= 1

    Lines not matching the pattern are silently skipped.
    """
    match = _SECTION_RE.search(plan_text)
    if not match:
        return []

    section_start = match.end()
    rest = plan_text[section_start:]

    # Find the next ### heading after the Fitness heading to bound the section.
    next_heading = _NEXT_HEADING_RE.search(rest)
    section_body = rest[: next_heading.start()] if next_heading else rest

    expressions: list[FitnessExpression] = []
    for line in section_body.splitlines():
        m = _LINE_RE.search(line)
        if not m:
            continue
        expressions.append(
            FitnessExpression(
                raw=line.strip(),
                metric_command=m.group("cmd"),
                comparator=m.group("cmp"),
                target_value=float(m.group("val")),
            )
        )
    return expressions


def evaluate(expression: FitnessExpression, cwd: str, timeout: int = 60) -> FitnessResult:
    """Run metric command via subprocess, compare result against target."""
    try:
        proc = subprocess.run(
            expression.metric_command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        actual = float(lines[-1].strip()) if lines else 0.0
    except subprocess.TimeoutExpired:
        return FitnessResult(
            passed=False,
            actual_value=0.0,
            target_value=expression.target_value,
            comparator=expression.comparator,
            expression=expression.raw,
        )
    except (ValueError, IndexError):
        actual = 0.0

    passed = _compare(actual, expression.comparator, expression.target_value)
    return FitnessResult(
        passed=passed,
        actual_value=actual,
        target_value=expression.target_value,
        comparator=expression.comparator,
        expression=expression.raw,
    )


def evaluate_all(
    expressions: list[FitnessExpression], cwd: str
) -> tuple[bool, list[FitnessResult]]:
    """Evaluate all expressions. Returns (all_passed, individual_results)."""
    results = [evaluate(expr, cwd) for expr in expressions]
    all_passed = all(r.passed for r in results)
    return all_passed, results


def _compare(actual: float, comparator: str, target: float) -> bool:
    """Return True when actual <comparator> target holds."""
    if comparator == ">=":
        return actual >= target
    if comparator == "<=":
        return actual <= target
    if comparator == "==":
        return actual == target
    if comparator == ">":
        return actual > target
    if comparator == "<":
        return actual < target
    return False
