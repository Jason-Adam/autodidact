"""Exit tracker parameter sweep harness.

Replays synthetic iteration sequences against ExitTracker with varied
thresholds, computing premature/late/correct exit rates and composite
fitness to find optimal parameters.
"""

from __future__ import annotations

import argparse
import itertools
import tempfile
from dataclasses import dataclass
from pathlib import Path

from src.exit_tracker import ExitTracker

# ---------------------------------------------------------------------------
# Fake type matching the ResponseAnalysis duck-type interface
# ---------------------------------------------------------------------------


@dataclass
class FakeAnalysis:
    exit_signal: bool = False
    raw_status: str = "unknown"
    work_type: str = "unknown"
    has_permission_denials: bool = False


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    name: str
    category: str  # "correct", "premature", "late", "edge"
    steps: list[FakeAnalysis]
    expected_exit_iteration: int | None  # 1-indexed; None = should NOT exit
    # For premature scenarios: exit before this iteration is premature
    earliest_valid_exit: int | None = None


def build_scenarios() -> list[Scenario]:
    """Build the 15-scenario corpus from the experiment plan."""
    scenarios: list[Scenario] = []

    # === Correct-exit scenarios ===

    # C1: Clean completion — 5 productive, then 2 exit_signal+COMPLETE
    steps_c1 = [FakeAnalysis() for _ in range(5)]
    steps_c1.append(FakeAnalysis(exit_signal=True, raw_status="COMPLETE"))
    steps_c1.append(FakeAnalysis(exit_signal=True, raw_status="COMPLETE"))
    scenarios.append(
        Scenario(
            name="C1_clean_completion",
            category="correct",
            steps=steps_c1,
            expected_exit_iteration=7,  # 2nd COMPLETE signal
        )
    )

    # C2: Gradual wind-down — 8 productive, then 3 exit_signal (no COMPLETE)
    steps_c2 = [FakeAnalysis() for _ in range(8)]
    steps_c2.extend([FakeAnalysis(exit_signal=True) for _ in range(3)])
    scenarios.append(
        Scenario(
            name="C2_gradual_winddown",
            category="correct",
            steps=steps_c2,
            expected_exit_iteration=11,  # dual-condition should fire
        )
    )

    # C3: Plan-driven exit — 6 iterations, plan completes on last
    # (plan_complete is handled externally; we test heuristics don't fire early)
    steps_c3 = [FakeAnalysis() for _ in range(6)]
    scenarios.append(
        Scenario(
            name="C3_plan_driven",
            category="correct",
            steps=steps_c3,
            expected_exit_iteration=None,  # no heuristic should fire
        )
    )

    # C4: Test-then-done — 4 productive, 2 test-only, then exit+COMPLETE
    steps_c4 = [FakeAnalysis() for _ in range(4)]
    steps_c4.extend([FakeAnalysis(work_type="testing") for _ in range(2)])
    steps_c4.append(FakeAnalysis(exit_signal=True, raw_status="COMPLETE"))
    scenarios.append(
        Scenario(
            name="C4_test_then_done",
            category="correct",
            steps=steps_c4,
            expected_exit_iteration=7,  # COMPLETE, not test saturation
        )
    )

    # === Premature-exit scenarios ===

    # P1: Early spurious COMPLETE — iter 2 COMPLETE, then 6 productive, then genuine
    steps_p1 = [FakeAnalysis()]
    steps_p1.append(FakeAnalysis(raw_status="COMPLETE"))  # spurious at iter 2
    steps_p1.extend([FakeAnalysis() for _ in range(6)])
    steps_p1.append(FakeAnalysis(raw_status="COMPLETE"))  # genuine at iter 9
    scenarios.append(
        Scenario(
            name="P1_early_spurious_complete",
            category="premature",
            steps=steps_p1,
            expected_exit_iteration=9,  # genuine COMPLETE
            earliest_valid_exit=9,
        )
    )

    # P2: Test-heavy workflow — 5 productive interleaved with 4 test-only
    steps_p2 = []
    for i in range(9):
        if i % 2 == 0:
            steps_p2.append(FakeAnalysis())  # productive
        else:
            steps_p2.append(FakeAnalysis(work_type="testing"))
    scenarios.append(
        Scenario(
            name="P2_test_heavy_workflow",
            category="premature",
            steps=steps_p2,
            expected_exit_iteration=None,  # should NOT exit
            earliest_valid_exit=10,  # any exit within scenario is premature
        )
    )

    # P3: Alternating exit signals — exit_signal on iters 2,5,7,9
    steps_p3 = []
    signal_iters = {2, 5, 7, 9}
    for i in range(1, 11):
        steps_p3.append(FakeAnalysis(exit_signal=(i in signal_iters)))
    scenarios.append(
        Scenario(
            name="P3_alternating_exit_signals",
            category="premature",
            steps=steps_p3,
            expected_exit_iteration=None,  # should not exit until work is done
            earliest_valid_exit=9,
        )
    )

    # P4: Long research phase — 8 no signals, then 4 productive, then complete
    steps_p4 = [FakeAnalysis() for _ in range(12)]
    steps_p4.append(FakeAnalysis(exit_signal=True, raw_status="COMPLETE"))
    scenarios.append(
        Scenario(
            name="P4_long_research",
            category="premature",
            steps=steps_p4,
            expected_exit_iteration=13,
            earliest_valid_exit=13,
        )
    )

    # P5: Early COMPLETE then course correction
    steps_p5 = [FakeAnalysis() for _ in range(2)]
    steps_p5.append(FakeAnalysis(raw_status="COMPLETE"))  # iter 3 early
    steps_p5.extend([FakeAnalysis() for _ in range(4)])  # iters 4-7 more work
    steps_p5.append(FakeAnalysis(raw_status="COMPLETE"))  # iter 8 genuine
    scenarios.append(
        Scenario(
            name="P5_early_complete_course_correction",
            category="premature",
            steps=steps_p5,
            expected_exit_iteration=8,
            earliest_valid_exit=8,
        )
    )

    # === Late-exit scenarios ===

    # L1: Obvious completion ignored — 3 consecutive exit+COMPLETE
    steps_l1 = [FakeAnalysis() for _ in range(3)]
    steps_l1.extend([FakeAnalysis(exit_signal=True, raw_status="COMPLETE") for _ in range(5)])
    scenarios.append(
        Scenario(
            name="L1_obvious_completion_ignored",
            category="late",
            steps=steps_l1,
            expected_exit_iteration=5,  # should exit by 2nd signal
        )
    )

    # L2: Test saturation delay — done at iter 6, then 3 test-only
    steps_l2 = [FakeAnalysis() for _ in range(6)]
    steps_l2.extend([FakeAnalysis(work_type="testing") for _ in range(5)])
    scenarios.append(
        Scenario(
            name="L2_test_saturation_delay",
            category="late",
            steps=steps_l2,
            expected_exit_iteration=9,  # ideal: exit at 3rd test-only
        )
    )

    # L3: Done signals spread thin — COMPLETE at iter 3 and iter 12
    steps_l3 = [FakeAnalysis() for _ in range(2)]
    steps_l3.append(FakeAnalysis(raw_status="COMPLETE"))  # iter 3
    steps_l3.extend([FakeAnalysis() for _ in range(8)])
    steps_l3.append(FakeAnalysis(raw_status="COMPLETE"))  # iter 12
    scenarios.append(
        Scenario(
            name="L3_done_signals_spread_thin",
            category="late",
            steps=steps_l3,
            expected_exit_iteration=12,
        )
    )

    # === Edge cases ===

    # E1: Permission denial — immediate exit
    steps_e1 = [FakeAnalysis(has_permission_denials=True)]
    scenarios.append(
        Scenario(
            name="E1_permission_denial",
            category="edge",
            steps=steps_e1,
            expected_exit_iteration=1,
        )
    )

    # E2: Fitness gate — exits via caller-supplied fitness
    steps_e2 = [FakeAnalysis() for _ in range(3)]
    scenarios.append(
        Scenario(
            name="E2_fitness_gate",
            category="edge",
            steps=steps_e2,
            expected_exit_iteration=3,  # fitness fires on last iteration
        )
    )

    # E3: Empty plan file — no false plan_complete
    steps_e3 = [FakeAnalysis() for _ in range(5)]
    scenarios.append(
        Scenario(
            name="E3_empty_plan",
            category="edge",
            steps=steps_e3,
            expected_exit_iteration=None,
        )
    )

    return scenarios


