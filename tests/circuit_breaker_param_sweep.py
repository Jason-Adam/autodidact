"""Circuit breaker parameter sweep harness.

Replays synthetic iteration sequences against CircuitBreaker with varied
thresholds, computing false-trip rate and true-trip latency to find
optimal parameters.
"""

from __future__ import annotations

import argparse
import itertools
from dataclasses import dataclass

import src.circuit_breaker as cb_module
from src.circuit_breaker import BreakerPhase, CircuitBreaker

# ---------------------------------------------------------------------------
# Fake types matching the duck-typed interface record_iteration expects
# ---------------------------------------------------------------------------


@dataclass
class FakeProgress:
    is_productive: bool = False


@dataclass
class FakeAnalysis:
    asking_questions: bool = False
    has_permission_denials: bool = False
    work_summary: str = ""
    files_modified: int = 0


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    name: str
    category: str  # "legitimate" or "stall"
    steps: list[tuple[FakeProgress, FakeAnalysis]]


def build_scenarios() -> list[Scenario]:
    """Build the synthetic scenario corpus from the experiment plan."""
    scenarios: list[Scenario] = []

    # --- Legitimate scenarios ---

    # L1: 3 question iterations then 1 productive
    scenarios.append(
        Scenario(
            name="questions_then_productive",
            category="legitimate",
            steps=[
                (FakeProgress(), FakeAnalysis(asking_questions=True, work_summary=f"q{i}"))
                for i in range(3)
            ]
            + [
                (
                    FakeProgress(is_productive=True),
                    FakeAnalysis(work_summary="done", files_modified=2),
                ),
            ],
        )
    )

    # L2: 4 iterations with varying work_summary (slow research)
    scenarios.append(
        Scenario(
            name="slow_research_varied_summaries",
            category="legitimate",
            steps=[
                (
                    FakeProgress(),
                    FakeAnalysis(work_summary=f"researching topic {i}", files_modified=0),
                )
                for i in range(4)
            ],
        )
    )

    # L3: 10 consecutive question iterations (prolonged clarification)
    scenarios.append(
        Scenario(
            name="prolonged_questions",
            category="legitimate",
            steps=[
                (FakeProgress(), FakeAnalysis(asking_questions=True, work_summary=f"clarify {i}"))
                for i in range(10)
            ],
        )
    )

    # L4: 3 iterations no files but is_productive=True (planning with productive git)
    scenarios.append(
        Scenario(
            name="productive_no_files",
            category="legitimate",
            steps=[
                (
                    FakeProgress(is_productive=True),
                    FakeAnalysis(work_summary=f"planning {i}", files_modified=0),
                )
                for i in range(3)
            ],
        )
    )

    # L5: Alternating productive and non-productive (normal working rhythm)
    scenarios.append(
        Scenario(
            name="alternating_productive",
            category="legitimate",
            steps=[
                (
                    FakeProgress(is_productive=(i % 2 == 0)),
                    FakeAnalysis(
                        work_summary=f"step {i}",
                        files_modified=(1 if i % 2 == 0 else 0),
                    ),
                )
                for i in range(6)
            ],
        )
    )

    # L6: 2 no-progress then productive recovery
    scenarios.append(
        Scenario(
            name="brief_stall_then_recovery",
            category="legitimate",
            steps=[(FakeProgress(), FakeAnalysis(work_summary=f"stuck {i}")) for i in range(2)]
            + [
                (
                    FakeProgress(is_productive=True),
                    FakeAnalysis(work_summary="recovered", files_modified=3),
                ),
            ],
        )
    )

    # L7: Research with occasional file writes (3 dry, 1 write, repeat)
    scenarios.append(
        Scenario(
            name="research_with_occasional_writes",
            category="legitimate",
            steps=[
                (FakeProgress(), FakeAnalysis(work_summary=f"research {i}", files_modified=0))
                for i in range(3)
            ]
            + [
                (
                    FakeProgress(is_productive=True),
                    FakeAnalysis(work_summary="write results", files_modified=2),
                ),
            ]
            + [
                (FakeProgress(), FakeAnalysis(work_summary=f"more research {i}", files_modified=0))
                for i in range(2)
            ],
        )
    )

    # L8: Single permission denial then recovery
    scenarios.append(
        Scenario(
            name="single_permission_denial",
            category="legitimate",
            steps=[
                (
                    FakeProgress(),
                    FakeAnalysis(has_permission_denials=True, work_summary="denied once"),
                ),
                (
                    FakeProgress(is_productive=True),
                    FakeAnalysis(work_summary="recovered", files_modified=1),
                ),
            ],
        )
    )

    # --- Stall scenarios ---

    # S1: Same error repeated (true stuck loop)
    scenarios.append(
        Scenario(
            name="same_error_loop",
            category="stall",
            steps=[
                (FakeProgress(), FakeAnalysis(work_summary="ImportError: no module named foo"))
                for _ in range(8)
            ],
        )
    )

    # S2: Permission denials (deterministic block)
    scenarios.append(
        Scenario(
            name="permission_denial_block",
            category="stall",
            steps=[
                (
                    FakeProgress(),
                    FakeAnalysis(has_permission_denials=True, work_summary=f"denied {i}"),
                )
                for i in range(4)
            ],
        )
    )

    # S3: No files modified, not productive, varying summaries
    scenarios.append(
        Scenario(
            name="no_files_stall",
            category="stall",
            steps=[
                (
                    FakeProgress(),
                    FakeAnalysis(work_summary=f"trying approach {i}", files_modified=0),
                )
                for i in range(8)
            ],
        )
    )

    # S4: Pure no-progress (empty summaries)
    scenarios.append(
        Scenario(
            name="pure_no_progress",
            category="stall",
            steps=[(FakeProgress(), FakeAnalysis(work_summary="")) for _ in range(8)],
        )
    )

    # S5: Alternating between two error messages (near-identical errors)
    scenarios.append(
        Scenario(
            name="alternating_errors",
            category="stall",
            steps=[
                (
                    FakeProgress(),
                    FakeAnalysis(
                        work_summary="error variant A" if i % 2 == 0 else "error variant B"
                    ),
                )
                for i in range(10)
            ],
        )
    )

    # S6: No progress with occasional questions (questions don't help)
    scenarios.append(
        Scenario(
            name="questions_no_resolution",
            category="stall",
            steps=[
                (FakeProgress(), FakeAnalysis(work_summary=f"stuck {i}"))
                if i % 3 != 0
                else (
                    FakeProgress(),
                    FakeAnalysis(asking_questions=True, work_summary=f"question {i}"),
                )
                for i in range(12)
            ],
        )
    )

    # S7: Same error with one variant interspersed
    scenarios.append(
        Scenario(
            name="mostly_same_error",
            category="stall",
            steps=[
                (
                    FakeProgress(),
                    FakeAnalysis(work_summary="the same error" if i != 3 else "slightly different"),
                )
                for i in range(8)
            ],
        )
    )

    # S8: Permission denials combined with repeated errors (common real pattern)
    scenarios.append(
        Scenario(
            name="permission_denial_error_loop",
            category="stall",
            steps=[
                (
                    FakeProgress(),
                    FakeAnalysis(
                        has_permission_denials=True,
                        work_summary="permission denied: cannot write to /etc/config",
                    ),
                )
                for _ in range(4)
            ],
        )
    )

    return scenarios


