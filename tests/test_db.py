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


if __name__ == "__main__":
    unittest.main()
