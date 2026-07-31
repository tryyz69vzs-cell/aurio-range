"""Synthetic account, official-event, and trusted rendering operations."""

from __future__ import annotations

import sqlite3
from typing import Any, Mapping
from urllib.parse import urlparse

from brandkit.renderer import destination_url, render_email, render_login


PROFILE_NAMES = {
    "cautious": "민서",
    "average": "지우",
    "careless": "도윤",
}


def create_accounts(
    connection: sqlite3.Connection,
    match_id: int,
    profiles: list[str],
) -> list[sqlite3.Row]:
    for profile in profiles:
        if profile not in PROFILE_NAMES:
            raise ValueError(f"알 수 없는 프로필: {profile}")
        connection.execute(
            """INSERT INTO accounts(
                 match_id, username, email, profile, mfa_enabled, status, session_state
               ) VALUES(?,?,?,?,?,?,?)""",
            (
                match_id,
                PROFILE_NAMES[profile],
                f"{profile}@users.aurio.test",
                profile,
                1 if profile == "cautious" else 0,
                "active",
                "normal",
            ),
        )
    connection.commit()
    return list(
        connection.execute(
            "SELECT * FROM accounts WHERE match_id=? ORDER BY id", (match_id,)
        )
    )


def create_official_event(
    connection: sqlite3.Connection,
    match_id: int,
    account_id: int,
    event_ref: str,
    event_type: str,
    description: str,
    created_step: int,
) -> sqlite3.Row:
    cursor = connection.execute(
        """INSERT INTO official_events(
             match_id, account_id, event_ref, event_type, description, created_step
           ) VALUES(?,?,?,?,?,?)""",
        (match_id, account_id, event_ref, event_type, description, created_step),
    )
    connection.execute(
        "UPDATE accounts SET session_state='anomalous' WHERE id=?", (account_id,)
    )
    connection.commit()
    return connection.execute(
        "SELECT * FROM official_events WHERE id=?", (cursor.lastrowid,)
    ).fetchone()


def official_event_exists(
    connection: sqlite3.Connection, account_id: int, event_ref: str
) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM official_events WHERE account_id=? AND event_ref=? LIMIT 1",
            (account_id, event_ref),
        ).fetchone()
        is not None
    )


def build_official_scenario(
    account: Mapping[str, Any],
    visual: Mapping[str, Any],
    mirrored_red: Mapping[str, Any],
    variant: str,
) -> dict[str, Any]:
    destinations = {
        "normal": "official_alerts",
        "route_drift": "official_drift_route",
        "infrastructure_drift": "official_drift_route",
        "hard_triggered": "official_alerts",
    }
    if variant not in destinations:
        raise ValueError(f"알 수 없는 공식 알림 변형: {variant}")
    ingress_mode = (
        "authorized_relay" if variant == "hard_triggered"
        else "synthetic_external" if variant == "infrastructure_drift"
        else "internal_service"
    )
    return {
        "scenario_type": "official_security_alert",
        "display_sender": f"{visual['brand_name']} 보안팀",
        "synthetic_sender_address": "security@aurio.test",
        "subject_text": mirrored_red["subject_text"],
        "greeting_text": mirrored_red["greeting_text"],
        "body_text": mirrored_red["body_text"],
        "action_label": mirrored_red["action_label"],
        "page_title": "계정 활동 확인",
        "page_body": "공식 앱의 계정 활동 화면입니다.",
        "page_action_label": "활동 확인",
        "urgency_level": mirrored_red["urgency_level"],
        "claimed_event_type": mirrored_red["claimed_event_type"],
        "claimed_event_ref": mirrored_red["claimed_event_ref"],
        "destination_identifier": destinations[variant],
        "difficulty": "official",
        "tactics": {
            "tactic_id": f"platform-{variant}",
            "sender_auth_result": "PASS",
            "signature_mode": "valid",
            "ingress_mode": ingress_mode,
            "layout_variant": "shared",
        },
    }


def materialize_scenario(
    structured: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    """Trusted conversion from validated variables to telemetry and fixed HTML."""
    tactics = structured["tactics"]
    signature_mode = tactics["signature_mode"]
    scenario_type = structured["scenario_type"]
    if scenario_type == "forged_security_alert" and signature_mode == "valid":
        raise ValueError("위조 시나리오는 유효한 플랫폼 서명을 발급받을 수 없습니다.")
    if scenario_type == "official_security_alert" and signature_mode != "valid":
        raise ValueError("공식 시나리오는 유효한 플랫폼 서명이 필요합니다.")
    if signature_mode == "valid":
        signature = f"{registry['signature_prefix']}{structured['claimed_event_ref']}"
    elif signature_mode == "invalid":
        signature = f"INVALID-{structured['claimed_event_ref']}"
    else:
        signature = None

    ingress_mode = tactics["ingress_mode"]
    if ingress_mode == "internal_service":
        ingress = "internal_service"
    elif ingress_mode == "authorized_relay":
        ingress = f"relay:{registry['authorized_relays'][0]}"
    else:
        if scenario_type == "official_security_alert":
            ingress = "external:new-relay.aurio-mail.test"
        else:
            sender_host = structured["synthetic_sender_address"].rsplit("@", 1)[1]
            ingress = f"external:{sender_host}"

    link = destination_url(str(structured["destination_identifier"]))
    parsed = urlparse(link)
    page_html = None
    if scenario_type == "forged_security_alert":
        page_html = render_login(structured)
    return {
        "channel": "email",
        "display_sender_name": structured["display_sender"],
        "auth_sender_address": structured["synthetic_sender_address"],
        "sender_auth_result": tactics["sender_auth_result"],
        "signature_token": signature,
        "claimed_event_type": structured["claimed_event_type"],
        "claimed_event_ref": structured["claimed_event_ref"],
        "link_destination": link,
        "ingress_channel": ingress,
        "subject_text": structured["subject_text"],
        "body_text": structured["body_text"],
        "rendered_html": render_email(structured),
        "page_url_path": parsed.path,
        "page_html": page_html,
    }
