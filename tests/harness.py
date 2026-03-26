"""Synthetic experiment history harness for convergence detection tuning."""

from __future__ import annotations

import random
from dataclasses import dataclass

from src.convergence import (
    ConvergenceThresholds,
    ExperimentEntry,
    detect_signals,
)


def _entry(
    num: int,
    status: str,
    metric: float | None = None,
    files: list[str] | None = None,
) -> ExperimentEntry:
    return ExperimentEntry(
        experiment_num=num,
        status=status,
        metric_value=metric,
        files_touched=files or [],
        duration_seconds=1.0,
        description=f"synthetic #{num}",
        timestamp="2026-01-01T00:00:00Z",
    )


# ── History generators ────────────────────────────────────────────────


def make_plateau_history(
    length: int, convergence_idx: int, noise: float = 0.0, *, seed: int = 42
) -> list[ExperimentEntry]:
    """Metric improves steadily then flattens at convergence_idx."""
    rng = random.Random(seed)
    entries: list[ExperimentEntry] = []
    base = 0.5
    step = 0.05
    for i in range(length):
        if i < convergence_idx:
            base += step
        jitter = rng.uniform(-noise, noise) if noise else 0.0
        entries.append(_entry(i, "keep", metric=base + jitter))
    return entries


def make_discard_history(length: int, convergence_idx: int) -> list[ExperimentEntry]:
    """Keeps with improving metric, then all-discard at convergence_idx."""
    entries: list[ExperimentEntry] = []
    metric = 0.5
    for i in range(length):
        if i < convergence_idx:
            metric += 0.03
            entries.append(_entry(i, "keep", metric=metric))
        else:
            entries.append(_entry(i, "discard", metric=None))
    return entries


def make_oscillating_history(length: int, convergence_idx: int) -> list[ExperimentEntry]:
    """Improving keeps, then alternating keep/discard at convergence_idx."""
    entries: list[ExperimentEntry] = []
    metric = 0.5
    for i in range(length):
        if i < convergence_idx:
            metric += 0.04
            entries.append(_entry(i, "keep", metric=metric))
        else:
            if (i - convergence_idx) % 2 == 0:
                entries.append(_entry(i, "keep", metric=metric))
            else:
                entries.append(_entry(i, "discard", metric=None))
    return entries


def make_interesting_history(length: int, convergence_idx: int) -> list[ExperimentEntry]:
    """Normal keeps, then all-interesting at convergence_idx."""
    entries: list[ExperimentEntry] = []
    metric = 0.5
    for i in range(length):
        if i < convergence_idx:
            metric += 0.03
            entries.append(_entry(i, "keep", metric=metric))
        else:
            entries.append(_entry(i, "interesting", metric=None))
    return entries


def make_thought_history(length: int, convergence_idx: int) -> list[ExperimentEntry]:
    """Normal keeps, then all-thought at convergence_idx."""
    entries: list[ExperimentEntry] = []
    metric = 0.5
    for i in range(length):
        if i < convergence_idx:
            metric += 0.03
            entries.append(_entry(i, "keep", metric=metric))
        else:
            entries.append(_entry(i, "thought", metric=None))
    return entries


def make_timeout_history(length: int, convergence_idx: int) -> list[ExperimentEntry]:
    """Normal keeps, then all-timeout at convergence_idx."""
    entries: list[ExperimentEntry] = []
    metric = 0.5
    for i in range(length):
        if i < convergence_idx:
            metric += 0.03
            entries.append(_entry(i, "keep", metric=metric))
        else:
            entries.append(_entry(i, "timeout", metric=None))
    return entries


def make_code_repetition_history(length: int, convergence_idx: int) -> list[ExperimentEntry]:
    """Normal keeps with varied files, then touches same file repeatedly."""
    entries: list[ExperimentEntry] = []
    metric = 0.5
    for i in range(length):
        if i < convergence_idx:
            metric += 0.03
            entries.append(_entry(i, "keep", metric=metric, files=[f"src/file_{i}.py"]))
        else:
            entries.append(_entry(i, "discard", metric=None, files=["src/stuck.py"]))
    return entries


