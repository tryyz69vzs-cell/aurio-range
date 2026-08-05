"""The allowlist. A strategy may only hold these fields with these values.

This module is the boundary of Adaptive Red's freedom. Values are closed enums
or bounded integers, so a strategy can never carry a free string, markup,
styles, scripts, a URL, an address, or a credential.
"""

from __future__ import annotations

from typing import Any, Mapping


ACTION_SPACE: dict[str, tuple[Any, ...]] = {
    # tactic
    "tactic_family": ("sender_forgery", "trusted_channel_abuse", "incident_echo",
                      "support_impersonation", "enforcement_notice"),
    "target_profile": ("cautious", "average", "careless"),
    "claimed_event_type": ("suspicious_login",),
    "objective_type": ("credential_submission", "link_engagement",
                       "warning_bypass"),
    # provenance signals
    "sender_auth_level": ("PASS", "SOFTFAIL", "FAIL"),
    # The safety validator accepts only these two; the action space is a
    # strict subset of what safety allows, never the other way around.
    "signature_state": ("invalid", "none"),
    "event_record_alignment": ("aligned", "unaligned"),
    # Not evolvable: a forged artifact must always point at the internal
    # capture sink. Allowing "registered" here would let a strategy aim at a
    # real platform route, which the safety validator rejects outright.
    "destination_ownership_class": ("unregistered",),
    "ingress_variant": ("internal_service", "authorized_relay",
                        "synthetic_external"),
    "display_alignment_variant": ("aligned", "misaligned"),
    # delivery
    "timing_variant": ("before_official", "with_official", "after_official"),
    "delay_bucket": (0, 1, 2, 3),
    "notification_pairing": ("unpaired", "parallel_unrelated", "shadowing"),
    "followup_style": ("none", "single_reminder"),
    "repetition_variant": (1, 2),
    # wording
    "wording_variant_id": (1, 2, 3, 4),
    "subject_theme": ("unfamiliar_signin_review", "account_security_notice",
                      "policy_violation_notice", "device_login_warning",
                      "recovery_followup"),
    "opening_style": ("observed_activity", "policy_reference",
                      "support_greeting"),
    "evidence_style": ("referenced_record", "unbacked_assertion",
                       "device_summary"),
    "consequence_style": ("none", "access_restriction", "review_deadline"),
    "reassurance_style": ("support_contact", "safety_note", "none"),
    "wording_tone": ("calm_informative", "neutral_directive",
                     "urgent_directive"),
    "urgency_level": ("low", "high"),
    "authority_level": ("low", "medium", "high"),
    "sentence_count_band": ("short", "medium", "long"),
    "paragraph_count_band": ("short", "medium", "long"),
    "semantic_sequence_variant": ("standard", "evidence_first", "cta_early"),
    "personalization_level": ("generic", "named_recipient"),
    # design
    "template_family": ("alert_basic", "alert_polished",
                        "alert_incident_echo"),
    "layout_variant": ("single_column_compact", "single_column_hero",
                       "single_column_hero_evidence"),
    "header_variant": ("wordmark", "wordmark_with_rule"),
    "CTA_variant": ("primary_button", "inline_link"),
    "CTA_position": ("below_body", "below_instruction", "above_body"),
    "visual_emphasis": ("low", "medium", "high"),
    "information_density": ("short", "medium", "long"),
    "mobile_layout": ("stacked", "compact"),
    "detail_block_variant": ("none", "device_table", "timeline"),
    # desired behaviour
    "desired_user_action": ("click", "submit", "ignore_warning"),
    "warning_escape_target": (False, True),
    "verification_target": ("suppress", "neutral"),
}

MUTABLE_FIELDS: tuple[str, ...] = tuple(ACTION_SPACE)

# Fields that actually reach the detection engine. Everything else shapes the
# artifact description and the report, never the safety-relevant telemetry.
SCORING_FIELDS: frozenset[str] = frozenset(
    {
        "sender_auth_level",
        "signature_state",
        "event_record_alignment",
        "destination_ownership_class",
        "ingress_variant",
        "display_alignment_variant",
        "urgency_level",
    }
)


class ActionSpaceViolation(ValueError):
    """Raised when a candidate strategy leaves the allowlist."""


def validate_strategy(fields: Mapping[str, Any]) -> None:
    """Fail closed on unknown fields, unknown values, and wrong value types."""
    if not isinstance(fields, Mapping):
        raise ActionSpaceViolation("전략은 매핑이어야 합니다.")
    for name, value in fields.items():
        if name not in ACTION_SPACE:
            raise ActionSpaceViolation(f"허용되지 않은 전략 필드: {name}")
        allowed = ACTION_SPACE[name]
        if value not in allowed:
            raise ActionSpaceViolation(
                f"허용되지 않은 값: {name}={value!r}"
            )
        if isinstance(value, str) and value not in allowed:
            raise ActionSpaceViolation(f"자유 문자열 금지: {name}")
    missing = set(ACTION_SPACE) - set(fields)
    if missing:
        raise ActionSpaceViolation(
            f"전략에 빠진 필드: {', '.join(sorted(missing))}"
        )


def is_valid(fields: Mapping[str, Any]) -> bool:
    try:
        validate_strategy(fields)
    except ActionSpaceViolation:
        return False
    return True
