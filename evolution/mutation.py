"""Mutate one or two allowlisted fields. Nothing else can change."""

from __future__ import annotations

import random
from typing import Any

from evolution.action_space import ACTION_SPACE, MUTABLE_FIELDS, validate_strategy
from evolution.models import Strategy


FIELD_REASON = {
    "urgency_level": "긴급도를 조정해 사용자 반응 임계를 탐색",
    "sender_auth_level": "발신 인증 수준을 바꿔 탐지 신호 기여를 탐색",
    "signature_state": "서명 상태를 바꿔 서명 신호 의존도를 탐색",
    "destination_ownership_class": "목적지 소유 신호의 영향력을 탐색",
    "event_record_alignment": "사건 기록 신호의 무력화 가능성을 탐색",
    "information_density": "정보 밀도를 바꿔 사용자 판단 부담을 조정",
    "personalization_level": "개인화 수준을 바꿔 신뢰 형성을 탐색",
    "timing_variant": "전달 타이밍을 바꿔 공식 알림과의 관계를 탐색",
    "target_profile": "다른 사용자 유형으로 일반화 가능성을 탐색",
}


def _reason(field: str, old: Any, new: Any) -> str:
    base = FIELD_REASON.get(field, f"`{field}` 값을 바꿔 방어 반응 변화를 탐색")
    return f"{base} ({old!r} → {new!r})"


def mutate(
    parent: Strategy, generation: int, index: int, rng: random.Random
) -> Strategy:
    """Return a child differing from the parent in exactly 1 or 2 fields."""
    count = rng.choice((1, 1, 2))
    candidates = [f for f in MUTABLE_FIELDS if len(ACTION_SPACE[f]) > 1]
    rng.shuffle(candidates)

    fields = dict(parent.fields)
    changed: list[str] = []
    previous: dict[str, Any] = {}
    new_values: dict[str, Any] = {}
    reasons: list[str] = []
    for name in candidates:
        if len(changed) >= count:
            break
        options = [v for v in ACTION_SPACE[name] if v != fields[name]]
        if not options:
            continue
        chosen = rng.choice(options)
        previous[name] = fields[name]
        new_values[name] = chosen
        reasons.append(_reason(name, fields[name], chosen))
        fields[name] = chosen
        changed.append(name)

    # Keep the strategy internally coherent without leaving the allowlist.
    if fields["warning_escape_target"] and fields["urgency_level"] == "low":
        fields["urgency_level"] = "high"
    validate_strategy(fields)
    return Strategy(
        fields=fields,
        strategy_id=f"g{generation}-{index:02d}-{parent.strategy_id[-6:]}",
        parent_strategy_id=parent.strategy_id,
        root_strategy_id=parent.root_strategy_id,
        generation=generation,
        origin_pattern=parent.origin_pattern,
        changed_fields=tuple(changed),
        previous_values=previous,
        new_values=new_values,
        mutation_reason="; ".join(reasons) or "변경 없음",
    )
