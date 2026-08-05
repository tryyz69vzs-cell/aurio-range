"""Lineage records: what changed, why, how it scored, and whether it survived."""

from __future__ import annotations

from typing import Any, Mapping

from evolution.models import Candidate


def build_node(
    candidate: Candidate,
    parent: Candidate | None,
    novelty_score: float,
    narrative: str,
) -> dict[str, Any]:
    strategy = candidate.strategy
    delta = candidate.evaluation_score - (
        parent.evaluation_score if parent is not None else 0.0
    )
    return {
        "generation": strategy.generation,
        "strategy_id": strategy.strategy_id,
        "parent_strategy_id": strategy.parent_strategy_id,
        "root_strategy_id": strategy.root_strategy_id,
        "origin_pattern": strategy.origin_pattern,
        "changed_fields": list(strategy.changed_fields),
        "previous_values": dict(strategy.previous_values),
        "new_values": dict(strategy.new_values),
        "mutation_reason": strategy.mutation_reason,
        "novelty": round(novelty_score, 6),
        "training_fitness": round(candidate.training_score, 6),
        "evaluation_fitness": round(candidate.evaluation_score, 6),
        "delta_from_parent": round(delta, 6),
        "training_breakdown": candidate.training_fitness.as_dict(),
        "evaluation_breakdown": (
            None if candidate.evaluation_fitness is None
            else candidate.evaluation_fitness.as_dict()
        ),
        "raw_metrics": candidate.training_metrics.as_dict(),
        "evaluation_raw_metrics": (
            None if candidate.evaluation_metrics is None
            else candidate.evaluation_metrics.as_dict()
        ),
        "top_detected_blue_signals": list(
            candidate.training_metrics.top_blue_signals
        ),
        "user_behavior_summary": candidate.training_metrics.user_behavior_summary,
        "safety_validation": {
            "passed": candidate.safety_ok,
            "detail": candidate.safety_detail,
        },
        "keep_or_drop": candidate.keep_or_drop,
        "drop_reason": candidate.drop_reason,
        "promoted_to_hall_of_fame": candidate.promoted,
        "narrative": narrative,
    }


def narrate(candidate: Candidate, parent: Candidate | None) -> str:
    """A plain-Korean sentence explaining the generation-to-generation change."""
    strategy = candidate.strategy
    metrics = candidate.training_metrics
    if parent is None:
        return (
            f"패턴 `{strategy.origin_pattern}` 에서 출발한 초기 전략입니다. "
            f"훈련에서 사전 방어 통과 {metrics.pre_delivery_escape}회, "
            f"클릭 {metrics.user_click}회, 제출 {metrics.user_submit}회를 "
            f"기록했습니다."
        )
    parent_metrics = parent.training_metrics
    changed = ", ".join(strategy.changed_fields) or "없음"
    direction = (
        "개선되어" if candidate.evaluation_score > parent.evaluation_score
        else "개선되지 못해"
    )
    return (
        f"부모 전략은 클릭 {parent_metrics.user_click}회, 제출 "
        f"{parent_metrics.user_submit}회를 기록했습니다. 자식 전략은 "
        f"`{changed}` 필드를 바꿨고, 숨김 평가에서 "
        f"{parent.evaluation_score:.2f} → {candidate.evaluation_score:.2f} 로 "
        f"{direction} `{candidate.keep_or_drop}` 판정을 받았습니다."
    )
