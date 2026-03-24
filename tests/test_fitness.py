"""Tests for the fitness expression parser and evaluator."""

from __future__ import annotations

import tempfile
import unittest

from src.fitness import (
    FitnessExpression,
    evaluate,
    evaluate_all,
    parse_fitness_block,
)

_PLAN_WITH_FITNESS = """\
# My Plan

## Overview
Some overview text.

### Fitness
- `echo 90` >= 85.0
- `python3 -m pytest --tb=no -q 2>&1 | tail -1 | grep -c passed` >= 1

### Next Steps
- Do the thing.
"""

_PLAN_NO_FITNESS = """\
# My Plan

## Overview
No fitness section here.
"""

_PLAN_MALFORMED = """\
# My Plan

### Fitness
- no backticks here >= 10
- `good command` but no comparator
- just a random line
- `echo 5` >= 5.0
"""

_PLAN_ALL_COMPARATORS = """\
### Fitness
- `echo 1` >= 1
- `echo 1` <= 1
- `echo 1` == 1
- `echo 2` > 1
- `echo 0` < 1
"""

_PLAN_INTEGER_TARGET = """\
### Fitness
- `echo 1` >= 1
"""


class TestFitness(unittest.TestCase):
    def setUp(self) -> None:
        self.cwd = tempfile.mkdtemp()

    # ── Parsing ─────────────────────────────────────────────────────

    def test_parse_valid_fitness_block(self) -> None:
        exprs = parse_fitness_block(_PLAN_WITH_FITNESS)
        self.assertEqual(len(exprs), 2)

        first = exprs[0]
        self.assertEqual(first.metric_command, "echo 90")
        self.assertEqual(first.comparator, ">=")
        self.assertAlmostEqual(first.target_value, 85.0)

        second = exprs[1]
        self.assertIn("pytest", second.metric_command)
        self.assertEqual(second.comparator, ">=")
        self.assertAlmostEqual(second.target_value, 1.0)

    def test_parse_missing_section(self) -> None:
        exprs = parse_fitness_block(_PLAN_NO_FITNESS)
        self.assertEqual(exprs, [])

    def test_parse_malformed_lines(self) -> None:
        exprs = parse_fitness_block(_PLAN_MALFORMED)
        # Only the one well-formed line should survive
        self.assertEqual(len(exprs), 1)
        self.assertEqual(exprs[0].metric_command, "echo 5")

    def test_parse_all_comparators(self) -> None:
        exprs = parse_fitness_block(_PLAN_ALL_COMPARATORS)
        self.assertEqual(len(exprs), 5)
        comparators = [e.comparator for e in exprs]
        self.assertEqual(comparators, [">=", "<=", "==", ">", "<"])

    def test_parse_integer_target(self) -> None:
        exprs = parse_fitness_block(_PLAN_INTEGER_TARGET)
        self.assertEqual(len(exprs), 1)
        self.assertAlmostEqual(exprs[0].target_value, 1.0)
        self.assertIsInstance(exprs[0].target_value, float)

    # ── Evaluation ──────────────────────────────────────────────────

    def test_evaluate_simple_echo(self) -> None:
        expr = FitnessExpression(
            raw="- `echo 42` >= 40",
            metric_command="echo 42",
            comparator=">=",
            target_value=40.0,
        )
        result = evaluate(expr, cwd=self.cwd)
        self.assertTrue(result.passed)
        self.assertAlmostEqual(result.actual_value, 42.0)

    def test_evaluate_fails(self) -> None:
        expr = FitnessExpression(
            raw="- `echo 10` >= 50",
            metric_command="echo 10",
            comparator=">=",
            target_value=50.0,
        )
        result = evaluate(expr, cwd=self.cwd)
        self.assertFalse(result.passed)
        self.assertAlmostEqual(result.actual_value, 10.0)

    def test_evaluate_timeout(self) -> None:
        expr = FitnessExpression(
            raw="- `sleep 10` >= 1",
            metric_command="sleep 10",
            comparator=">=",
            target_value=1.0,
        )
        result = evaluate(expr, cwd=self.cwd, timeout=1)
        self.assertFalse(result.passed)
        self.assertAlmostEqual(result.actual_value, 0.0)

    def test_evaluate_non_numeric_output(self) -> None:
        expr = FitnessExpression(
            raw="- `echo hello` >= 1",
            metric_command="echo hello",
            comparator=">=",
            target_value=1.0,
        )
        result = evaluate(expr, cwd=self.cwd)
        self.assertFalse(result.passed)
        self.assertAlmostEqual(result.actual_value, 0.0)

    def test_evaluate_all_mixed(self) -> None:
        exprs = [
            FitnessExpression(
                raw="- `echo 100` >= 90",
                metric_command="echo 100",
                comparator=">=",
                target_value=90.0,
            ),
            FitnessExpression(
                raw="- `echo 5` >= 50",
                metric_command="echo 5",
                comparator=">=",
                target_value=50.0,
            ),
        ]
        all_passed, results = evaluate_all(exprs, cwd=self.cwd)
        self.assertFalse(all_passed)
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0].passed)
        self.assertFalse(results[1].passed)


if __name__ == "__main__":
    unittest.main()