# ---------------------------------------------------------------------------
# Sweep engine
# ---------------------------------------------------------------------------


@dataclass
class SweepResult:
    no_progress: int
    same_error: int
    permission_denial: int
    half_open: int
    no_files_modified: int
    false_trip_rate: float
    mean_true_trip_latency: float
    composite_score: float


def run_scenario(scenario: Scenario) -> tuple[bool, int | None]:
    """Replay a scenario. Returns (tripped, iteration_of_trip).

    iteration_of_trip is 0-indexed from the start of the stall pattern.
    For legitimate scenarios that trip, it's the iteration index.
    """
    breaker = CircuitBreaker()

    for i, (progress, analysis) in enumerate(scenario.steps):
        breaker.record_iteration(progress, analysis)
        if breaker.current_phase == BreakerPhase.OPEN:
            return True, i + 1  # 1-indexed iteration count

    return False, None


def patch_constants(
    no_progress: int,
    same_error: int,
    permission_denial: int,
    half_open: int,
    no_files_modified: int,
) -> None:
    """Monkey-patch circuit breaker module constants."""
    cb_module.NO_PROGRESS_THRESHOLD = no_progress
    cb_module.SAME_ERROR_THRESHOLD = same_error
    cb_module.PERMISSION_DENIAL_THRESHOLD = permission_denial
    cb_module.HALF_OPEN_THRESHOLD = half_open
    cb_module.NO_FILES_MODIFIED_THRESHOLD = no_files_modified