# ── Synthetic result ──────────────────────────────────────────────────


@dataclass
class SyntheticCase:
    """A synthetic history with its known convergence point."""

    name: str
    history: list[ExperimentEntry]
    convergence_idx: int
    expected_signal: str  # which signal type should fire


@dataclass
class SyntheticResult:
    """Aggregate metrics from running detectors against a suite of histories."""

    iterations_saved_ratio: float  # mean ISR across suite
    false_stop_rate: float  # fraction of histories where detection fired too early
    mean_lag: float  # mean lag (actual_stop - convergence) for non-false-stops
    signal_coverage: dict[str, bool]  # which signal types fired at least once


# ── Runner ────────────────────────────────────────────────────────────


def run_synthetic(
    thresholds: ConvergenceThresholds,
    history: list[ExperimentEntry],
    convergence_idx: int,
) -> tuple[int | None, float, bool, float]:
    """Run prefix scan and return (actual_stop, ISR, is_false_stop, lag).

    Returns actual_stop=None if no signal ever fires.
    """
    actual_stop: int | None = None
    for i in range(1, len(history) + 1):
        signals = detect_signals(history[:i], thresholds)
        if signals:
            actual_stop = i
            break

    if actual_stop is None:
        # No signal fired — ISR = 0, not a false stop, lag = full length
        return None, 0.0, False, float(len(history) - convergence_idx)

    is_false_stop = actual_stop < convergence_idx
    isr = (len(history) - actual_stop) / len(history)
    lag = actual_stop - convergence_idx if not is_false_stop else 0.0
    return actual_stop, isr, is_false_stop, lag


def _build_default_suite() -> list[SyntheticCase]:
    """Build the default grid of synthetic histories (30+ cases, all 5+ categories)."""
    cases: list[SyntheticCase] = []

    lengths = [20, 35, 50]
    fractions = [0.3, 0.5, 0.75]

    for length in lengths:
        for frac in fractions:
            cidx = int(length * frac)

            # Plateau — two noise levels
            for noise, suffix in [(0.0, "clean"), (0.003, "noisy")]:
                cases.append(
                    SyntheticCase(
                        name=f"plateau_{length}_{frac}_{suffix}",
                        history=make_plateau_history(length, cidx, noise=noise),
                        convergence_idx=cidx,
                        expected_signal="plateau",
                    )
                )

            # Discard streak
            cases.append(
                SyntheticCase(
                    name=f"discard_{length}_{frac}",
                    history=make_discard_history(length, cidx),
                    convergence_idx=cidx,
                    expected_signal="consecutive_discards",
                )
            )

            # Oscillating
            cases.append(
                SyntheticCase(
                    name=f"oscillating_{length}_{frac}",
                    history=make_oscillating_history(length, cidx),
                    convergence_idx=cidx,
                    expected_signal="alternating",
                )
            )

            # Interesting streak
            cases.append(
                SyntheticCase(
                    name=f"interesting_{length}_{frac}",
                    history=make_interesting_history(length, cidx),
                    convergence_idx=cidx,
                    expected_signal="consecutive_interesting",
                )
            )

            # Thought streak
            cases.append(
                SyntheticCase(
                    name=f"thought_{length}_{frac}",
                    history=make_thought_history(length, cidx),
                    convergence_idx=cidx,
                    expected_signal="consecutive_thoughts",
                )
            )

            # Timeout streak
            cases.append(
                SyntheticCase(
                    name=f"timeout_{length}_{frac}",
                    history=make_timeout_history(length, cidx),
                    convergence_idx=cidx,
                    expected_signal="timeout_streak",
                )
            )

            # Code repetition
            cases.append(
                SyntheticCase(
                    name=f"code_rep_{length}_{frac}",
                    history=make_code_repetition_history(length, cidx),
                    convergence_idx=cidx,
                    expected_signal="code_repetition",
                )
            )

    return cases


_DEFAULT_SUITE: list[SyntheticCase] | None = None


