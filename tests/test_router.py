"""Tests for the cost-ascending router."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.router import classify


class TestTier0PatternMatch(unittest.TestCase):

    def test_interview_routes_to_plan(self) -> None:
        r = classify("/do interview")
        self.assertEqual(r.skill, "plan")
        self.assertEqual(r.tier, 0)

    def test_research_routes_to_plan(self) -> None:
        r = classify("/do research")
        self.assertEqual(r.skill, "plan")
        self.assertEqual(r.tier, 0)

    def test_direct_fleet(self) -> None:
        r = classify("fleet")
        self.assertEqual(r.skill, "fleet")
        self.assertEqual(r.tier, 0)

    def test_do_prefix_run(self) -> None:
        r = classify("/do run refactor the DB")
        self.assertEqual(r.skill, "run")
        self.assertEqual(r.tier, 0)

    def test_bare_run(self) -> None:
        r = classify("run")
        self.assertEqual(r.skill, "run")
        self.assertEqual(r.tier, 0)

    def test_run_does_not_match_natural_language(self) -> None:
        """'run the tests' should NOT route to /run skill."""
        r = classify("run the tests")
        self.assertNotEqual(r.skill, "run")

    def test_marshal_legacy_alias(self) -> None:
        r = classify("do marshal")
        self.assertEqual(r.skill, "run")
        self.assertEqual(r.tier, 0)

    def test_campaign(self) -> None:
        r = classify("/do campaign")
        self.assertEqual(r.skill, "campaign")
        self.assertEqual(r.tier, 0)

    def test_archon_legacy_alias(self) -> None:
        r = classify("archon")
        self.assertEqual(r.skill, "campaign")
        self.assertEqual(r.tier, 0)

    def test_learn_status(self) -> None:
        r = classify("/do learn_status")
        self.assertEqual(r.skill, "learn_status")
        self.assertEqual(r.tier, 0)

    def test_case_insensitive(self) -> None:
        r = classify("INTERVIEW")
        self.assertEqual(r.skill, "plan")  # interview consolidated into plan
        self.assertEqual(r.tier, 0)

    def test_no_match(self) -> None:
        r = classify("build the widget")
        self.assertNotEqual(r.tier, 0)


class TestTier1ActiveState(unittest.TestCase):

    def test_active_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            campaigns = Path(tmpdir) / ".planning" / "campaigns"
            campaigns.mkdir(parents=True)
            (campaigns / "test.json").write_text(json.dumps({
                "name": "test campaign",
                "status": "in_progress",
            }))
            r = classify("continue working", cwd=tmpdir)
            self.assertEqual(r.skill, "campaign")
            self.assertEqual(r.tier, 1)

    def test_no_active_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            r = classify("continue working", cwd=tmpdir)
            self.assertNotEqual(r.tier, 1)


class TestTier2KeywordHeuristic(unittest.TestCase):

    def test_parallel_routes_to_fleet(self) -> None:
        r = classify("execute these tasks in parallel across worktrees")
        self.assertEqual(r.skill, "fleet")
        self.assertEqual(r.tier, 2)

    def test_plan_routes_to_plan(self) -> None:
        r = classify("create an implementation plan for the auth feature")
        self.assertEqual(r.skill, "plan")
        self.assertEqual(r.tier, 2)

    def test_review_routes_to_review(self) -> None:
        r = classify("code review the changes")
        self.assertEqual(r.skill, "review")
        self.assertEqual(r.tier, 2)

    def test_low_score_falls_through(self) -> None:
        r = classify("fix the bug in the login form")
        self.assertEqual(r.tier, 3)  # Falls through to LLM


class TestTier3Fallthrough(unittest.TestCase):

    def test_unmatched_returns_classify(self) -> None:
        r = classify("fix the bug in the login form")
        self.assertEqual(r.skill, "classify")
        self.assertEqual(r.tier, 3)
        self.assertAlmostEqual(r.confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
