"""Stateless convergence signal detection for experiment loops."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExperimentEntry:
    """A single experiment result in the loop history."""

    experiment_num: int
    status: str  # "keep" | "discard" | "crash" | "timeout" | "interesting" | "thought" | "baseline"
    metric_value: float | None
    files_touched: list[str]
    duration_seconds: float
    description: str
    timestamp: str


@dataclass
class ConvergenceThresholds:
    """Configurable thresholds for convergence signal detection."""

    plateau_threshold: float = 0.01  # < 1% improvement over window
    plateau_window: int = 3  # N consecutive keeps to evaluate
    max_consecutive_discards: int = 5
    alternating_window: int = 6  # last N entries for oscillation check
    alternating_ratio: float = 0.8  # oscillation detection threshold
    code_repetition_window: int = 10
    code_repetition_threshold: int = 3  # same file touched N+ times in window
    max_consecutive_timeouts: int = 2
    max_consecutive_interesting: int = 4
    max_consecutive_thoughts: int = 4


@dataclass
class ConvergenceSignal:
    """A detected convergence signal with confidence and explanation."""

    # "plateau" | "consecutive_discards" | "alternating" |
    # "code_repetition" | "timeout_streak"
    signal_type: str
    confidence: float  # 0.0 to 1.0
    detail: str  # human-readable explanation


def detect_signals(
    entries: list[ExperimentEntry],
    thresholds: ConvergenceThresholds | None = None,
) -> list[ConvergenceSignal]:
    """Detect convergence signals from experiment history."""
    if thresholds is None:
        thresholds = ConvergenceThresholds()
    signals = []
    for detector in [
        _detect_plateau,
        _detect_consecutive_discards,
        _detect_alternating,
        _detect_code_repetition,
        _detect_timeout_streak,
        _detect_consecutive_interesting,
        _detect_consecutive_thoughts,
    ]:
        result = detector(entries, thresholds)
        if result:
            signals.append(result)
    return signals


def _detect_plateau(
    entries: list[ExperimentEntry],
    thresholds: ConvergenceThresholds,
) -> ConvergenceSignal | None:
    """Fire when the last N keep entries show negligible metric improvement."""
    keeps = [e for e in entries if e.status == "keep" and e.metric_value is not None]
    if len(keeps) < thresholds.plateau_window:
        return None

    window = keeps[-thresholds.plateau_window :]
    first_val = window[0].metric_value
    last_val = window[-1].metric_value

    # Both are guaranteed non-None by the filter above, but satisfy the type checker
    assert first_val is not None and last_val is not None

    abs_improvement = abs(last_val - first_val)
    rel_improvement = abs_improvement / abs(first_val) if first_val != 0.0 else abs_improvement

    if (
        abs_improvement < thresholds.plateau_threshold
        and rel_improvement < thresholds.plateau_threshold
    ):
        # Confidence rises as improvement shrinks toward zero
        raw = 1.0 - max(abs_improvement, rel_improvement) / thresholds.plateau_threshold
        confidence = max(0.0, min(raw, 1.0))
        return ConvergenceSignal(
            signal_type="plateau",
            confidence=confidence,
            detail=(
                f"Last {thresholds.plateau_window} keeps show only {rel_improvement:.4f} "
                f"relative improvement (threshold {thresholds.plateau_threshold})"
            ),
        )
    return None


def _detect_trailing_streak(
    entries: list[ExperimentEntry],
    target_statuses: set[str],
    signal_type: str,
    threshold: int,
    label: str,
) -> ConvergenceSignal | None:
    """Generic trailing-streak detector. Fires when the last N entries all match target_statuses."""
    count = 0
    for entry in reversed(entries):
        if entry.status in target_statuses:
            count += 1
        else:
            break

    if count >= threshold:
        confidence = min(count / (threshold + 2), 1.0)
        return ConvergenceSignal(
            signal_type=signal_type,
            confidence=confidence,
            detail=f"{count} consecutive {label} (threshold {threshold})",
        )
    return None


def _detect_consecutive_discards(
    entries: list[ExperimentEntry],
    thresholds: ConvergenceThresholds,
) -> ConvergenceSignal | None:
    """Fire when trailing entries are all discards or crashes."""
    return _detect_trailing_streak(
        entries,
        {"discard", "crash"},
        "consecutive_discards",
        thresholds.max_consecutive_discards,
        "discard/crash entries",
    )


def _detect_alternating(
    entries: list[ExperimentEntry],
    thresholds: ConvergenceThresholds,
) -> ConvergenceSignal | None:
    """Fire when the last N entries oscillate between keep and non-keep."""
    window = entries[-thresholds.alternating_window :]
    if len(window) < thresholds.alternating_window:
        return None

    statuses = [e.status for e in window]
    alternations = sum(
        1 for i in range(1, len(statuses)) if (statuses[i] == "keep") != (statuses[i - 1] == "keep")
    )
    ratio = alternations / (len(statuses) - 1)

    if ratio >= thresholds.alternating_ratio:
        return ConvergenceSignal(
            signal_type="alternating",
            confidence=ratio,
            detail=(
                f"Alternation ratio {ratio:.2f} over last {thresholds.alternating_window} entries "
                f"(threshold {thresholds.alternating_ratio:.2f})"
            ),
        )
    return None


def _detect_code_repetition(
    entries: list[ExperimentEntry],
    thresholds: ConvergenceThresholds,
) -> ConvergenceSignal | None:
    """Fire when the same file is repeatedly touched within the recent window."""
    window = entries[-thresholds.code_repetition_window :]
    if not window:
        return None

    counts: dict[str, int] = {}
    for entry in window:
        for f in entry.files_touched:
            counts[f] = counts.get(f, 0) + 1

    if not counts:
        return None

    max_file, max_count = max(counts.items(), key=lambda kv: kv[1])
    if max_count >= thresholds.code_repetition_threshold:
        confidence = min(max_count / thresholds.code_repetition_window, 1.0)
        return ConvergenceSignal(
            signal_type="code_repetition",
            confidence=confidence,
            detail=(
                f"'{max_file}' touched {max_count} times in last "
                f"{thresholds.code_repetition_window} entries "
                f"(threshold {thresholds.code_repetition_threshold})"
            ),
        )
    return None


def _detect_timeout_streak(
    entries: list[ExperimentEntry],
    thresholds: ConvergenceThresholds,
) -> ConvergenceSignal | None:
    """Fire when trailing entries are all timeouts."""
    return _detect_trailing_streak(
        entries,
        {"timeout"},
        "timeout_streak",
        thresholds.max_consecutive_timeouts,
        "timeouts",
    )


def _detect_consecutive_interesting(
    entries: list[ExperimentEntry],
    thresholds: ConvergenceThresholds,
) -> ConvergenceSignal | None:
    """Fire when trailing entries are all 'interesting'."""
    return _detect_trailing_streak(
        entries,
        {"interesting"},
        "consecutive_interesting",
        thresholds.max_consecutive_interesting,
        "interesting entries",
    )


def _detect_consecutive_thoughts(
    entries: list[ExperimentEntry],
    thresholds: ConvergenceThresholds,
) -> ConvergenceSignal | None:
    """Fire when trailing entries are all 'thought'."""
    return _detect_trailing_streak(
        entries,
        {"thought"},
        "consecutive_thoughts",
        thresholds.max_consecutive_thoughts,
        "thought entries",
    )
