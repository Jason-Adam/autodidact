"""Tests for the task dependency graph."""

from __future__ import annotations

import unittest

from src.task_graph import TaskGraph, TaskNode


class TestGraphConstruction(unittest.TestCase):
    def test_no_tasks_empty_partition(self) -> None:
        g = TaskGraph()
        self.assertEqual(g.partition_waves(), [])

    def test_single_task(self) -> None:
        g = TaskGraph()
        g.add_task(TaskNode(task_id="a", description="do a"))
        waves = g.partition_waves()
        self.assertEqual(waves, [["a"]])


class TestExplicitDependencies(unittest.TestCase):
    def test_chain_a_b_c(self) -> None:
        g = TaskGraph()
        g.add_task(TaskNode(task_id="a", description="a"))
        g.add_task(TaskNode(task_id="b", description="b", depends_on=["a"]))
        g.add_task(TaskNode(task_id="c", description="c", depends_on=["b"]))
        waves = g.partition_waves()
        self.assertEqual(len(waves), 3)
        self.assertEqual(waves[0], ["a"])
        self.assertEqual(waves[1], ["b"])
        self.assertEqual(waves[2], ["c"])

    def test_diamond_dependency(self) -> None:
        """A -> B, A -> C, B -> D, C -> D"""
        g = TaskGraph()
        g.add_task(TaskNode(task_id="a", description="a"))
        g.add_task(TaskNode(task_id="b", description="b", depends_on=["a"]))
        g.add_task(TaskNode(task_id="c", description="c", depends_on=["a"]))
        g.add_task(TaskNode(task_id="d", description="d", depends_on=["b", "c"]))
        waves = g.partition_waves()
        self.assertEqual(waves[0], ["a"])
        self.assertIn("b", waves[1])
        self.assertIn("c", waves[1])
        self.assertEqual(waves[-1], ["d"])


class TestFileOverlapEdges(unittest.TestCase):
    def test_no_overlap_single_wave(self) -> None:
        g = TaskGraph()
        g.add_task(TaskNode(task_id="a", description="a", target_files=["src/a.py"]))
        g.add_task(TaskNode(task_id="b", description="b", target_files=["src/b.py"]))
        g.add_task(TaskNode(task_id="c", description="c", target_files=["src/c.py"]))
        waves = g.partition_waves()
        self.assertEqual(len(waves), 1)
        self.assertEqual(len(waves[0]), 3)

    def test_overlap_creates_dependency(self) -> None:
        g = TaskGraph()
        g.add_task(TaskNode(task_id="a", description="a", target_files=["src/shared.py"]))
        g.add_task(TaskNode(task_id="b", description="b", target_files=["src/shared.py"]))
        waves = g.partition_waves()
        self.assertEqual(len(waves), 2)
        self.assertEqual(waves[0], ["a"])
        self.assertEqual(waves[1], ["b"])

    def test_partial_overlap(self) -> None:
        """A overlaps B, C is independent."""
        g = TaskGraph()
        g.add_task(TaskNode(task_id="a", description="a", target_files=["src/x.py"]))
        g.add_task(TaskNode(task_id="b", description="b", target_files=["src/x.py", "src/y.py"]))
        g.add_task(TaskNode(task_id="c", description="c", target_files=["src/z.py"]))
        waves = g.partition_waves()
        # a and c should be in wave 1, b in wave 2
        self.assertIn("a", waves[0])
        self.assertIn("c", waves[0])
        self.assertIn("b", waves[1])


class TestMaxPerWave(unittest.TestCase):
    def test_four_independent_tasks_split(self) -> None:
        g = TaskGraph(max_per_wave=3)
        for i in range(4):
            g.add_task(
                TaskNode(task_id=f"t{i}", description=f"task {i}", target_files=[f"f{i}.py"])
            )
        waves = g.partition_waves()
        self.assertEqual(len(waves), 2)
        self.assertEqual(len(waves[0]), 3)
        self.assertEqual(len(waves[1]), 1)

    def test_max_per_wave_respected(self) -> None:
        g = TaskGraph(max_per_wave=2)
        for i in range(6):
            g.add_task(
                TaskNode(task_id=f"t{i}", description=f"task {i}", target_files=[f"f{i}.py"])
            )
        waves = g.partition_waves()
        for wave in waves:
            self.assertLessEqual(len(wave), 2)


class TestCycleDetection(unittest.TestCase):
    def test_simple_cycle_raises(self) -> None:
        g = TaskGraph()
        g.add_task(TaskNode(task_id="a", description="a", depends_on=["b"]))
        g.add_task(TaskNode(task_id="b", description="b", depends_on=["a"]))
        with self.assertRaises(ValueError) as ctx:
            g.partition_waves()
        self.assertIn("Cycle", str(ctx.exception))

    def test_three_way_cycle(self) -> None:
        g = TaskGraph()
        g.add_task(TaskNode(task_id="a", description="a", depends_on=["c"]))
        g.add_task(TaskNode(task_id="b", description="b", depends_on=["a"]))
        g.add_task(TaskNode(task_id="c", description="c", depends_on=["b"]))
        with self.assertRaises(ValueError):
            g.partition_waves()


class TestValidate(unittest.TestCase):
    def test_valid_graph(self) -> None:
        g = TaskGraph()
        g.add_task(TaskNode(task_id="a", description="a"))
        g.add_task(TaskNode(task_id="b", description="b", depends_on=["a"]))
        result = g.validate()
        self.assertTrue(result["valid"])
        self.assertEqual(result["waves"], 2)
        self.assertIsNone(result["error"])

    def test_invalid_cycle(self) -> None:
        g = TaskGraph()
        g.add_task(TaskNode(task_id="a", description="a", depends_on=["b"]))
        g.add_task(TaskNode(task_id="b", description="b", depends_on=["a"]))
        result = g.validate()
        self.assertFalse(result["valid"])
        self.assertIsNotNone(result["error"])

    def test_unknown_dependency_warning(self) -> None:
        g = TaskGraph()
        g.add_task(TaskNode(task_id="a", description="a", depends_on=["nonexistent"]))
        result = g.validate()
        self.assertTrue(result["valid"])  # still valid, just warned
        self.assertTrue(any("nonexistent" in w for w in result["warnings"]))

    def test_bottleneck_warning(self) -> None:
        g = TaskGraph()
        g.add_task(TaskNode(task_id="hub", description="hub"))
        for i in range(7):
            g.add_task(TaskNode(task_id=f"dep{i}", description=f"dep{i}", depends_on=["hub"]))
        result = g.validate()
        self.assertTrue(result["valid"])
        self.assertTrue(any("bottleneck" in w for w in result["warnings"]))


class TestDuplicateTaskId(unittest.TestCase):
    def test_duplicate_task_id_raises(self) -> None:
        g = TaskGraph()
        g.add_task(TaskNode(task_id="a", description="first"))
        with self.assertRaises(ValueError) as ctx:
            g.add_task(TaskNode(task_id="a", description="second"))
        self.assertIn("Duplicate", str(ctx.exception))


class TestEmptyTargetFiles(unittest.TestCase):
    def test_no_files_no_overlap(self) -> None:
        """Tasks with no target_files don't create overlap edges."""
        g = TaskGraph()
        g.add_task(TaskNode(task_id="a", description="a"))
        g.add_task(TaskNode(task_id="b", description="b"))
        waves = g.partition_waves()
        self.assertEqual(len(waves), 1)


if __name__ == "__main__":
    unittest.main()