def get_default_suite() -> list[SyntheticCase]:
    """Return (and cache) the default synthetic suite."""
    global _DEFAULT_SUITE
    if _DEFAULT_SUITE is None:
        _DEFAULT_SUITE = _build_default_suite()
    return _DEFAULT_SUITE


def run_suite(
    thresholds: ConvergenceThresholds | None = None,
) -> SyntheticResult:
    """Run all synthetic histories against the given thresholds and aggregate metrics."""
    if thresholds is None:
        thresholds = ConvergenceThresholds()

    suite = get_default_suite()
    total = len(suite)
    isr_sum = 0.0
    false_stops = 0
    lag_sum = 0.0
    lag_count = 0
    signal_fired: dict[str, bool] = {}

    for case in suite:
        _, isr, is_false_stop, lag = run_synthetic(thresholds, case.history, case.convergence_idx)
        isr_sum += isr
        if is_false_stop:
            false_stops += 1
        else:
            lag_sum += lag
            lag_count += 1

        # Track which signal types fire correctly — check the expected signal
        # at any prefix, not just the first detection point (another signal
        # may fire earlier, masking coverage).
        if case.expected_signal not in signal_fired:
            for j in range(1, len(case.history) + 1):
                sigs = detect_signals(case.history[:j], thresholds)
                for s in sigs:
                    signal_fired[s.signal_type] = True
                if case.expected_signal in signal_fired:
                    break

    mean_isr = isr_sum / total if total else 0.0
    fsr = false_stops / total if total else 0.0
    mean_lag = lag_sum / lag_count if lag_count else 0.0

    # Check coverage for all 7 signal types
    all_signals = [
        "plateau",
        "consecutive_discards",
        "alternating",
        "code_repetition",
        "timeout_streak",
        "consecutive_interesting",
        "consecutive_thoughts",
    ]
    coverage = {s: signal_fired.get(s, False) for s in all_signals}

    return SyntheticResult(
        iterations_saved_ratio=mean_isr,
        false_stop_rate=fsr,
        mean_lag=mean_lag,
        signal_coverage=coverage,
    )


def grid_search(
    param_grid: dict[str, list[object]],
    base_thresholds: ConvergenceThresholds | None = None,
) -> list[tuple[dict[str, object], SyntheticResult]]:
    """Run a grid search over threshold parameters.

    Returns list of (params_dict, result) sorted by ISR descending,
    filtered to FSR < 0.05.
    """
    if base_thresholds is None:
        base_thresholds = ConvergenceThresholds()

    # Build all combinations
    keys = list(param_grid.keys())
    combos: list[dict[str, object]] = [{}]
    for key in keys:
        new_combos = []
        for combo in combos:
            for val in param_grid[key]:
                new_combo = dict(combo)
                new_combo[key] = val
                new_combos.append(new_combo)
        combos = new_combos

    results: list[tuple[dict[str, object], SyntheticResult]] = []
    for combo in combos:
        # Create thresholds with overrides
        params = {
            "plateau_threshold": base_thresholds.plateau_threshold,
            "plateau_window": base_thresholds.plateau_window,
            "max_consecutive_discards": base_thresholds.max_consecutive_discards,
            "alternating_window": base_thresholds.alternating_window,
            "alternating_ratio": base_thresholds.alternating_ratio,
            "code_repetition_window": base_thresholds.code_repetition_window,
            "code_repetition_threshold": base_thresholds.code_repetition_threshold,
            "max_consecutive_timeouts": base_thresholds.max_consecutive_timeouts,
            "max_consecutive_interesting": base_thresholds.max_consecutive_interesting,
            "max_consecutive_thoughts": base_thresholds.max_consecutive_thoughts,
        }
        params.update(combo)
        thresholds = ConvergenceThresholds(**params)  # type: ignore[arg-type]
        result = run_suite(thresholds)
        results.append((combo, result))

    # Sort by ISR descending, filter to FSR < 0.05
    valid = [(c, r) for c, r in results if r.false_stop_rate < 0.05]
    valid.sort(key=lambda x: x[1].iterations_saved_ratio, reverse=True)

    return valid if valid else results  # return all if none pass FSR filter
