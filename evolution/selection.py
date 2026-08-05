"""Selection, deduplication, novelty, and promotion rules."""

from __future__ import annotations

from typing import Iterable, Sequence

from evolution.models import Candidate, Strategy


def similarity(left: Strategy, right: Strategy) -> float:
    """Fraction of allowlisted fields that hold the same value."""
    keys = set(left.fields) | set(right.fields)
    if not keys:
        return 1.0
    same = sum(1 for key in keys if left.fields.get(key) == right.fields.get(key))
    return same / len(keys)


def novelty(strategy: Strategy, existing: Iterable[Strategy]) -> float:
    """1.0 when nothing like it exists, 0.0 when an identical one does."""
    scores = [similarity(strategy, other) for other in existing
              if other.strategy_id != strategy.strategy_id]
    if not scores:
        return 1.0
    return max(0.0, 1.0 - max(scores))


def deduplicate(strategies: Sequence[Strategy]) -> tuple[list[Strategy], list[Strategy]]:
    """Split into unique strategies and exact fingerprint duplicates."""
    seen: set[str] = set()
    unique: list[Strategy] = []
    duplicates: list[Strategy] = []
    for strategy in strategies:
        if strategy.fingerprint in seen:
            duplicates.append(strategy)
        else:
            seen.add(strategy.fingerprint)
            unique.append(strategy)
    return unique, duplicates


def select_parents(candidates: Sequence[Candidate], count: int) -> list[Candidate]:
    """Rank by training fitness; safety failures can never be selected."""
    eligible = [c for c in candidates if c.safety_ok]
    ranked = sorted(
        eligible,
        key=lambda c: (-c.training_score, c.strategy.strategy_id),
    )
    return ranked[: max(1, count)]


def promotion_decision(
    candidate: Candidate,
    parent: Candidate | None,
    *,
    min_novelty: float,
    min_reproducibility: float,
    novelty_score: float,
    reproducibility_score: float,
    profile_balance_score: float,
) -> tuple[bool, str]:
    """Every promotion gate, evaluated in order. Returns (promote, reason)."""
    if not candidate.safety_ok:
        return False, f"safety 검증 실패: {candidate.safety_detail}"
    if candidate.evaluation_fitness is None:
        return False, "숨김 평가가 실행되지 않음"
    if novelty_score < min_novelty:
        return False, f"novelty {novelty_score:.3f} < 기준 {min_novelty:.3f}"
    if reproducibility_score < min_reproducibility:
        return False, (
            f"재현성 {reproducibility_score:.3f} < 기준 {min_reproducibility:.3f}"
        )
    if profile_balance_score <= 0.0 and len(
        candidate.training_metrics.per_profile_scores
    ) > 1:
        return False, "단일 사용자 프로필에만 의존"
    # Compare like with like: penalty-free performance on both sides, so the
    # generalization penalty already inside evaluation_score is not counted twice.
    if candidate.evaluation_performance < candidate.training_performance * 0.5:
        return False, (
            f"훈련 {candidate.training_performance:.3f} 대비 평가 "
            f"{candidate.evaluation_performance:.3f} 로 과적합"
        )
    if (
        parent is not None
        and candidate.evaluation_performance <= parent.evaluation_performance
    ):
        return False, (
            f"숨김 평가가 부모({parent.evaluation_performance:.3f}) 대비 "
            "개선되지 않음"
        )
    return True, "승격 기준 충족"
