"""Experiment harness for router keyword weight optimization.

Runs a labeled corpus through _tier2_keyword_heuristic with configurable
threshold and weight overrides, computing accuracy/escalation/FP metrics.
"""

from __future__ import annotations

import copy
import json
import re
import timeit
from pathlib import Path

from src.router import _KEYWORD_SCORES, RouterResult

FIXTURES = Path(__file__).parent / "fixtures"
TRAIN_CORPUS = FIXTURES / "router_corpus_train.json"
HOLDOUT_CORPUS = FIXTURES / "router_corpus_holdout.json"


def load_corpus(path: Path) -> list[dict[str, str]]:
    """Load a labeled corpus file."""
    return json.loads(path.read_text())


def score_prompt(
    prompt: str,
    threshold: float = 0.6,
    weight_overrides: dict[str, list[tuple[str, float]]] | None = None,
    use_word_boundary: bool = False,
) -> RouterResult | None:
    """Score a prompt using the Tier 2 heuristic with optional overrides.

    This reimplements the scoring logic so we can inject different parameters
    without modifying the production code.
    """
    keywords = weight_overrides if weight_overrides else _KEYWORD_SCORES
    normalized = prompt.strip().lower()
    best_skill = ""
    best_score = 0.0

    for skill, kws in keywords.items():
        sorted_kws = sorted(kws, key=lambda x: len(x[0]), reverse=True)
        matched: list[str] = []
        score = 0.0
        for kw, weight in sorted_kws:
            if use_word_boundary:
                if not re.search(r"\b" + re.escape(kw) + r"\b", normalized):
                    continue
            else:
                if kw not in normalized:
                    continue
            # Skip if substring of already-matched keyword
            if any(kw in m for m in matched):
                continue
            matched.append(kw)
            score += weight
        if score > best_score:
            best_score = score
            best_skill = skill

    if best_score >= threshold:
        return RouterResult(
            skill=best_skill,
            confidence=min(best_score, 1.0),
            tier=2,
            reasoning=f"Keyword match: {best_skill} (score: {best_score:.2f})",
        )
    return None


def evaluate_corpus(
    corpus: list[dict[str, str]],
    threshold: float = 0.6,
    weight_overrides: dict[str, list[tuple[str, float]]] | None = None,
    use_word_boundary: bool = False,
) -> dict:
    """Run a corpus through the heuristic and compute metrics.

    Returns dict with:
      - accuracy: correct / total_routed
      - escalation_rate: fell_through / total
      - false_positive_rate: wrong_skill / total_routed
      - per_skill: {skill: {tp, fp, fn, accuracy, ...}}
      - details: list of per-prompt results
    """
    total = len(corpus)
    correct = 0
    wrong = 0
    fell_through = 0
    correct_fallthrough = 0  # expected none AND got none

    # Per-skill tracking
    skills = set()
    for entry in corpus:
        if entry["expected_skill"] != "none":
            skills.add(entry["expected_skill"])
    per_skill: dict[str, dict[str, int]] = {s: {"tp": 0, "fp": 0, "fn": 0} for s in skills}

    details: list[dict] = []

    for entry in corpus:
        prompt = entry["prompt"]
        expected = entry["expected_skill"]
        result = score_prompt(prompt, threshold, weight_overrides, use_word_boundary)

        predicted = "none" if result is None else result.skill

        detail = {
            "prompt": prompt,
            "expected": expected,
            "predicted": predicted,
            "score": result.confidence if result else 0.0,
        }
        details.append(detail)

        if expected == "none" and predicted == "none":
            correct_fallthrough += 1
        elif expected == "none" and predicted != "none":
            wrong += 1
            if predicted in per_skill:
                per_skill[predicted]["fp"] += 1
        elif expected != "none" and predicted == "none":
            fell_through += 1
            if expected in per_skill:
                per_skill[expected]["fn"] += 1
        elif predicted == expected:
            correct += 1
            if expected in per_skill:
                per_skill[expected]["tp"] += 1
        else:
            wrong += 1
            if predicted in per_skill:
                per_skill[predicted]["fp"] += 1
            if expected in per_skill:
                per_skill[expected]["fn"] += 1

    total_routed = correct + wrong
    total_expected_skill = total - sum(1 for e in corpus if e["expected_skill"] == "none")

    return {
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "fell_through": fell_through,
        "correct_fallthrough": correct_fallthrough,
        "accuracy": correct / total_routed if total_routed > 0 else 0.0,
        "escalation_rate": fell_through / total_expected_skill if total_expected_skill > 0 else 0.0,
        "false_positive_rate": wrong / total_routed if total_routed > 0 else 0.0,
        "per_skill": per_skill,
        "details": details,
    }