def restore_defaults() -> None:
    """Restore module constants to their canonical values."""
    cb_module.NO_PROGRESS_THRESHOLD = 5
    cb_module.SAME_ERROR_THRESHOLD = 2
    cb_module.PERMISSION_DENIAL_THRESHOLD = 2
    cb_module.HALF_OPEN_THRESHOLD = 1
    cb_module.NO_FILES_MODIFIED_THRESHOLD = 5


def evaluate_params(
    scenarios: list[Scenario],
    no_progress: int,
    same_error: int,
    permission_denial: int,
    half_open: int,
    no_files_modified: int,
) -> SweepResult:
    """Evaluate a parameter combination against the scenario corpus."""
    patch_constants(no_progress, same_error, permission_denial, half_open, no_files_modified)

    legitimate = [s for s in scenarios if s.category == "legitimate"]
    stalls = [s for s in scenarios if s.category == "stall"]

    # False-trip rate: legitimate scenarios that tripped
    legit_tripped = sum(1 for s in legitimate if run_scenario(s)[0])
    false_trip_rate = legit_tripped / len(legitimate) if legitimate else 0.0

    # True-trip latency: mean iterations until OPEN for stall scenarios that tripped
    stall_latencies = []
    for s in stalls:
        tripped, iteration = run_scenario(s)
        if tripped and iteration is not None:
            stall_latencies.append(iteration)

    mean_latency = sum(stall_latencies) / len(stall_latencies) if stall_latencies else float("inf")

    # Composite score: (1 - false_trip_rate) * 0.6 + (1 - normalized_latency) * 0.4
    # Normalize latency to [0, 1] range; max reasonable is 10 iterations
    normalized_latency = min(mean_latency / 10.0, 1.0)
    composite = (1.0 - false_trip_rate) * 0.6 + (1.0 - normalized_latency) * 0.4

    return SweepResult(
        no_progress=no_progress,
        same_error=same_error,
        permission_denial=permission_denial,
        half_open=half_open,
        no_files_modified=no_files_modified,
        false_trip_rate=false_trip_rate,
        mean_true_trip_latency=mean_latency,
        composite_score=composite,
    )


def run_sweep(scenarios: list[Scenario]) -> list[SweepResult]:
    """Grid search over the parameter space."""
    results: list[SweepResult] = []

    no_progress_range = range(2, 7)  # 2-6
    same_error_range = range(2, 7)  # 2-6
    permission_denial_range = range(1, 4)  # 1-3
    no_files_modified_range = range(3, 8)  # 3-7

    for np_thresh, se_thresh, pd_thresh, nfm_thresh in itertools.product(
        no_progress_range,
        same_error_range,
        permission_denial_range,
        no_files_modified_range,
    ):
        # HALF_OPEN must be strictly less than NO_PROGRESS
        for ho_thresh in range(1, np_thresh):
            result = evaluate_params(
                scenarios,
                np_thresh,
                se_thresh,
                pd_thresh,
                ho_thresh,
                nfm_thresh,
            )
            results.append(result)

    restore_defaults()
    return results


