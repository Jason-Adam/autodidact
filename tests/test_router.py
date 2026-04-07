"""Tests for the cost-ascending router."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.router import classify, select_loop_mode


def _write_plan(tmpdir: str, content: str) -> None:
    """Shared helper to write a plan file in a temp directory."""
    plans = Path(tmpdir) / ".planning" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    (plans / "2026-01-01-test.md").write_text(content)


class TestTier0PatternMatch(unittest.TestCase):
    """Tier 0 tests. Implementation skills use a tmpdir with a plan doc
    to bypass the plan gate, so we're testing pattern matching in isolation."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self._tmpdir = self._td.name
        self.addCleanup(self._td.cleanup)
        _write_plan(self._tmpdir, "## Plan\n### Phase 1: Do it\n- [ ] task\n")

    def test_interview_routes_to_plan(self) -> None:
        r = classify("/do interview")
        self.assertEqual(r.skill, "autodidact-plan")
        self.assertEqual(r.tier, 0)

    def test_research_routes_to_research(self) -> None:
        r = classify("/do research")
        self.assertEqual(r.skill, "autodidact-research")
        self.assertEqual(r.tier, 0)

    def test_direct_fleet(self) -> None:
        r = classify("fleet", cwd=self._tmpdir)
        self.assertEqual(r.skill, "autodidact-fleet")
        self.assertEqual(r.tier, 0)

    def test_do_prefix_run(self) -> None:
        r = classify("/do run refactor the DB", cwd=self._tmpdir)
        self.assertEqual(r.skill, "autodidact-run")
        self.assertEqual(r.tier, 0)

    def test_bare_run(self) -> None:
        r = classify("run", cwd=self._tmpdir)
        self.assertEqual(r.skill, "autodidact-run")
        self.assertEqual(r.tier, 0)

    def test_run_does_not_match_natural_language(self) -> None:
        """'run the tests' should NOT route to /run skill."""
        r = classify("run the tests")
        self.assertNotEqual(r.skill, "autodidact-run")

    def test_marshal_legacy_alias(self) -> None:
        r = classify("do marshal", cwd=self._tmpdir)
        self.assertEqual(r.skill, "autodidact-run")
        self.assertEqual(r.tier, 0)

    def test_campaign(self) -> None:
        r = classify("/do campaign", cwd=self._tmpdir)
        self.assertEqual(r.skill, "autodidact-campaign")
        self.assertEqual(r.tier, 0)

    def test_archon_legacy_alias(self) -> None:
        r = classify("archon", cwd=self._tmpdir)
        self.assertEqual(r.skill, "autodidact-campaign")
        self.assertEqual(r.tier, 0)

    def test_learn_status(self) -> None:
        r = classify("/do learn_status")
        self.assertEqual(r.skill, "autodidact-learn-status")
        self.assertEqual(r.tier, 0)

    def test_learn_vs_learn_status_ambiguity(self) -> None:
        """'learn status codes' should route to learn, not learn-status."""
        r = classify("/do learn status codes are important")
        self.assertEqual(r.skill, "autodidact-learn")
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

    def test_forget_routes_to_forget_skill(self) -> None:
        r = classify("/do forget")
        self.assertEqual(r.skill, "autodidact-forget")
        self.assertEqual(r.tier, 0)

    def test_gc_direct(self) -> None:
        r = classify("gc")
        self.assertEqual(r.skill, "autodidact-gc")
        self.assertEqual(r.tier, 0)

    def test_do_gc(self) -> None:
        r = classify("/do gc")
        self.assertEqual(r.skill, "autodidact-gc")
        self.assertEqual(r.tier, 0)

    def test_pr_direct(self) -> None:
        r = classify("pr")
        self.assertEqual(r.skill, "autodidact-create-pr")
        self.assertEqual(r.tier, 0)

    def test_do_pr(self) -> None:
        r = classify("/do pr")
        self.assertEqual(r.skill, "autodidact-create-pr")
        self.assertEqual(r.tier, 0)

    def test_do_create_pr(self) -> None:
        r = classify("/do create-pr")
        self.assertEqual(r.skill, "autodidact-create-pr")
        self.assertEqual(r.tier, 0)

    def test_create_pr_direct(self) -> None:
        r = classify("create pr")
        self.assertEqual(r.skill, "autodidact-create-pr")
        self.assertEqual(r.tier, 0)

    def test_no_match_redirects_to_plan(self) -> None:
        """Unrecognized implementation prompt hits Tier 3 then plan gate."""
        r = classify("build the widget")
        self.assertEqual(r.skill, "autodidact-plan")
        self.assertIn("Plan gate", r.reasoning)


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
            # Plan gate requires a plan doc for implementation skills
            _write_plan(tmpdir, "## Plan\n### Phase 1: Do it\n- [ ] task\n")
            r = classify("continue working", cwd=tmpdir)
            self.assertEqual(r.skill, "autodidact-campaign")
            self.assertEqual(r.tier, 1)

    def test_no_active_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            r = classify("continue working", cwd=tmpdir)
            self.assertNotEqual(r.tier, 1)


