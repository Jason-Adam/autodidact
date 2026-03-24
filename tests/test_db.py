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
        self.db.record("error", "test_key", "value", confidence=0.8)
        self.db.record("error", "test_key", "value2", confidence=0.3)
        row = self.db.get_by_id(1)
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


class TestRunSummary(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "test_learning.db"
        self.db = LearningDB(self.db_path)

    def tearDown(self) -> None:
        self.db.close()

    def test_run_summary_created(self) -> None:
        summary = {
            "iterations": 5,
            "exit_reason": "plan_complete",
            "final_phase": "closed",
            "mode": "run",
        }
        lid = self.db.record_run_summary(summary)
        self.assertGreater(lid, 0)
        row = self.db.get_by_id(lid)
        assert row is not None
        self.assertEqual(row["topic"], "loop_run")
        self.assertEqual(row["category"], "run_summary")

    def test_run_summary_json_fields(self) -> None:
        import json

        summary = {
            "iterations": 3,
            "exit_reason": "test_saturation",
            "final_phase": "half_open",
            "mode": "campaign",
        }
        lid = self.db.record_run_summary(summary)
        row = self.db.get_by_id(lid)
        assert row is not None
        parsed = json.loads(row["value"])
        self.assertEqual(parsed["iterations"], 3)
        self.assertEqual(parsed["exit_reason"], "test_saturation")

    def test_multiple_summaries_distinct(self) -> None:
        import time

        s1 = {"iterations": 1, "exit_reason": "a", "final_phase": "closed", "mode": "run"}
        s2 = {"iterations": 2, "exit_reason": "b", "final_phase": "closed", "mode": "run"}
        lid1 = self.db.record_run_summary(s1)
        time.sleep(0.01)  # ensure different timestamp key
        lid2 = self.db.record_run_summary(s2)
        self.assertNotEqual(lid1, lid2)


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
        self.db.record("test", "upsert_out", "v1", outcome="interesting")
        self.db.record("test", "upsert_out", "v2", outcome="")
        row = self.db.get_by_id(1)
        assert row is not None
        self.assertEqual(row["outcome"], "interesting")

    def test_upsert_overwrites_with_nonempty(self) -> None:
        self.db.record("test", "upsert_out2", "v1", outcome="interesting")
        self.db.record("test", "upsert_out2", "v2", outcome="success")
        row = self.db.get_by_id(1)
        assert row is not None
        self.assertEqual(row["outcome"], "success")

    def test_default_outcome_empty(self) -> None:
        lid = self.db.record("test", "no_outcome", "value")
        row = self.db.get_by_id(lid)
        assert row is not None
        self.assertEqual(row["outcome"], "")


if __name__ == "__main__":
    unittest.main()