# ---------------------------------------------------------------------------
# Sweep engine
# ---------------------------------------------------------------------------


@dataclass
class SweepResult:
    max_completion_indicators: int
    max_test_only_loops: int
    max_done_signals: int
    dual_condition_floor: int
    done_signals_window: int | None
    test_only_window: int | None
    premature_exit_rate: float
    late_exit_rate: float
    correct_exit_rate: float
    mean_extra_iterations: float
    composite_score: float


def run_scenario(
    scenario: Scenario,
    *,
    fitness_on_last: bool = False,
) -> tuple[int | None, str]:
    """Replay a scenario. Returns (exit_iteration_1indexed, reason).

    exit_iteration is None if no exit fired.
    """
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "exit_signals.json"
        tracker = ExitTracker(state_path=state_path)

        for i, analysis in enumerate(scenario.steps):
            iteration = i + 1
            tracker.update(iteration, analysis)

            # For E2, supply fitness on the last step
            fitness = None
            if fitness_on_last and iteration == len(scenario.steps):
                fitness = (True, [])

            decision = tracker.evaluate(analysis=analysis, fitness_results=fitness)
            if decision.should_exit:
                return iteration, decision.reason

    return None, ""


# Pre-tuning baseline values
_BASELINE = {
    "max_completion_indicators": 5,
    "max_test_only_loops": 3,
    "max_done_signals": 2,
    "dual_condition_floor": 2,
}