def print_metrics(metrics: dict, label: str = "Results") -> None:
    """Pretty-print evaluation metrics."""
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    print(f"  Total prompts:      {metrics['total']}")
    print(f"  Correct routes:     {metrics['correct']}")
    print(f"  Wrong routes:       {metrics['wrong']}")
    print(f"  Fell through:       {metrics['fell_through']}")
    print(f"  Correct fallthrough:{metrics['correct_fallthrough']}")
    print(f"  Accuracy:           {metrics['accuracy']:.1%}")
    print(f"  Escalation rate:    {metrics['escalation_rate']:.1%}")
    print(f"  False positive rate:{metrics['false_positive_rate']:.1%}")
    print("\n  Per-skill breakdown:")
    for skill, counts in sorted(metrics["per_skill"].items()):
        total_expected = counts["tp"] + counts["fn"]
        skill_acc = counts["tp"] / total_expected if total_expected > 0 else 0.0
        print(
            f"    {skill:15s}  TP={counts['tp']}  FP={counts['fp']}  "
            f"FN={counts['fn']}  acc={skill_acc:.0%}"
        )


def sweep_threshold(
    corpus: list[dict[str, str]],
    low: float = 0.4,
    high: float = 0.8,
    step: float = 0.05,
    weight_overrides: dict[str, list[tuple[str, float]]] | None = None,
    use_word_boundary: bool = False,
) -> list[dict]:
    """Sweep threshold values and return metrics for each."""
    results = []
    t = low
    while t <= high + 0.001:
        m = evaluate_corpus(corpus, t, weight_overrides, use_word_boundary)
        results.append(
            {
                "threshold": round(t, 2),
                "accuracy": m["accuracy"],
                "escalation_rate": m["escalation_rate"],
                "false_positive_rate": m["false_positive_rate"],
                "correct": m["correct"],
                "wrong": m["wrong"],
                "fell_through": m["fell_through"],
            }
        )
        t += step
    return results


def sweep_keyword_weights(
    corpus: list[dict[str, str]],
    skill: str,
    threshold: float,
    base_weights: dict[str, list[tuple[str, float]]],
    use_word_boundary: bool = False,
) -> dict[str, tuple[float, float, float]]:
    """Sweep each keyword weight for a skill, return best weight per keyword.

    Returns {keyword: (best_weight, best_accuracy, baseline_accuracy)}
    """
    baseline = evaluate_corpus(corpus, threshold, base_weights, use_word_boundary)
    baseline_acc = baseline["accuracy"]
    best_per_kw: dict[str, tuple[float, float, float]] = {}

    for i, (kw, current_weight) in enumerate(base_weights[skill]):
        best_weight = current_weight
        best_acc = baseline_acc

        for delta in [-0.15, -0.10, -0.05, 0.05, 0.10, 0.15]:
            new_weight = round(current_weight + delta, 2)
            if new_weight < 0.05 or new_weight > 0.95:
                continue

            trial = copy.deepcopy(base_weights)
            trial[skill][i] = (kw, new_weight)
            m = evaluate_corpus(corpus, threshold, trial, use_word_boundary)

            # Better accuracy, or same accuracy with lower FP rate
            if m["accuracy"] > best_acc or (
                m["accuracy"] == best_acc
                and m["false_positive_rate"] < baseline["false_positive_rate"]
            ):
                best_acc = m["accuracy"]
                best_weight = new_weight

        best_per_kw[kw] = (best_weight, best_acc, baseline_acc)

    return best_per_kw


def benchmark_scoring(n: int = 10000, use_word_boundary: bool = False) -> float:
    """Benchmark scoring performance. Returns avg microseconds per call."""
    prompt = "design an implementation plan and clarify the approach for the auth module"

    def run():
        score_prompt(prompt, use_word_boundary=use_word_boundary)

    total = timeit.timeit(run, number=n)
    return (total / n) * 1_000_000  # microseconds


if __name__ == "__main__":
    corpus = load_corpus(TRAIN_CORPUS)
    metrics = evaluate_corpus(corpus)
    print_metrics(metrics, "Baseline (threshold=0.6, current weights)")
