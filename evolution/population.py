"""Seed the initial population from the abstracted pattern library."""

from __future__ import annotations

import random
from typing import Any, Sequence

from evolution.action_space import ACTION_SPACE
from evolution.models import Strategy
from evolution.patterns import PATTERN_LIBRARY, PATTERN_NAMES


BASE_FIELDS: dict[str, Any] = {
    "tactic_family": "trusted_channel_abuse",
    "target_profile": "average",
    "claimed_event_type": "suspicious_login",
    "objective_type": "credential_submission",
    "sender_auth_level": "SOFTFAIL",
    "signature_state": "none",
    "event_record_alignment": "unaligned",
    "destination_ownership_class": "unregistered",
    "ingress_variant": "authorized_relay",
    "display_alignment_variant": "aligned",
    "timing_variant": "with_official",
    "delay_bucket": 1,
    "notification_pairing": "parallel_unrelated",
    "followup_style": "none",
    "repetition_variant": 1,
    "wording_variant_id": 1,
    "subject_theme": "unfamiliar_signin_review",
    "opening_style": "observed_activity",
    "evidence_style": "unbacked_assertion",
    "consequence_style": "none",
    "reassurance_style": "support_contact",
    "wording_tone": "calm_informative",
    "urgency_level": "low",
    "authority_level": "medium",
    "sentence_count_band": "medium",
    "paragraph_count_band": "short",
    "semantic_sequence_variant": "standard",
    "personalization_level": "named_recipient",
    "template_family": "alert_polished",
    "layout_variant": "single_column_hero",
    "header_variant": "wordmark",
    "CTA_variant": "primary_button",
    "CTA_position": "below_body",
    "visual_emphasis": "medium",
    "information_density": "medium",
    "mobile_layout": "stacked",
    "detail_block_variant": "none",
    "desired_user_action": "click",
    "warning_escape_target": False,
    "verification_target": "neutral",
}

PATTERN_TACTIC = {
    "account_security_alert": "trusted_channel_abuse",
    "account_enforcement": "enforcement_notice",
    "policy_violation_notice": "enforcement_notice",
    "device_login_warning": "sender_forgery",
    "recovery_followup": "support_impersonation",
    "support_impersonation": "support_impersonation",
    "event_shadowing": "incident_echo",
    "warning_escape_test": "trusted_channel_abuse",
    "visual_trust_abuse": "trusted_channel_abuse",
    "synthetic_copyright_claim": "enforcement_notice",
}


def strategy_from_pattern(
    pattern_name: str, profile: str, index: int
) -> Strategy:
    """Project one abstracted pattern onto the allowlisted action space."""
    pattern = PATTERN_LIBRARY[pattern_name]
    fields = dict(BASE_FIELDS)
    for key, value in pattern.items():
        # Pattern traits that fall outside the (safety-narrowed) action space
        # are simply not projected; the base value stays.
        if key in ACTION_SPACE and value in ACTION_SPACE[key]:
            fields[key] = value
    fields["target_profile"] = profile
    fields["tactic_family"] = PATTERN_TACTIC.get(
        pattern_name, fields["tactic_family"]
    )
    if pattern_name == "event_shadowing":
        fields["event_record_alignment"] = "aligned"
        fields["notification_pairing"] = "shadowing"
    if pattern_name == "warning_escape_test":
        fields["warning_escape_target"] = True
        fields["desired_user_action"] = "ignore_warning"
    return Strategy(
        fields=fields,
        strategy_id=f"g0-{index:02d}-{pattern_name[:14]}",
        generation=0,
        origin_pattern=pattern_name,
        mutation_reason=(
            f"패턴 라이브러리 `{pattern_name}` 의 구조적 특징을 "
            f"{profile} 프로필에 투영한 초기 전략"
        ),
    )


# Deterministic spread across the detection-relevant fields so that the very
# first generation already has a fitness gradient to select on.
SIGNAL_SPREAD = (
    ("SOFTFAIL", "unregistered", "unaligned", "authorized_relay", "low"),
    ("PASS", "unregistered", "unaligned", "authorized_relay", "low"),
    ("PASS", "unregistered", "unaligned", "internal_service", "low"),
    ("SOFTFAIL", "unregistered", "aligned", "internal_service", "low"),
    ("PASS", "unregistered", "aligned", "internal_service", "high"),
    ("FAIL", "unregistered", "unaligned", "synthetic_external", "high"),
    ("PASS", "unregistered", "aligned", "authorized_relay", "low"),
    ("SOFTFAIL", "unregistered", "unaligned", "internal_service", "high"),
)