def patch_tracker(
    max_completion_indicators: int,
    max_test_only_loops: int,
    max_done_signals: int,
    dual_condition_floor: int,
    done_signals_window: int | None = None,
    test_only_window: int | None = None,
) -> dict:
    """Monkey-patch ExitTracker class constants. Returns old values."""
    old = {
        "MAX_COMPLETION_INDICATORS": ExitTracker.MAX_COMPLETION_INDICATORS,
        "MAX_TEST_ONLY_LOOPS": ExitTracker.MAX_TEST_ONLY_LOOPS,
        "MAX_DONE_SIGNALS": ExitTracker.MAX_DONE_SIGNALS,
        "DUAL_CONDITION_FLOOR": ExitTracker.DUAL_CONDITION_FLOOR,
    }
    ExitTracker.MAX_COMPLETION_INDICATORS = max_completion_indicators
    ExitTracker.MAX_TEST_ONLY_LOOPS = max_test_only_loops
    ExitTracker.MAX_DONE_SIGNALS = max_done_signals
    ExitTracker.DUAL_CONDITION_FLOOR = dual_condition_floor

    # Store windowing params as class attrs for update() to use
    ExitTracker._DONE_SIGNALS_WINDOW = done_signals_window  # type: ignore[attr-defined]
    ExitTracker._TEST_ONLY_WINDOW = test_only_window  # type: ignore[attr-defined]

    # Monkey-patch update() to support windowing if needed
    if done_signals_window is not None or test_only_window is not None:
        _patch_update_with_windowing(done_signals_window, test_only_window)

    return old


