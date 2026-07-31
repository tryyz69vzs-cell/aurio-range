"""Risk scoring before delivery and state-only response after User actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse

from engine.db import BlueRepo
from engine.detection_params import DetectionParams, classify_risk
from engine.observation import BlueObservation


@dataclass(frozen=True)
class PreAssessment:
    risk_total: int
    band: str
    pre_delivery_action: str
    signals: dict[str, dict[str, Any]]
    assessment_step: int = -1


@dataclass(frozen=True)
class PostResponse:
    response: str
    response_step: int
    page_blocked: bool
    account_status: str
    session_state: str


def _signal(score: int, value: str) -> dict[str, Any]:
    return {"value": value, "score": score}


def pre_delivery_assess(
    obs: BlueObservation,
    repo: BlueRepo,
    params: DetectionParams,
) -> PreAssessment:
    if type(obs) is not BlueObservation:
        raise TypeError("BlueObservation만 사전 검사에 전달할 수 있습니다.")
    registry = repo.registry
    weights = params.weights

    registered_sender = obs.auth_sender_address in registry["official_senders"]
    auth_value = obs.sender_auth_result
    claims_official = "aurio" in obs.display_sender_name.lower()
    aligned = not claims_official or registered_sender

    expected_signature = (
        f"{registry['signature_prefix']}{obs.claimed_event_ref}"
        if obs.claimed_event_ref
        else None
    )
    if obs.signature_token is None:
        signature_value = "NONE"
    elif expected_signature is not None and obs.signature_token == expected_signature:
        signature_value = "VALID"
    else:
        signature_value = "INVALID"

    destination = urlparse(obs.link_destination)
    owned_destination = (
        destination.scheme == "https"
        and destination.hostname in registry["official_hosts"]
        and destination.path in registry["official_routes"]
    )
    event_exists = repo.official_event_exists(
        obs.account_id, obs.claimed_event_ref
    )
    if obs.ingress_channel == "internal_service":
        ingress_value = "trusted"
    elif obs.ingress_channel.startswith("relay:") and (
        obs.ingress_channel.split(":", 1)[1] in registry["authorized_relays"]
    ):
        ingress_value = "trusted"
    elif obs.ingress_channel.startswith("external:"):
        ingress_value = "external"
    else:
        ingress_value = "unknown"

    urgency_present = any(
        token in obs.body_text for token in ("즉시", "긴급", "차단", "마지막 경고")
    )
    contradiction = (
        obs.claimed_event_type == "account_locked"
        and obs.account_status_snapshot == "active"
    )
    signals = {
        "sender_registry": _signal(
            weights["sender_registry"][
                "registered" if registered_sender else "unregistered"
            ],
            "registered" if registered_sender else "unregistered",
        ),
        "sender_auth": _signal(weights["sender_auth"][auth_value], auth_value),
        "display_alignment": _signal(
            weights["display_alignment"]["aligned" if aligned else "misaligned"],
            "aligned" if aligned else "misaligned",
        ),
        "signature_validity": _signal(
            weights["signature_validity"][signature_value], signature_value
        ),
        "destination_ownership": _signal(
            weights["destination_ownership"][
                "registered" if owned_destination else "unregistered"
            ],
            "registered" if owned_destination else "unregistered",
        ),
        "official_event_record": _signal(
            weights["official_event_record"]["exists" if event_exists else "missing"],
            "exists" if event_exists else "missing",
        ),
        "ingress_channel": _signal(
            weights["ingress_channel"][ingress_value], ingress_value
        ),
        "urgency_authority": _signal(
            weights["urgency_authority"]["present" if urgency_present else "absent"],
            "present" if urgency_present else "absent",
        ),
        "state_consistency": _signal(
            weights["state_consistency"][
                "contradictory" if contradiction else "consistent"
            ],
            "contradictory" if contradiction else "consistent",
        ),
    }
    total = sum(item["score"] for item in signals.values())
    band, action = classify_risk(total, params.strictness)
    return PreAssessment(total, band, action, signals)


def post_action_response(
    action_event: Mapping[str, Any],
    repo: BlueRepo,
    params: DetectionParams,
) -> PostResponse:
    del params
    required = {"event_type", "message_id", "account_id", "step_index"}
    if not isinstance(action_event, Mapping) or not required <= set(action_event):
        raise TypeError("행동 이벤트 매핑이 필요합니다.")
    event_type = str(action_event["event_type"])
    message_id = int(action_event["message_id"])
    account_id = int(action_event["account_id"])
    step_index = int(action_event["step_index"])

    page_blocked = False
    status = repo.account_snapshot(account_id)["status"]
    session = repo.account_snapshot(account_id)["session_state"]
    response = "observed"
    if event_type == "USER_REPORT":
        repo.mark_report_handled(message_id)
        page_blocked = repo.block_page(message_id, step_index)
        response = "reported_handled"
    elif event_type == "USER_CLICK":
        page_blocked = repo.block_page(message_id, step_index)
        repo.protect_account(account_id, "active", "stepup_required")
        session = "stepup_required"
        response = "page_blocked_stepup_required"
    elif event_type == "USER_SUBMIT":
        page_blocked = repo.block_page(message_id, step_index)
        repo.protect_account(account_id, "recovery_pending", "revoked")
        status = "recovery_pending"
        session = "revoked"
        response = "contained"
    repo.save_post_response(message_id, response, step_index)
    repo.commit()
    return PostResponse(response, step_index, page_blocked, status, session)