def initial_population(
    size: int, profiles: tuple[str, ...], rng: random.Random
) -> list[Strategy]:
    """Deterministic, pattern-diverse seed population with signal spread."""
    population: list[Strategy] = []
    names = list(PATTERN_NAMES)
    profile_list = list(profiles) or ["average"]
    for index in range(size):
        pattern = names[index % len(names)]
        profile = profile_list[index % len(profile_list)]
        strategy = strategy_from_pattern(pattern, profile, index)
        auth, destination, alignment, ingress, urgency = SIGNAL_SPREAD[
            index % len(SIGNAL_SPREAD)
        ]
        fields = dict(strategy.fields)
        fields["sender_auth_level"] = auth
        fields["destination_ownership_class"] = destination
        fields["event_record_alignment"] = alignment
        fields["ingress_variant"] = ingress
        fields["urgency_level"] = urgency
        population.append(
            Strategy(
                fields=fields,
                strategy_id=strategy.strategy_id,
                generation=0,
                origin_pattern=strategy.origin_pattern,
                mutation_reason=strategy.mutation_reason,
            )
        )
    rng.shuffle(population)
    return population


def restore_strategy(payload: Any) -> Strategy | None:
    """Rebuild a stored strategy, or return None when it is no longer valid.

    The stored generation is an absolute generation number and is kept exactly
    as saved. Adding a run offset here would compound on every run, so the
    offset is only ever used for strategies this run creates.

    Every restored field is re-checked against the current action space, so a
    strategy saved under an older, wider allowlist is discarded rather than
    silently reintroduced.
    """
    if not isinstance(payload, dict):
        return None
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        return None
    cleaned: dict[str, Any] = {}
    for name, value in fields.items():
        if name not in ACTION_SPACE:
            return None
        if isinstance(value, list):
            return None
        if value not in ACTION_SPACE[name]:
            return None
        cleaned[name] = value
    if set(cleaned) != set(ACTION_SPACE):
        return None
    strategy_id = payload.get("strategy_id")
    if not isinstance(strategy_id, str) or not strategy_id:
        return None
    try:
        return Strategy(
            fields=cleaned,
            strategy_id=strategy_id,
            parent_strategy_id=payload.get("parent_strategy_id"),
            root_strategy_id=payload.get("root_strategy_id") or strategy_id,
            generation=int(payload.get("generation", 0)),
            origin_pattern=str(payload.get("origin_pattern", "restored")),
            changed_fields=tuple(payload.get("changed_fields", ()) or ()),
            previous_values=dict(payload.get("previous_values", {}) or {}),
            new_values=dict(payload.get("new_values", {}) or {}),
            mutation_reason=str(
                payload.get("mutation_reason", "이전 실행에서 복원된 전략")
            ),
        )
    except (ValueError, TypeError):
        return None


def restore_population(
    stored_population: Any,
    stored_hall_of_fame: Any,
) -> list[Strategy]:
    """Survivors from a previous run, best-of-fame first, de-duplicated."""
    restored: list[Strategy] = []
    seen: set[str] = set()

    ranked_fame = []
    if isinstance(stored_hall_of_fame, list):
        ranked_fame = sorted(
            (e for e in stored_hall_of_fame if isinstance(e, dict)),
            key=lambda e: -float(e.get("evaluation_fitness", 0.0) or 0.0),
        )
    for source in (ranked_fame, stored_population):
        if not isinstance(source, list):
            continue
        for payload in source:
            strategy = restore_strategy(payload)
            if strategy is None:
                continue
            if strategy.fingerprint in seen:
                continue
            seen.add(strategy.fingerprint)
            restored.append(strategy)
    return restored


def seed_population(
    size: int,
    profiles: tuple[str, ...],
    rng: random.Random,
    carried: Sequence[Strategy] = (),
    generation: int = 0,
) -> list[Strategy]:
    """Carried survivors first, then fresh pattern strategies to fill the gap.

    Survivors keep their own absolute generation. Fillers are stamped with the
    current absolute generation and get an id that encodes it, so a later run
    never re-emits `g0-*` ids and cumulative lineage stays collision-free.
    """
    population: list[Strategy] = list(carried)[:size]
    if len(population) >= size:
        return population
    seen = {s.fingerprint for s in population}
    taken = {s.strategy_id for s in population}
    filler_index = 0
    for candidate in initial_population(size * 2, profiles, rng):
        if candidate.fingerprint in seen:
            continue
        strategy_id = (
            f"g{generation}-seed-{filler_index:02d}-"
            f"{candidate.origin_pattern[:14]}"
        )
        if strategy_id in taken:
            continue
        seen.add(candidate.fingerprint)
        taken.add(strategy_id)
        filler_index += 1
        population.append(
            Strategy(
                fields=dict(candidate.fields),
                strategy_id=strategy_id,
                generation=generation,
                origin_pattern=candidate.origin_pattern,
                mutation_reason=candidate.mutation_reason,
            )
        )
        if len(population) >= size:
            break
    return population[:size]