def print_top_results(results: list[SweepResult], n: int = 10) -> None:
    """Print top N results by composite score."""
    ranked = sorted(results, key=lambda r: r.composite_score, reverse=True)

    print(
        f"{'Rank':<5} {'NP':<4} {'SE':<4} {'PD':<4} {'HO':<4} {'NFM':<5} "
        f"{'FTR':<8} {'Latency':<9} {'Score':<8}"
    )
    print("-" * 60)

    for i, r in enumerate(ranked[:n], 1):
        print(
            f"{i:<5} {r.no_progress:<4} {r.same_error:<4} {r.permission_denial:<4} "
            f"{r.half_open:<4} {r.no_files_modified:<5} "
            f"{r.false_trip_rate:<8.4f} {r.mean_true_trip_latency:<9.2f} "
            f"{r.composite_score:<8.4f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Circuit breaker parameter sweep")
    parser.add_argument(
        "--metric",
        choices=["false_trip_rate", "true_trip_latency", "composite"],
        help="Output a single metric value for fitness evaluation",
    )
    parser.add_argument("--top", type=int, default=10, help="Number of top results to show")
    parser.add_argument("--full", action="store_true", help="Run full sweep and show results table")
    args = parser.parse_args()

    scenarios = build_scenarios()

    if args.metric:
        # Evaluate current constants (as set in the module)
        result = evaluate_params(
            scenarios,
            cb_module.NO_PROGRESS_THRESHOLD,
            cb_module.SAME_ERROR_THRESHOLD,
            cb_module.PERMISSION_DENIAL_THRESHOLD,
            cb_module.HALF_OPEN_THRESHOLD,
            cb_module.NO_FILES_MODIFIED_THRESHOLD,
        )
        restore_defaults()

        if args.metric == "false_trip_rate":
            print(f"{result.false_trip_rate:.4f}")
        elif args.metric == "true_trip_latency":
            print(f"{result.mean_true_trip_latency:.4f}")
        elif args.metric == "composite":
            print(f"{result.composite_score:.4f}")
        return

    if args.full:
        print("Running full parameter sweep...")
        results = run_sweep(scenarios)
        print(f"\nTotal combinations evaluated: {len(results)}")
        print(f"\nTop {args.top} parameter combinations:\n")
        print_top_results(results, args.top)

        # Show baseline comparison
        baseline = evaluate_params(scenarios, 3, 5, 2, 2, 4)
        restore_defaults()
        print(
            f"\nBaseline (current defaults): FTR={baseline.false_trip_rate:.4f}, "
            f"Latency={baseline.mean_true_trip_latency:.2f}, "
            f"Score={baseline.composite_score:.4f}"
        )
        return

    # Default: show current metrics and recommend
    print("Running parameter sweep...")
    results = run_sweep(scenarios)
    best = max(results, key=lambda r: r.composite_score)
    baseline = evaluate_params(scenarios, 3, 5, 2, 2, 4)
    restore_defaults()

    print(
        f"\nBaseline: FTR={baseline.false_trip_rate:.4f}, "
        f"Latency={baseline.mean_true_trip_latency:.2f}, "
        f"Score={baseline.composite_score:.4f}"
    )
    print(
        f"\nBest:     FTR={best.false_trip_rate:.4f}, "
        f"Latency={best.mean_true_trip_latency:.2f}, "
        f"Score={best.composite_score:.4f}"
    )
    print("\nRecommended parameters:")
    print(f"  NO_PROGRESS_THRESHOLD = {best.no_progress}")
    print(f"  SAME_ERROR_THRESHOLD = {best.same_error}")
    print(f"  PERMISSION_DENIAL_THRESHOLD = {best.permission_denial}")
    print(f"  HALF_OPEN_THRESHOLD = {best.half_open}")
    print(f"  NO_FILES_MODIFIED_THRESHOLD = {best.no_files_modified}")

    improvement = best.composite_score - baseline.composite_score
    print(f"\n  Composite improvement: {improvement:+.4f} ({improvement * 100:+.1f}pp)")

    if best.false_trip_rate <= 0.10 and best.mean_true_trip_latency <= 4.0:
        print("\n  ✓ Meets fitness criteria")
    else:
        issues = []
        if best.false_trip_rate > 0.10:
            issues.append(f"FTR {best.false_trip_rate:.4f} > 0.10")
        if best.mean_true_trip_latency > 4.0:
            issues.append(f"Latency {best.mean_true_trip_latency:.2f} > 4.0")
        print(f"\n  ✗ Does not meet fitness: {', '.join(issues)}")

    print("\nTop 10:\n")
    print_top_results(results, 10)


if __name__ == "__main__":
    main()