def _patch_update_with_windowing(done_window: int | None, test_window: int | None) -> None:
    """Patch ExitTracker.update to trim done_signals and test_only_loops."""
    original_update = (
        ExitTracker._original_update
        if hasattr(ExitTracker, "_original_update")
        else ExitTracker.update
    )  # type: ignore[attr-defined]
    ExitTracker._original_update = original_update  # type: ignore[attr-defined]

    def windowed_update(self: ExitTracker, iteration: int, analysis: object) -> None:
        original_update(self, iteration, analysis)  # type: ignore[arg-type]
        # Trim after original update (which already called _save)
        needs_resave = False
        if done_window is not None:
            trimmed = self._signals.done_signals[-done_window:]
            if len(trimmed) != len(self._signals.done_signals):
                self._signals.done_signals = trimmed
                needs_resave = True
        if test_window is not None:
            trimmed = self._signals.test_only_loops[-test_window:]
            if len(trimmed) != len(self._signals.test_only_loops):
                self._signals.test_only_loops = trimmed
                needs_resave = True
        if needs_resave:
            self._save()

    ExitTracker.update = windowed_update  # type: ignore[assignment]


def restore_defaults(old: dict) -> None:
    """Restore ExitTracker class constants."""
    for name, value in old.items():
        setattr(ExitTracker, name, value)
    # Restore original update if patched
    if hasattr(ExitTracker, "_original_update"):
        ExitTracker.update = ExitTracker._original_update  # type: ignore[attr-defined]
        del ExitTracker._original_update  # type: ignore[attr-defined]
    # Clean up windowing attrs
    for attr in ("_DONE_SIGNALS_WINDOW", "_TEST_ONLY_WINDOW"):
        if hasattr(ExitTracker, attr):
            delattr(ExitTracker, attr)


def classify_result(
    scenario: Scenario,
    actual_exit: int | None,
) -> str:
    """Classify as 'correct', 'premature', or 'late'."""
    expected = scenario.expected_exit_iteration
    earliest = scenario.earliest_valid_exit

    if scenario.category == "edge":
        # Edge cases: just check if exit matches expected
        if expected is None:
            return "correct" if actual_exit is None else "premature"
        return (
            "correct"
            if actual_exit == expected
            else ("premature" if actual_exit is not None and actual_exit < expected else "late")
        )

    if scenario.category == "premature":
        # For premature scenarios, exit should not fire before earliest_valid_exit
        if actual_exit is None:
            return "correct" if expected is None else "late"
        if earliest is not None and actual_exit < earliest:
            return "premature"
        if expected is not None and actual_exit == expected:
            return "correct"
        if expected is not None and actual_exit > expected:
            return "late"
        # Exit at/after earliest_valid_exit with expected=None: scenario considers
        # this acceptable (e.g. P3 exits at iter 9 when earliest=9)
        return "correct"

    if scenario.category == "correct":
        if expected is None:
            return "correct" if actual_exit is None else "premature"
        if actual_exit is None:
            return "late"
        if actual_exit == expected:
            return "correct"
        if actual_exit < expected:
            return "premature"
        return "late"

    if scenario.category == "late":
        if expected is None:
            return "correct" if actual_exit is None else "premature"
        if actual_exit is None:
            return "late"
        if actual_exit <= expected:
            return "correct"
        return "late"

    return "correct"


def compute_extra_iterations(scenario: Scenario, actual_exit: int | None) -> float:
    """How many extra iterations beyond expected exit."""
    if scenario.expected_exit_iteration is None:
        return 0.0
    if actual_exit is None:
        return float(len(scenario.steps) - scenario.expected_exit_iteration)
    return max(0.0, float(actual_exit - scenario.expected_exit_iteration))


