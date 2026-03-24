"""Tests for the cost-ascending router."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.router import classify, select_loop_mode


class TestTier0PatternMatch(unittest.TestCase):
    def test_interview_routes_to_plan(self) -> None:
        r = classify("/do interview")
        self.assertEqual(r.skill, "autodidact-plan")
        self.assertEqual(r.tier, 0)

    def test_research_routes_to_plan(self) -> None:
        r = classify("/do research")
        self.assertEqual(r.skill, "autodidact-plan")
        self.assertEqual(r.tier, 0)

    def test_direct_fleet(self) -> None:
        r = classify("fleet")
        self.assertEqual(r.skill, "autodidact-fleet")
        self.assertEqual(r.tier, 0)

    def test_do_prefix_run(self) -> None:
        r = classify("/do run refactor the DB")
        self.assertEqual(r.skill, "autodidact-run")
        self.assertEqual(r.tier, 0)

    def test_bare_run(self) -> None:
        r = classify("run")
        self.assertEqual(r.skill, "autodidact-run")
        self.assertEqual(r.tier, 0)

    def test_run_does_not_match_natural_language(self) -> None:
        """'run the tests' should NOT route to /run skill."""
        r = classify("run the tests")
        self.assertNotEqual(r.skill, "autodidact-run")

    def test_marshal_legacy_alias(self) -> None:
        r = classify("do marshal")
        self.assertEqual(r.skill, "autodidact-run")
        self.assertEqual(r.tier, 0)

    def test_campaign(self) -> None:
        r = classify("/do campaign")
        self.assertEqual(r.skill, "autodidact-campaign")
        self.assertEqual(r.tier, 0)

    def test_archon_legacy_alias(self) -> None:
        r = classify("archon")
        self.assertEqual(r.skill, "autodidact-campaign")
        self.assertEqual(r.tier, 0)

    def test_learn_status(self) -> None:
        """learn_status is command-only, no autodidact- prefix."""
        r = classify("/do learn_status")
        self.assertEqual(r.skill, "learn_status")
        self.assertEqual(r.tier, 0)

    def test_case_insensitive(self) -> None:
        r = classify("INTERVIEW")
        self.assertEqual(r.skill, "autodidact-plan")  # interview consolidated into plan
        self.assertEqual(r.tier, 0)

    def test_polish_direct(self) -> None:
        r = classify("polish")
        self.assertEqual(r.skill, "autodidact-polish")
        self.assertEqual(r.tier, 0)

    def test_do_polish(self) -> None:
        r = classify("/do polish the code")
        self.assertEqual(r.skill, "autodidact-polish")
        self.assertEqual(r.tier, 0)

    def test_loop_routes_to_loop(self) -> None:
        r = classify("/do loop")
        self.assertEqual(r.skill, "autodidact-loop")
        self.assertEqual(r.tier, 0)

    def test_bare_loop(self) -> None:
        r = classify("loop")
        self.assertEqual(r.skill, "autodidact-loop")
        self.assertEqual(r.tier, 0)

    def test_loop_with_mode(self) -> None:
        r = classify("/do loop fleet")
        self.assertEqual(r.skill, "autodidact-loop")
        self.assertEqual(r.tier, 0)

    def test_loop_does_not_match_natural_language(self) -> None:
        """'loop through the array' should NOT route to /loop skill."""
        r = classify("loop through the array")
        self.assertNotEqual(r.skill, "autodidact-loop")

    def test_no_match(self) -> None:
        r = classify("build the widget")
        self.assertNotEqual(r.tier, 0)


class TestTier1ActiveState(unittest.TestCase):
    def test_active_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            campaigns = Path(tmpdir) / ".planning" / "campaigns"
            campaigns.mkdir(parents=True)
            (campaigns / "test.json").write_text(
                json.dumps(
                    {
                        "name": "test campaign",
                        "status": "in_progress",
                    }
                )
            )
            r = classify("continue working", cwd=tmpdir)
            self.assertEqual(r.skill, "autodidact-campaign")
            self.assertEqual(r.tier, 1)

    def test_no_active_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            r = classify("continue working", cwd=tmpdir)
            self.assertNotEqual(r.tier, 1)


class TestTier2KeywordHeuristic(unittest.TestCase):
    def test_parallel_routes_to_fleet(self) -> None:
        r = classify("execute these tasks in parallel across worktrees")
        self.assertEqual(r.skill, "autodidact-fleet")
        self.assertEqual(r.tier, 2)

    def test_plan_routes_to_plan(self) -> None:
        r = classify("create an implementation plan for the auth feature")
        self.assertEqual(r.skill, "autodidact-plan")
        self.assertEqual(r.tier, 2)

    def test_review_routes_to_review(self) -> None:
        """review is command-only, no autodidact- prefix."""
        r = classify("code review the changes")
        self.assertEqual(r.skill, "review")
        self.assertEqual(r.tier, 2)

    def test_polish_keyword_routes(self) -> None:
        r = classify("clean up and simplify the module")
        self.assertEqual(r.skill, "autodidact-polish")
        self.assertEqual(r.tier, 2)

    def test_low_score_falls_through(self) -> None:
        r = classify("fix the bug in the login form")
        self.assertEqual(r.tier, 3)  # Falls through to LLM


class TestTier25PlanAnalysis(unittest.TestCase):
    """Tests for plan-structure-based orchestrator selection."""

    def _write_plan(self, tmpdir: str, content: str) -> None:
        plans = Path(tmpdir) / ".planning" / "plans"
        plans.mkdir(parents=True, exist_ok=True)
        (plans / "2026-01-01-test.md").write_text(content)

    def test_single_phase_routes_direct(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_plan(
                tmpdir,
                ("## Plan: Small fix\n### Phase 1: Fix the bug\n- [ ] Edit `src/router.py`\n"),
            )
            r = classify("implement the fix", cwd=tmpdir)
            self.assertEqual(r.skill, "direct")

    def test_sequential_phases_route_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_plan(
                tmpdir,
                (
                    "## Plan: Auth refactor\n"
                    "### Phase 1: Update models\n"
                    "- [ ] Edit `src/models.py`\n"
                    "### Phase 2: Update routes\n"
                    "- [ ] Edit `src/models.py`\n"
                    "- [ ] Edit `src/routes.py`\n"
                    "### Phase 3: Add tests\n"
                    "- [ ] Edit `tests/test_auth.py`\n"
                ),
            )
            r = classify("implement the auth refactor", cwd=tmpdir)
            self.assertEqual(r.skill, "autodidact-run")
            self.assertIn("3 sequential phases", r.reasoning)

    def test_independent_phases_route_fleet(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_plan(
                tmpdir,
                (
                    "## Plan: Multi-module update\n"
                    "### Phase 1: Update auth\n"
                    "- [ ] Edit `src/auth.py`\n"
                    "### Phase 2: Update billing\n"
                    "- [ ] Edit `src/billing.py`\n"
                    "### Phase 3: Update notifications\n"
                    "- [ ] Edit `src/notifications.py`\n"
                ),
            )
            r = classify("implement the multi-module update", cwd=tmpdir)
            self.assertEqual(r.skill, "autodidact-fleet")
            self.assertIn("independent phases", r.reasoning)

    def test_large_plan_routes_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            phases = ""
            for i in range(1, 8):
                phases += (
                    f"### Phase {i}: Step {i}\n"
                    f"- [ ] Edit `src/file{i}.py`\n"
                    f"- [ ] Edit `src/shared.py`\n"
                )
            self._write_plan(tmpdir, f"## Plan: Big migration\n{phases}")
            r = classify("implement the migration", cwd=tmpdir)
            self.assertEqual(r.skill, "autodidact-campaign")
            self.assertIn("7 phases", r.reasoning)

    def test_no_plan_falls_through(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            r = classify("implement something", cwd=tmpdir)
            # No plan exists, should fall through to Tier 3
            self.assertEqual(r.tier, 3)

    def test_keyword_match_takes_precedence(self) -> None:
        """Tier 2 keywords should fire before Tier 2.5 plan analysis."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_plan(
                tmpdir, ("## Plan: Small fix\n### Phase 1: Fix\n- [ ] Edit `src/router.py`\n")
            )
            r = classify("code review the changes", cwd=tmpdir)
            self.assertEqual(r.skill, "review")
            self.assertEqual(r.tier, 2)

    def test_most_recent_plan_is_used(self) -> None:
        """When multiple plans exist, the most recent (by filename) is used."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plans = Path(tmpdir) / ".planning" / "plans"
            plans.mkdir(parents=True)
            # Older plan: single phase → direct
            (plans / "2026-01-01-old.md").write_text(
                "## Plan: Old\n### Phase 1: Fix\n- [ ] Edit `src/old.py`\n"
            )
            # Newer plan: 3 sequential phases → run
            (plans / "2026-03-01-new.md").write_text(
                "## Plan: New\n"
                "### Phase 1: A\n- [ ] Edit `src/a.py`\n"
                "### Phase 2: B\n- [ ] Edit `src/a.py`\n"
                "### Phase 3: C\n- [ ] Edit `src/c.py`\n"
            )
            r = classify("implement the plan", cwd=tmpdir)
            self.assertEqual(r.skill, "autodidact-run")
            self.assertIn("new.md", r.reasoning)


class TestTier3Fallthrough(unittest.TestCase):
    def test_unmatched_returns_classify(self) -> None:
        r = classify("fix the bug in the login form")
        self.assertEqual(r.skill, "classify")
        self.assertEqual(r.tier, 3)
        self.assertAlmostEqual(r.confidence, 0.0)


class TestSelectLoopMode(unittest.TestCase):
    """Tests for plan-aware loop mode auto-selection."""

    def _write_plan(self, tmpdir: str, content: str) -> None:
        plans = Path(tmpdir) / ".planning" / "plans"
        plans.mkdir(parents=True, exist_ok=True)
        (plans / "2026-01-01-test.md").write_text(content)

    def test_active_campaign_returns_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            campaigns = Path(tmpdir) / ".planning" / "campaigns"
            campaigns.mkdir(parents=True)
            (campaigns / "test.json").write_text(
                json.dumps({"name": "test", "status": "in_progress"})
            )
            self.assertEqual(select_loop_mode(tmpdir), "campaign")

    def test_plan_with_independent_phases_returns_fleet(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_plan(
                tmpdir,
                (
                    "## Plan\n"
                    "### Phase 1: Auth\n- [ ] Edit `src/auth.py`\n"
                    "### Phase 2: Billing\n- [ ] Edit `src/billing.py`\n"
                    "### Phase 3: Notify\n- [ ] Edit `src/notify.py`\n"
                ),
            )
            self.assertEqual(select_loop_mode(tmpdir), "fleet")

    def test_plan_with_sequential_phases_returns_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_plan(
                tmpdir,
                (
                    "## Plan\n"
                    "### Phase 1: Models\n- [ ] Edit `src/models.py`\n"
                    "### Phase 2: Routes\n- [ ] Edit `src/models.py`\n"
                    "- [ ] Edit `src/routes.py`\n"
                ),
            )
            self.assertEqual(select_loop_mode(tmpdir), "run")

    def test_single_phase_returns_run(self) -> None:
        """Single-phase plan maps 'direct' to 'run' for loop mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_plan(
                tmpdir,
                "## Plan\n### Phase 1: Fix\n- [ ] Edit `src/router.py`\n",
            )
            self.assertEqual(select_loop_mode(tmpdir), "run")

    def test_large_plan_returns_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            phases = ""
            for i in range(1, 8):
                phases += (
                    f"### Phase {i}: Step {i}\n"
                    f"- [ ] Edit `src/file{i}.py`\n"
                    f"- [ ] Edit `src/shared.py`\n"
                )
            self._write_plan(tmpdir, f"## Plan\n{phases}")
            self.assertEqual(select_loop_mode(tmpdir), "campaign")

    def test_no_plan_defaults_to_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(select_loop_mode(tmpdir), "run")


if __name__ == "__main__":
    unittest.main()
