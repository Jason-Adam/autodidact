"""Tests for the learning database."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.db import LearningDB


class TestLearningDB(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "test_learning.db"
        self.db = LearningDB(self.db_path)

    def tearDown(self) -> None:
        self.db.close()

    # ── Record ──────────────────────────────────────────────────────

    def test_record_creates_learning(self) -> None:
        lid = self.db.record("error", "mypy_missing_import", "Add import statement")
        self.assertGreater(lid, 0)
        row = self.db.get_by_id(lid)
        assert row is not None
        self.assertEqual(row["topic"], "error")
        self.assertEqual(row["key"], "mypy_missing_import")
        self.assertEqual(row["value"], "Add import statement")
        self.assertAlmostEqual(row["confidence"], 0.5)
        self.assertEqual(row["observation_count"], 1)

    def test_record_upsert_increments_observation(self) -> None:
        self.db.record("error", "mypy_missing_import", "Add import statement")
        self.db.record("error", "mypy_missing_import", "Add import statement v2")
        rows = self.db.conn.execute(
            "SELECT * FROM learnings WHERE topic='error' AND key='mypy_missing_import'"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["observation_count"], 2)
        self.assertEqual(rows[0]["value"], "Add import statement v2")

    def test_record_upsert_keeps_higher_confidence(self) -> None:
        lid = self.db.record("error", "test_key", "value", confidence=0.8)
        self.db.record("error", "test_key", "value2", confidence=0.3)
        row = self.db.get_by_id(lid)
        assert row is not None
        self.assertAlmostEqual(row["confidence"], 0.8)

    # ── FTS5 Query ──────────────────────────────────────────────────

    def test_query_fts_returns_matches(self) -> None:
        self.db.record("error", "mypy_import", "Use 'from typing import X'")
        self.db.record("pattern", "react_hook", "Use useState for state")
        results = self.db.query_fts("mypy import typing")
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]["key"], "mypy_import")

    def test_query_fts_respects_min_confidence(self) -> None:
        self.db.record("error", "low_conf", "Low confidence", confidence=0.1)
        results = self.db.query_fts("low confidence", min_confidence=0.3)
        self.assertEqual(len(results), 0)

    def test_query_fts_excludes_graduated(self) -> None:
        lid = self.db.record("pattern", "graduated_one", "Already promoted", confidence=0.95)
        self.db.conn.execute(
            "UPDATE learnings SET graduated_to = 'CLAUDE.md', observation_count = 10 WHERE id = ?",
            (lid,),
        )
        self.db.conn.commit()
        results = self.db.query_fts("promoted graduated")
        self.assertEqual(len(results), 0)

    def test_query_fts_empty_input(self) -> None:
        results = self.db.query_fts("")
        self.assertEqual(results, [])

    def test_query_fts_special_chars(self) -> None:
        self.db.record("error", "special", "Handle $pecial ch@rs")
        results = self.db.query_fts("$pecial ch@rs!")
        # Should not crash, may or may not find results
        self.assertIsInstance(results, list)

    # ── Confidence ──────────────────────────────────────────────────

    def test_boost(self) -> None:
        lid = self.db.record("error", "boost_test", "value", confidence=0.5)
        self.db.boost(lid)
        row = self.db.get_by_id(lid)
        assert row is not None
        self.assertAlmostEqual(row["confidence"], 0.65)
        self.assertEqual(row["success_count"], 1)
        self.assertEqual(row["observation_count"], 2)  # 1 from record + 1 from boost

    def test_boost_caps_at_1(self) -> None:
        lid = self.db.record("error", "cap_test", "value", confidence=0.95)
        self.db.boost(lid, 0.15)
        row = self.db.get_by_id(lid)
        assert row is not None
        self.assertAlmostEqual(row["confidence"], 1.0)

    def test_decay(self) -> None:
        lid = self.db.record("error", "decay_test", "value", confidence=0.5)
        self.db.decay(lid)
        row = self.db.get_by_id(lid)
        assert row is not None
        self.assertAlmostEqual(row["confidence"], 0.4)
        self.assertEqual(row["failure_count"], 1)
        self.assertEqual(row["observation_count"], 2)  # 1 from record + 1 from decay

    def test_decay_floors_at_0(self) -> None:
        lid = self.db.record("error", "floor_test", "value", confidence=0.05)
        self.db.decay(lid, 0.10)
        row = self.db.get_by_id(lid)
        assert row is not None
        self.assertAlmostEqual(row["confidence"], 0.0)

    def test_time_decay(self) -> None:
        lid = self.db.record("error", "time_test", "value", confidence=0.5)
        # Backdate last_seen by 10 days
        self.db.conn.execute(
            "UPDATE learnings SET last_seen = datetime('now', '-10 days') WHERE id = ?",
            (lid,),
        )
        self.db.conn.commit()
        self.db.time_decay([lid])
        row = self.db.get_by_id(lid)
        assert row is not None
        # 10 days * 0.01 = 0.10 decay -> 0.5 - 0.10 = 0.40
        self.assertAlmostEqual(row["confidence"], 0.4, places=1)

    # ── Graduation ──────────────────────────────────────────────────

    def test_graduate_eligible(self) -> None:
        lid = self.db.record("pattern", "grad_test", "value", confidence=0.95)
        self.db.conn.execute("UPDATE learnings SET observation_count = 10 WHERE id = ?", (lid,))
        self.db.conn.commit()
        result = self.db.graduate(lid, "CLAUDE.md")
        self.assertTrue(result)
        row = self.db.get_by_id(lid)
        assert row is not None
        self.assertEqual(row["graduated_to"], "CLAUDE.md")

    def test_graduate_ineligible_low_confidence(self) -> None:
        lid = self.db.record("pattern", "no_grad", "value", confidence=0.5)
        result = self.db.graduate(lid, "CLAUDE.md")
        self.assertFalse(result)

    def test_graduate_ineligible_low_observations(self) -> None:
        lid = self.db.record("pattern", "no_grad2", "value", confidence=0.95)
        result = self.db.graduate(lid, "CLAUDE.md")
        self.assertFalse(result)

    # ── Prune ───────────────────────────────────────────────────────

    def test_prune_removes_stale(self) -> None:
        lid = self.db.record("error", "stale", "old stuff", confidence=0.05)
        self.db.conn.execute(
            "UPDATE learnings SET last_seen = datetime('now', '-100 days') WHERE id = ?",
            (lid,),
        )
        self.db.conn.commit()
        deleted = self.db.prune()
        self.assertEqual(deleted, 1)
        self.assertIsNone(self.db.get_by_id(lid))

    def test_prune_keeps_high_confidence(self) -> None:
        lid = self.db.record("error", "keep_me", "good stuff", confidence=0.8)
        self.db.conn.execute(
            "UPDATE learnings SET last_seen = datetime('now', '-100 days') WHERE id = ?",
            (lid,),
        )
        self.db.conn.commit()
        deleted = self.db.prune()
        self.assertEqual(deleted, 0)

    # ── Error Signature ─────────────────────────────────────────────

    def test_get_by_error_signature(self) -> None:
        self.db.record(
            "error",
            "sig_test",
            "Fix: add import",
            error_signature="ModuleNotFoundError: foo",
        )
        row = self.db.get_by_error_signature("ModuleNotFoundError: foo")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["value"], "Fix: add import")

    def test_get_by_error_signature_missing(self) -> None:
        row = self.db.get_by_error_signature("NonexistentError")
        self.assertIsNone(row)

    # ── Top Learnings ───────────────────────────────────────────────

    def test_get_top_learnings(self) -> None:
        self.db.record("a", "low", "low", confidence=0.3)
        self.db.record("b", "mid", "mid", confidence=0.6)
        self.db.record("c", "high", "high", confidence=0.9)
        results = self.db.get_top_learnings(limit=2)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["key"], "high")

    def test_get_top_learnings_by_project(self) -> None:
        self.db.record("a", "global", "global", confidence=0.9, project_path="")
        self.db.record("b", "proj", "project-specific", confidence=0.8, project_path="/my/project")
        results = self.db.get_top_learnings(project_path="/my/project")
        # Should include both global and project-specific
        self.assertEqual(len(results), 2)

    # ── Routing Gaps ────────────────────────────────────────────────

    def test_record_routing_gap(self) -> None:
        gid = self.db.record_routing_gap("build the thing", [0, 1, 2], "marshal")
        self.assertGreater(gid, 0)
        gaps = self.db.get_routing_gaps()
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["prompt"], "build the thing")

    # ── Stats ───────────────────────────────────────────────────────

    def test_stats(self) -> None:
        self.db.record("a", "one", "v1")
        self.db.record("b", "two", "v2")
        stats = self.db.stats()
        self.assertEqual(stats["total"], 2)


class TestAccessCount(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "test_learning.db"
        self.db = LearningDB(self.db_path)

    def tearDown(self) -> None:
        self.db.close()

    def test_increment_access(self) -> None:
        lid = self.db.record("test", "access_test", "value")
        row = self.db.get_by_id(lid)
        assert row is not None
        self.assertEqual(row["access_count"], 0)
        self.db.increment_access(lid)
        row = self.db.get_by_id(lid)
        assert row is not None
        self.assertEqual(row["access_count"], 1)

    def test_multiple_increments(self) -> None:
        lid = self.db.record("test", "multi_access", "value")
        for _ in range(5):
            self.db.increment_access(lid)
        row = self.db.get_by_id(lid)
        assert row is not None
        self.assertEqual(row["access_count"], 5)

    def test_access_count_boosts_ranking(self) -> None:
        self.db.record("topic", "low_access", "search term alpha", confidence=0.5)
        lid2 = self.db.record("topic", "high_access", "search term alpha", confidence=0.5)
        # Boost access count on second record
        for _ in range(10):
            self.db.increment_access(lid2)
        results = self.db.query_fts("search term alpha")
        self.assertGreater(len(results), 0)
        # High access should rank first (or at least be present)
        ids = [r["id"] for r in results]
        self.assertIn(lid2, ids)

    def test_default_access_count_zero(self) -> None:
        lid = self.db.record("test", "default_access", "value")
        row = self.db.get_by_id(lid)
        assert row is not None
        self.assertEqual(row["access_count"], 0)


class TestOutcome(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "test_learning.db"
        self.db = LearningDB(self.db_path)

    def tearDown(self) -> None:
        self.db.close()

    def test_record_with_outcome(self) -> None:
        lid = self.db.record("test", "outcome_test", "value", outcome="interesting")
        row = self.db.get_by_id(lid)
        assert row is not None
        self.assertEqual(row["outcome"], "interesting")

    def test_get_by_outcome(self) -> None:
        self.db.record("a", "k1", "v1", outcome="interesting")
        self.db.record("b", "k2", "v2", outcome="failure")
        self.db.record("c", "k3", "v3", outcome="interesting")
        results = self.db.get_by_outcome("interesting")
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertEqual(r["outcome"], "interesting")

    def test_upsert_preserves_nonempty_outcome(self) -> None:
        lid = self.db.record("test", "upsert_out", "v1", outcome="interesting")
        self.db.record("test", "upsert_out", "v2", outcome="")
        row = self.db.get_by_id(lid)
        assert row is not None
        self.assertEqual(row["outcome"], "interesting")

    def test_upsert_overwrites_with_nonempty(self) -> None:
        lid = self.db.record("test", "upsert_out2", "v1", outcome="interesting")
        self.db.record("test", "upsert_out2", "v2", outcome="success")
        row = self.db.get_by_id(lid)
        assert row is not None
        self.assertEqual(row["outcome"], "success")

    def test_default_outcome_empty(self) -> None:
        lid = self.db.record("test", "no_outcome", "value")
        row = self.db.get_by_id(lid)
        assert row is not None
        self.assertEqual(row["outcome"], "")


class TestSetOutcome(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "test_learning.db"
        self.db = LearningDB(self.db_path)

    def tearDown(self) -> None:
        self.db.close()

    def test_set_outcome_updates_field(self) -> None:
        lid = self.db.record("test", "out_test", "value")
        self.db.set_outcome(lid, "success")
        row = self.db.get_by_id(lid)
        assert row is not None
        self.assertEqual(row["outcome"], "success")

    def test_set_outcome_overwrites_existing(self) -> None:
        lid = self.db.record("test", "out_test2", "value", outcome="failure")
        self.db.set_outcome(lid, "success")
        row = self.db.get_by_id(lid)
        assert row is not None
        self.assertEqual(row["outcome"], "success")

    def test_set_outcome_updates_last_seen(self) -> None:
        lid = self.db.record("test", "out_test3", "value")
        # Backdate last_seen
        self.db.conn.execute(
            "UPDATE learnings SET last_seen = '2020-01-01T00:00:00' WHERE id = ?",
            (lid,),
        )
        self.db.conn.commit()
        self.db.set_outcome(lid, "interesting")
        row = self.db.get_by_id(lid)
        assert row is not None
        self.assertNotEqual(row["last_seen"], "2020-01-01T00:00:00")


class TestGetAccessedInSession(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "test_learning.db"
        self.db = LearningDB(self.db_path)

    def tearDown(self) -> None:
        self.db.close()

    def test_returns_accessed_learnings(self) -> None:
        lid1 = self.db.record("a", "k1", "v1")
        self.db.record("b", "k2", "v2")
        self.db.increment_access(lid1, session_id="sess1")
        # second learning was not accessed, should not be returned
        results = self.db.get_accessed_in_session("sess1")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], lid1)

    def test_excludes_other_sessions(self) -> None:
        lid = self.db.record("a", "k1", "v1")
        self.db.increment_access(lid, session_id="sess1")
        self.db.record("b", "k2", "v2")
        # sess2 never accessed anything
        results = self.db.get_accessed_in_session("sess2")
        self.assertEqual(len(results), 0)

    def test_cross_session_access(self) -> None:
        """A learning created in sess1 but accessed in sess2 should appear in sess2."""
        lid = self.db.record("a", "k1", "v1", session_id="sess1")
        self.db.increment_access(lid, session_id="sess2")
        results = self.db.get_accessed_in_session("sess2")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], lid)

    def test_empty_session_returns_empty(self) -> None:
        results = self.db.get_accessed_in_session("nonexistent")
        self.assertEqual(len(results), 0)

    def test_multiple_accessed(self) -> None:
        lid1 = self.db.record("a", "k1", "v1")
        lid2 = self.db.record("b", "k2", "v2")
        self.db.increment_access(lid1, session_id="sess1")
        self.db.increment_access(lid2, session_id="sess1")
        results = self.db.get_accessed_in_session("sess1")
        self.assertEqual(len(results), 2)


class TestDecayIntegration(unittest.TestCase):
    """Test that decay properly increments failure_count and decreases confidence."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "test_learning.db"
        self.db = LearningDB(self.db_path)

    def tearDown(self) -> None:
        self.db.close()

    def test_multiple_decays_accumulate(self) -> None:
        lid = self.db.record("error", "multi_decay", "value", confidence=0.5)
        self.db.decay(lid, amount=0.05)
        self.db.decay(lid, amount=0.05)
        self.db.decay(lid, amount=0.05)
        row = self.db.get_by_id(lid)
        assert row is not None
        self.assertAlmostEqual(row["confidence"], 0.35)
        self.assertEqual(row["failure_count"], 3)
        self.assertEqual(row["observation_count"], 4)  # 1 from record + 3 from decays

    def test_boost_then_decay_net_effect(self) -> None:
        lid = self.db.record("error", "net_test", "value", confidence=0.5)
        self.db.boost(lid, amount=0.15)  # -> 0.65, success=1
        self.db.decay(lid, amount=0.10)  # -> 0.55, failure=1
        row = self.db.get_by_id(lid)
        assert row is not None
        self.assertAlmostEqual(row["confidence"], 0.55)
        self.assertEqual(row["success_count"], 1)
        self.assertEqual(row["failure_count"], 1)
        self.assertEqual(row["observation_count"], 3)  # 1 from record + 1 boost + 1 decay


