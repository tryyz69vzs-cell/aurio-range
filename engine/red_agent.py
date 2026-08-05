"""Rule-based Red agent that emits structured scenario variables only."""

from __future__ import annotations

from typing import Any, Mapping


_TACTIC_ID_BY_FAMILY = {
    "sender_forgery": "obvious-spoof",
    "trusted_channel_abuse": "trusted-relay-abuse",
    "incident_echo": "event-shadowing",
    "support_impersonation": "trusted-relay-abuse",
    "enforcement_notice": "obvious-spoof",
}


def build_scenario(
    account: Mapping[str, Any],
    difficulty: str,
    visual: Mapping[str, Any],
    triggered_event: Mapping[str, Any] | None = None,
    strategy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return data only—never markup, styles, scripts, or executable strings."""
    if difficulty not in {"easy", "medium", "hard"}:
        raise ValueError("난이도는 easy, medium, hard 중 하나여야 합니다.")
    if difficulty == "hard" and not triggered_event:
        raise ValueError("Hard 시나리오에는 공식 사건 참조가 필요합니다.")

    event_ref = (
        str(triggered_event["event_ref"])
        if triggered_event
        else f"AR-{difficulty[:1].upper()}-{int(account['id']):04d}"
    )
    greeting = visual["tone"]["greeting"].format(username=account["username"])

    definitions = {
        "easy": {
            "subject": "즉시 새로운 로그인 활동을 확인해 주세요",
            "body": "낯선 환경의 로그인 시도가 감지되었습니다. 즉시 활동을 확인해 주세요.",
            "urgency": "high",
            "sender": "notice@aur1o.test",
            "destination": "synthetic_capture_easy",
            "auth": "FAIL",
            "signature": "none",
            "ingress": "synthetic_external",
            "tactic_id": "obvious-spoof",
        },
        "medium": {
            "subject": "새로운 로그인 활동을 확인해 주세요",
            "body": "계정에서 새로운 로그인 활동이 관찰되었습니다. 활동 내역을 확인해 주세요.",
            "urgency": "low",
            "sender": "security@aurio.test",
            "destination": "synthetic_capture_medium",
            "auth": "SOFTFAIL",
            "signature": "none",
            "ingress": "authorized_relay",
            "tactic_id": "trusted-relay-abuse",
        },
        "hard": {
            "subject": "즉시 새로운 로그인 활동을 확인해 주세요",
            "body": "낯선 환경의 로그인 시도가 감지되었습니다. 즉시 활동을 확인해 주세요.",
            "urgency": "high",
            "sender": "security@aurio.test",
            "destination": "synthetic_capture_hard",
            "auth": "SOFTFAIL",
            "signature": "none",
            "ingress": "authorized_relay",
            "tactic_id": "event-shadowing",
        },
    }
    chosen = dict(definitions[difficulty])
    tactic_id = chosen["tactic_id"]
    layout_variant = "shared"
    if strategy:
        # Only allowlisted, already-validated enum values may land here.
        chosen["auth"] = str(strategy.get("sender_auth_level", chosen["auth"]))
        chosen["signature"] = {
            "valid": "valid", "invalid": "invalid", "none": "none",
        }.get(str(strategy.get("signature_state", "none")), chosen["signature"])
        chosen["ingress"] = str(
            strategy.get("ingress_variant", chosen["ingress"])
        )
        chosen["urgency"] = str(
            strategy.get("urgency_level", chosen["urgency"])
        )
        if str(strategy.get("destination_ownership_class")) == "registered":
            chosen["destination"] = "official_alerts"
        tactic_id = _TACTIC_ID_BY_FAMILY.get(
            str(strategy.get("tactic_family", "")), tactic_id
        )
        # Layout stays the shared brandkit layout on purpose: official and
        # forged artifacts must remain visually identical. The strategy's
        # layout_variant only shapes the report and the schematic preview.
    return {
        "scenario_type": "forged_security_alert",
        "display_sender": f"{visual['brand_name']} 보안팀",
        "synthetic_sender_address": chosen["sender"],
        "subject_text": chosen["subject"],
        "greeting_text": greeting,
        "body_text": chosen["body"],
        "action_label": "계정 활동 확인",
        "page_title": "계정 활동 확인",
        "page_body": "계속하려면 합성 계정 확인 단계를 완료하세요.",
        "page_action_label": "안전 확인",
        "urgency_level": chosen["urgency"],
        "claimed_event_type": "suspicious_login",
        "claimed_event_ref": event_ref,
        "destination_identifier": chosen["destination"],
        "difficulty": difficulty,
        "tactics": {
            "tactic_id": tactic_id,
            "sender_auth_result": chosen["auth"],
            "signature_mode": chosen["signature"],
            "ingress_mode": chosen["ingress"],
            "layout_variant": layout_variant,
        },
    }
