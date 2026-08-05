"""Fitness coefficients and computation. All weights live here for testing."""

from __future__ import annotations

import statistics
from typing import Mapping

from evolution.models import FitnessBreakdown, RawMetrics


WEIGHTS: dict[str, float] = {
    "pre_delivery_escape": 1.0,
    "warn_reached": 0.6,
    "warning_escape": 1.6,
    "user_click": 1.2,
    "user_submit": 2.0,
    "credential_exposure": 2.6,
    "takeover_success": 3.4,
    "official_event_signal_neutralized": 1.0,
    "blue_failure_discovery": 1.4,
    "profile_coverage": 1.2,
    "difficulty_coverage": 1.0,
    "novelty": 1.5,
    "reproducibility": 1.5,
    "evaluation_generalization": 2.0,
    "lineage_diversity": 0.8,
    "safety_compliance": 1.0,
}

PENALTIES: dict[str, float] = {
    "safety_violation": -40.0,
    "duplicate_strategy": -12.0,
    "excessive_similarity": -6.0,
    "training_seed_overfit": -5.0,
    "single_profile_overfit": -5.0,
    "evaluation_regression": -8.0,
}


def _rate(numerator: int, denominator: int) -> float:
    return 0.0 if denominator <= 0 else numerator / denominator


def reproducibility(metrics: RawMetrics) -> float:
    """1.0 when per-seed outcomes agree, lower when they scatter."""
    scores = list(metrics.per_seed_scores)
    if len(scores) < 2:
        return 1.0 if scores else 0.0
    spread = statistics.pstdev(scores)
    mean = statistics.fmean(scores)
    if mean <= 0:
        return 1.0 if spread == 0 else 0.0
    return max(0.0, 1.0 - min(1.0, spread / mean))


def profile_balance(metrics: RawMetrics) -> float:
    """1.0 when a strategy works across profiles, 0.0 when it needs just one."""
    scores = [v for v in metrics.per_profile_scores.values()]
    if len(scores) < 2:
        return 0.0
    total = sum(scores)
    if total <= 0:
        return 0.0
    top = max(scores)
    return max(0.0, 1.0 - (top / total - 1.0 / len(scores)) / (1.0 - 1.0 / len(scores)))


def compute_fitness(
    metrics: RawMetrics,
    *,
    novelty: float,
    lineage_diversity: float = 0.0,
    safety_ok: bool = True,
    duplicate: bool = False,
    excessive_similarity: bool = False,
    evaluation_delta: float | None = None,
    weights: Mapping[str, float] | None = None,
) -> FitnessBreakdown:
    """Combine independent raw indicators; never score on takeover alone."""
    table = dict(WEIGHTS)
    if weights:
        table.update(weights)
    attempts = max(1, metrics.attempts)
    repro = reproducibility(metrics)
    balance = profile_balance(metrics)

    components = {
        "pre_delivery_escape": table["pre_delivery_escape"]
        * _rate(metrics.pre_delivery_escape, attempts),
        "warn_reached": table["warn_reached"] * _rate(metrics.warn_reached, attempts),
        "warning_escape": table["warning_escape"]
        * _rate(metrics.warning_escape, attempts),
        "user_click": table["user_click"] * _rate(metrics.user_click, attempts),
        "user_submit": table["user_submit"] * _rate(metrics.user_submit, attempts),
        "credential_exposure": table["credential_exposure"]
        * _rate(metrics.credential_exposure, attempts),
        "takeover_success": table["takeover_success"]
        * _rate(metrics.takeover_success, attempts),
        "official_event_signal_neutralized": table[
            "official_event_signal_neutralized"
        ] * _rate(metrics.official_event_signal_neutralized, attempts),
        "blue_failure_discovery": table["blue_failure_discovery"]
        * _rate(metrics.blue_failure_discovery, attempts),
        "profile_coverage": table["profile_coverage"] * balance,
        "difficulty_coverage": table["difficulty_coverage"]
        * _rate(metrics.difficulties_covered, 3),
        "novelty": table["novelty"] * max(0.0, min(1.0, novelty)),
        "reproducibility": table["reproducibility"] * repro,
        "lineage_diversity": table["lineage_diversity"]
        * max(0.0, min(1.0, lineage_diversity)),
        "safety_compliance": table["safety_compliance"] * (1.0 if safety_ok else 0.0),
    }
    if evaluation_delta is not None:
        components["evaluation_generalization"] = table[
            "evaluation_generalization"
        ] * max(-1.0, min(1.0, evaluation_delta))

    penalties: dict[str, float] = {}
    if not safety_ok:
        penalties["safety_violation"] = PENALTIES["safety_violation"]
    if duplicate:
        penalties["duplicate_strategy"] = PENALTIES["duplicate_strategy"]
    if excessive_similarity:
        penalties["excessive_similarity"] = PENALTIES["excessive_similarity"]
    if repro < 0.5:
        penalties["training_seed_overfit"] = PENALTIES["training_seed_overfit"] * (
            1.0 - repro
        )
    if balance < 0.34 and len(metrics.per_profile_scores) > 1:
        penalties["single_profile_overfit"] = PENALTIES["single_profile_overfit"]
    if evaluation_delta is not None and evaluation_delta < 0:
        penalties["evaluation_regression"] = PENALTIES["evaluation_regression"] * min(
            1.0, -evaluation_delta
        )

    total = sum(components.values()) + sum(penalties.values())
    return FitnessBreakdown(total=total, components=components, penalties=penalties)