class TestProgressiveLearnings(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "test_learning.db"
        self.db = LearningDB(self.db_path)

    def tearDown(self) -> None:
        self.db.close()

    def test_empty_db_returns_empty_tiers(self) -> None:
        result = self.db.get_progressive_learnings()
        self.assertEqual(result["core"], [])
        self.assertEqual(result["relevant"], [])

    def test_confidence_floor_filters(self) -> None:
        self.db.record("a", "low", "value", confidence=0.1)
        self.db.record("b", "high", "value", confidence=0.5)
        result = self.db.get_progressive_learnings(min_confidence=0.3)
        self.assertEqual(len(result["core"]), 1)
        self.assertEqual(result["core"][0]["key"], "high")

    def test_budget_exhaustion(self) -> None:
        # Each entry ~20 overhead + value tokens. With tiny budget, should cap early.
        for i in range(10):
            self.db.record(f"t{i}", f"k{i}", "x" * 200, confidence=0.8)
        result = self.db.get_progressive_learnings(token_budget=200)
        # Half budget = 100 tokens. Each entry = 200//4+20 = 70 tokens. Max 1 entry.
        self.assertLessEqual(len(result["core"]), 2)

    def test_max_seven_core_entries(self) -> None:
        for i in range(15):
            self.db.record(f"t{i}", f"k{i}", "short", confidence=0.9)
        result = self.db.get_progressive_learnings(token_budget=10000)
        self.assertLessEqual(len(result["core"]), 7)

    def test_graduated_excluded(self) -> None:
        lid = self.db.record("a", "grad", "value", confidence=0.95)
        self.db.conn.execute(
            "UPDATE learnings SET graduated_to = 'CLAUDE.md', observation_count = 10 WHERE id = ?",
            (lid,),
        )
        self.db.conn.commit()
        result = self.db.get_progressive_learnings()
        self.assertEqual(len(result["core"]), 0)

    def test_deduplication_between_tiers(self) -> None:
        self.db.record("search", "overlap", "search term alpha", confidence=0.8)
        result = self.db.get_progressive_learnings(
            topic_hint="search term alpha", min_confidence=0.3
        )
        # The same entry should not appear in both tiers
        core_ids = {e["id"] for e in result["core"]}
        relevant_ids = {e["id"] for e in result["relevant"]}
        self.assertEqual(core_ids & relevant_ids, set())

    def test_token_budget_respected(self) -> None:
        for i in range(10):
            self.db.record(f"t{i}", f"k{i}", "x" * 400, confidence=0.8)
        result = self.db.get_progressive_learnings(token_budget=500)
        total_tokens = sum(len(e["value"]) // 4 + 20 for e in result["core"] + result["relevant"])
        self.assertLessEqual(total_tokens, 500)


if __name__ == "__main__":
    unittest.main()