def evaluate_params(
    scenarios: list[Scenario],
    max_completion_indicators: int,
    max_test_only_loops: int,
    max_done_signals: int,
    dual_condition_floor: int,
    done_signals_window: int | None = None,
    test_only_window: int | None = None,
) -> SweepResult:
    """Evaluate a parameter combination against the scenario corpus."""
    old = patch_tracker(
        max_completion_indicators,
        max_test_only_loops,
        max_done_signals,
        dual_condition_floor,
        done_signals_window,
        test_only_window,
    )
    try:
        total = len(scenarios)
        premature_count = 0
        late_count = 0
        correct_count = 0
        extra_iters: list[float] = []

        for scenario in scenarios:
            fitness_on_last = scenario.name == "E2_fitness_gate"
            actual_exit, _reason = run_scenario(scenario, fitness_on_last=fitness_on_last)
            classification = classify_result(scenario, actual_exit)

            if classification == "premature":
                premature_count += 1
            elif classification == "late":
                late_count += 1
            else:
                correct_count += 1

            extra_iters.append(compute_extra_iterations(scenario, actual_exit))

        per = premature_count / total if total else 0.0
        ler = late_count / total if total else 0.0
        cer = correct_count / total if total else 0.0

        mean_extra = sum(extra_iters) / len(extra_iters) if extra_iters else 0.0
        max_scenario_len = max(len(s.steps) for s in scenarios) if scenarios else 1
        normalized_ler = min(mean_extra / max_scenario_len, 1.0)

        composite = cer * 0.5 + (1.0 - per) * 0.35 + (1.0 - normalized_ler) * 0.15

        return SweepResult(
            max_completion_indicators=max_completion_indicators,
            max_test_only_loops=max_test_only_loops,
            max_done_signals=max_done_signals,
            dual_condition_floor=dual_condition_floor,
            done_signals_window=done_signals_window,
            test_only_window=test_only_window,
            premature_exit_rate=per,
            late_exit_rate=ler,
            correct_exit_rate=cer,
            mean_extra_iterations=mean_extra,
            composite_score=composite,
        )
    finally:
        restore_defaults(old)


def run_sweep(
    scenarios: list[Scenario],
    *,
    include_windowing: bool = False,
) -> list[SweepResult]:
    """Grid search over the parameter space."""
    results: list[SweepResult] = []

    mci_range = range(2, 8)  # MAX_COMPLETION_INDICATORS: 2-7
    mtl_range = range(2, 7)  # MAX_TEST_ONLY_LOOPS: 2-6
    mds_range = range(1, 5)  # MAX_DONE_SIGNALS: 1-4
    # DUAL_CONDITION_FLOOR is derived: max(1, mci - 3)

    if include_windowing:
        dsw_options: list[int | None] = [None, 3, 4, 5, 6, 7, 8]
        tow_options: list[int | None] = [None, 4, 5, 6, 7, 8]
    else:
        dsw_options = [None]
        tow_options = [None]

    for mci, mtl, mds, dsw, tow in itertools.product(
        mci_range,
        mtl_range,
        mds_range,
        dsw_options,
        tow_options,
    ):
        dcf = max(1, mci - 3)
        result = evaluate_params(
            scenarios,
            mci,
            mtl,
            mds,
            dcf,
            dsw,
            tow,
        )
        results.append(result)

    return results