class TestTier2KeywordHeuristic(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self._tmpdir = self._td.name
        self.addCleanup(self._td.cleanup)
        _write_plan(self._tmpdir, "## Plan\n### Phase 1: Do it\n- [ ] task\n")

    def test_parallel_routes_to_batch(self) -> None:
        r = classify("execute these tasks in parallel concurrently", cwd=self._tmpdir)
        self.assertEqual(r.skill, "batch")
        self.assertEqual(r.tier, 2)

    def test_worktree_wave_routes_to_fleet(self) -> None:
        r = classify("dispatch these in multi-wave worktree execution", cwd=self._tmpdir)
        self.assertEqual(r.skill, "autodidact-fleet")
        self.assertEqual(r.tier, 2)

    def test_research_keyword_routes_to_research(self) -> None:
        r = classify("deep dive into the authentication flow")
        self.assertEqual(r.skill, "autodidact-research")
        self.assertEqual(r.tier, 2)

    def test_investigate_routes_to_research(self) -> None:
        r = classify("investigate how the database connections work")
        self.assertEqual(r.skill, "autodidact-research")
        self.assertEqual(r.tier, 2)

    def test_plan_routes_to_plan(self) -> None:
        r = classify("design an implementation plan for the auth feature")
        self.assertEqual(r.skill, "autodidact-plan")
        self.assertEqual(r.tier, 2)

    def test_review_routes_to_polish(self) -> None:
        r = classify("code review the changes")
        self.assertEqual(r.skill, "autodidact-polish")
        self.assertEqual(r.tier, 2)

    def test_polish_keyword_routes(self) -> None:
        r = classify("clean up and simplify the module")
        self.assertEqual(r.skill, "autodidact-polish")
        self.assertEqual(r.tier, 2)

    def test_token_savings_routes_to_learn_status(self) -> None:
        r = classify("show my token savings")
        self.assertEqual(r.skill, "autodidact-learn-status")
        self.assertEqual(r.tier, 2)

    def test_rtk_routes_to_learn_status(self) -> None:
        r = classify("rtk stats and learning stats")
        self.assertEqual(r.skill, "autodidact-learn-status")
        self.assertEqual(r.tier, 2)

    def test_commit_keyword_routes_to_gc(self) -> None:
        r = classify("commit these changes and stage everything")
        self.assertEqual(r.skill, "autodidact-gc")
        self.assertEqual(r.tier, 2)

    def test_pull_request_keyword_routes_to_create_pr(self) -> None:
        r = classify("open a pull request for this branch")
        self.assertEqual(r.skill, "autodidact-create-pr")
        self.assertEqual(r.tier, 2)

    def test_low_score_falls_through(self) -> None:
        """Low keyword score falls through to Tier 3, then plan gate redirects."""
        r = classify("fix the bug in the login form")
        # Without a plan doc, the plan gate redirects classify → plan
        self.assertEqual(r.skill, "autodidact-plan")
        self.assertIn("Plan gate", r.reasoning)


class TestTier25PlanAnalysis(unittest.TestCase):
    """Tests for plan-structure-based orchestrator selection."""

    _write_plan = staticmethod(_write_plan)

    def test_single_phase_routes_direct(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_plan(
                tmpdir,
                ("## Plan: Small fix\n### Phase 1: Fix the bug\n- [ ] Edit `src/router.py`\n"),
            )
            r = classify("implement the fix", cwd=tmpdir)
            self.assertEqual(r.skill, "direct")
            self.assertEqual(r.tier, 2)

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

    def test_independent_phases_route_batch(self) -> None:
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
            self.assertEqual(r.skill, "batch")
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

    def test_no_plan_redirects_to_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            r = classify("implement something", cwd=tmpdir)
            # No plan exists — plan gate redirects to /plan at tier 0
            self.assertEqual(r.skill, "autodidact-plan")
            self.assertEqual(r.tier, 0)
            self.assertIn("Plan gate", r.reasoning)

    def test_keyword_match_takes_precedence(self) -> None:
        """Tier 2 keywords should fire before Tier 2.5 plan analysis."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_plan(
                tmpdir, ("## Plan: Small fix\n### Phase 1: Fix\n- [ ] Edit `src/router.py`\n")
            )
            r = classify("code review the changes", cwd=tmpdir)
            self.assertEqual(r.skill, "autodidact-polish")
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
            r = classify("do the thing now", cwd=tmpdir)
            self.assertEqual(r.skill, "autodidact-run")
            self.assertIn("new.md", r.reasoning)


class TestTier3Fallthrough(unittest.TestCase):
    def test_unmatched_without_plan_redirects_to_plan(self) -> None:
        """Without a plan doc, Tier 3 classify is an implementation intent
        and gets redirected to /plan by the plan gate."""
        r = classify("fix the bug in the login form")
        self.assertEqual(r.skill, "autodidact-plan")
        self.assertIn("Plan gate", r.reasoning)

    def test_unmatched_with_plan_routes_via_plan_analysis(self) -> None:
        """With a plan doc, Tier 2.5 plan analysis picks an executor."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_plan(tmpdir, "## Plan\n### Phase 1: Fix\n- [ ] Edit `src/router.py`\n")
            r = classify("fix the bug in the login form", cwd=tmpdir)
            # Single-phase plan → Tier 2.5 routes to direct
            self.assertEqual(r.skill, "direct")
            self.assertEqual(r.tier, 2)


class TestSelectLoopMode(unittest.TestCase):
    """Tests for plan-aware loop mode auto-selection."""

    _write_plan = staticmethod(_write_plan)

    def test_active_campaign_returns_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            campaigns = Path(tmpdir) / ".planning" / "campaigns"
            campaigns.mkdir(parents=True)
            (campaigns / "test.json").write_text(
                json.dumps({"name": "test", "status": "in_progress"})
            )
            self.assertEqual(select_loop_mode(tmpdir), "campaign")

    def test_plan_with_independent_phases_returns_run(self) -> None:
        """Independent phases route to batch, which maps to run in loop mode."""
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
            self.assertEqual(select_loop_mode(tmpdir), "run")

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


class TestModelRouting(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self._tmpdir = self._td.name
        self.addCleanup(self._td.cleanup)
        _write_plan(self._tmpdir, "## Plan\n### Phase 1: Do it\n- [ ] task\n")

    def test_classify_returns_model_field(self) -> None:
        r = classify("fleet", cwd=self._tmpdir)
        self.assertTrue(hasattr(r, "model"))
        self.assertNotEqual(r.model, "")

    def test_fleet_gets_sonnet(self) -> None:
        r = classify("fleet", cwd=self._tmpdir)
        self.assertEqual(r.model, "sonnet")

    def test_research_gets_opus(self) -> None:
        r = classify("/do research")
        self.assertEqual(r.model, "opus")

    def test_campaign_gets_opus(self) -> None:
        r = classify("/do campaign", cwd=self._tmpdir)
        self.assertEqual(r.model, "opus")

    def test_learn_status_gets_haiku(self) -> None:
        r = classify("/do learn-status")
        self.assertEqual(r.model, "haiku")

    def test_forget_gets_haiku(self) -> None:
        r = classify("/do forget")
        self.assertEqual(r.model, "haiku")

    def test_tier3_fallback_gets_plan_model_via_gate(self) -> None:
        """Without a plan doc, Tier 3 is redirected to plan by the gate."""
        r = classify("fix the bug in the login form")
        # Plan gate redirects to plan, which gets sonnet
        self.assertEqual(r.model, "sonnet")

    def test_unknown_skill_defaults_to_sonnet(self) -> None:
        from src.router import RouterResult, _assign_model

        r = _assign_model(RouterResult(skill="unknown-thing", confidence=0.5, tier=2))
        self.assertEqual(r.model, "sonnet")

    def test_all_known_skills_have_model(self) -> None:
        from src.router import _AUTODIDACT_SKILLS, SKILL_MODEL_MAP

        # Every autodidact skill should be in the model map
        for skill in _AUTODIDACT_SKILLS:
            self.assertIn(skill, SKILL_MODEL_MAP, f"Skill '{skill}' missing from SKILL_MODEL_MAP")


class TestPlanGate(unittest.TestCase):
    """Tests for the mandatory plan gate on implementation skills."""

    def test_run_without_plan_redirects_to_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            r = classify("/do run refactor the DB", cwd=tmpdir)
            self.assertEqual(r.skill, "autodidact-plan")
            self.assertIn("Plan gate", r.reasoning)

    def test_run_with_plan_passes_through(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_plan(tmpdir, "## Plan\n### Phase 1: Do it\n- [ ] task\n")
            r = classify("/do run refactor the DB", cwd=tmpdir)
            self.assertEqual(r.skill, "autodidact-run")

    def test_fleet_without_plan_redirects_to_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            r = classify("fleet", cwd=tmpdir)
            self.assertEqual(r.skill, "autodidact-plan")
            self.assertIn("Plan gate", r.reasoning)

    def test_campaign_without_plan_redirects_to_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            r = classify("/do campaign", cwd=tmpdir)
            self.assertEqual(r.skill, "autodidact-plan")
            self.assertIn("Plan gate", r.reasoning)

    def test_utility_skills_exempt_from_gate(self) -> None:
        """Utility skills should never be redirected, even without a plan."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for prompt, expected in [
                ("gc", "autodidact-gc"),
                ("pr", "autodidact-create-pr"),
                ("polish", "autodidact-polish"),
                ("handoff", "autodidact-handoff"),
                ("/do learn something", "autodidact-learn"),
                ("/do research the auth flow", "autodidact-research"),
                ("plan", "autodidact-plan"),
            ]:
                r = classify(prompt, cwd=tmpdir)
                self.assertEqual(
                    r.skill, expected, f"'{prompt}' should route to {expected}, got {r.skill}"
                )

    def test_no_cwd_redirects_to_plan(self) -> None:
        """Without cwd, no plan can be found, so implementation skills redirect."""
        r = classify("fleet")
        self.assertEqual(r.skill, "autodidact-plan")

    def test_tier3_without_plan_redirects_to_plan(self) -> None:
        """Tier 3 classify is implementation-class and gets gated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            r = classify("build a new widget for the dashboard", cwd=tmpdir)
            self.assertEqual(r.skill, "autodidact-plan")
            self.assertIn("Plan gate", r.reasoning)


if __name__ == "__main__":
    unittest.main()