def print_top_results(results: list[SweepResult], n: int = 10) -> None:
    """Print top N results by composite score."""
    ranked = sorted(results, key=lambda r: r.composite_score, reverse=True)

    header = (
        f"{'Rank':<5} {'MCI':<5} {'MTL':<5} {'MDS':<5} {'DCF':<5} "
        f"{'DSW':<5} {'TOW':<5} "
        f"{'PER':<8} {'LER':<8} {'CER':<8} {'Score':<8}"
    )
    print(header)
    print("-" * len(header))

    for i, r in enumerate(ranked[:n], 1):
        dsw = str(r.done_signals_window) if r.done_signals_window else "-"
        tow = str(r.test_only_window) if r.test_only_window else "-"
        print(
            f"{i:<5} {r.max_completion_indicators:<5} {r.max_test_only_loops:<5} "
            f"{r.max_done_signals:<5} {r.dual_condition_floor:<5} "
            f"{dsw:<5} {tow:<5} "
            f"{r.premature_exit_rate:<8.4f} {r.late_exit_rate:<8.4f} "
            f"{r.correct_exit_rate:<8.4f} {r.composite_score:<8.4f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Exit tracker parameter sweep")
    parser.add_argument(
        "--metric",
        choices=["premature_exit_rate", "late_exit_rate", "correct_exit_rate", "composite"],
        help="Output a single metric value for fitness evaluation",
    )
    parser.add_argument("--top", type=int, default=10, help="Number of top results to show")
    parser.add_argument("--full", action="store_true", help="Run full sweep and show results table")
    parser.add_argument("--windowing", action="store_true", help="Include windowing parameters")
    args = parser.parse_args()

    scenarios = build_scenarios()

    if args.metric:
        # Evaluate current constants
        result = evaluate_params(
            scenarios,
            ExitTracker.MAX_COMPLETION_INDICATORS,
            ExitTracker.MAX_TEST_ONLY_LOOPS,
            ExitTracker.MAX_DONE_SIGNALS,
            ExitTracker.DUAL_CONDITION_FLOOR,
        )
        attr_map = {"composite": "composite_score"}
        metric_val = getattr(result, attr_map.get(args.metric, args.metric))
        print(f"{metric_val:.4f}")
        return

    if args.full:
        print("Running full parameter sweep...")
        results = run_sweep(scenarios, include_windowing=args.windowing)
        print(f"\nTotal combinations evaluated: {len(results)}")
        print(f"\nTop {args.top} parameter combinations:\n")
        print_top_results(results, args.top)

        # Baseline comparison
        baseline = evaluate_params(scenarios, **_BASELINE)
        print(
            f"\nBaseline: PER={baseline.premature_exit_rate:.4f}, "
            f"LER={baseline.late_exit_rate:.4f}, "
            f"CER={baseline.correct_exit_rate:.4f}, "
            f"Score={baseline.composite_score:.4f}"
        )
        return

    # Default: run sweep and recommend
    print("Running parameter sweep...")
    results = run_sweep(scenarios, include_windowing=args.windowing)
    best = max(results, key=lambda r: r.composite_score)
    baseline = evaluate_params(scenarios, **_BASELINE)

    print(
        f"\nBaseline: PER={baseline.premature_exit_rate:.4f}, "
        f"LER={baseline.late_exit_rate:.4f}, "
        f"CER={baseline.correct_exit_rate:.4f}, "
        f"Score={baseline.composite_score:.4f}"
    )
    print(
        f"\nBest:     PER={best.premature_exit_rate:.4f}, "
        f"LER={best.late_exit_rate:.4f}, "
        f"CER={best.correct_exit_rate:.4f}, "
        f"Score={best.composite_score:.4f}"
    )
    print("\nRecommended parameters:")
    print(f"  MAX_COMPLETION_INDICATORS = {best.max_completion_indicators}")
    print(f"  MAX_TEST_ONLY_LOOPS = {best.max_test_only_loops}")
    print(f"  MAX_DONE_SIGNALS = {best.max_done_signals}")
    print(f"  DUAL_CONDITION_FLOOR = {best.dual_condition_floor}")
    if best.done_signals_window:
        print(f"  DONE_SIGNALS_WINDOW = {best.done_signals_window}")
    if best.test_only_window:
        print(f"  TEST_ONLY_WINDOW = {best.test_only_window}")

    improvement = best.composite_score - baseline.composite_score
    print(f"\n  Composite improvement: {improvement:+.4f} ({improvement * 100:+.1f}pp)")

    if best.premature_exit_rate <= 0.05 and improvement >= 0.05:
        print("\n  ✓ Meets fitness criteria (PER<=5%, +5pp composite)")
    else:
        issues = []
        if best.premature_exit_rate > 0.05:
            issues.append(f"PER {best.premature_exit_rate:.4f} > 0.05")
        if improvement < 0.05:
            issues.append(f"improvement {improvement:+.4f} < 0.05")
        print(f"\n  ✗ Does not meet fitness: {', '.join(issues)}")

    print(f"\nTop {args.top}:\n")
    print_top_results(results, args.top)


if __name__ == "__main__":
    main()
