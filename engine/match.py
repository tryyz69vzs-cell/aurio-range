"""Synchronous, isolated, event-queue match orchestration."""

from __future__ import annotations

import json
import random
from dataclasses import asdict, replace
from typing import Any, Mapping

from brandkit.renderer import load_registry, load_visual, static_login_preview
from engine.blue_agent import post_action_response, pre_delivery_assess
from engine.db import BlueRepo, JudgeRepo, create_match_database
from engine.detection_params import get_params
from engine.event_queue import EventQueue
from engine.judge import evaluate
from engine.observation import BlueObservation
from engine.platform_state import (
    build_official_scenario,
    create_accounts,
    create_official_event,
    materialize_scenario,
    official_event_exists,
)
from engine.red_agent import build_scenario
from engine.user_agent import run_state_machine
from safety.guard import arena_gate, validate_red_output


VALID_DIFFICULTIES = {"easy", "medium", "hard", "mixed"}
VALID_PROFILES = {"cautious", "average", "careless"}


def _insert_message(
    connection,
    queue: EventQueue,
    match_id: int,
    account_id: int,
    structured: Mapping[str, Any],
    rendered: Mapping[str, Any],
    origin: str,
) -> int:
    created_step = queue.current_step + 1
    cursor = connection.execute(
        """INSERT INTO messages(
             match_id, account_id, channel, display_sender_name,
             auth_sender_address, sender_auth_result, signature_token,
             claimed_event_type, claimed_event_ref, link_destination,
             ingress_channel, subject_text, body_text, rendered_html,
             created_step
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            match_id, account_id, rendered["channel"],
            rendered["display_sender_name"], rendered["auth_sender_address"],
            rendered["sender_auth_result"], rendered["signature_token"],
            rendered["claimed_event_type"], rendered["claimed_event_ref"],
            rendered["link_destination"], rendered["ingress_channel"],
            rendered["subject_text"], rendered["body_text"],
            rendered["rendered_html"], created_step,
        ),
    )
    message_id = int(cursor.lastrowid)
    queue.record(
        "MESSAGE_CREATED", message_id, account_id,
        {"generator": "platform" if origin == "official" else "red"},
    )
    if origin == "forged":
        connection.execute(
            """INSERT INTO phish_pages(
                 match_id, message_id, url_path, html, created_step, blocked
               ) VALUES(?,?,?,?,?,0)""",
            (
                match_id, message_id, rendered["page_url_path"],
                rendered["page_html"], created_step,
            ),
        )
    connection.execute(
        """INSERT INTO scenario_ground_truth(
             message_id, match_id, true_origin, true_difficulty,
             generator, red_tactic_id, scenario_goal, is_forged,
             expected_classification
           ) VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            message_id, match_id, origin,
            structured["difficulty"],
            "platform" if origin == "official" else "red",
            None if origin == "official" else structured["tactics"]["tactic_id"],
            "deliver legitimate alert" if origin == "official"
            else "measure defensive detection and user response",
            1 if origin == "forged" else 0,
            "allow_expected" if origin == "official" else "flag_expected",
        ),
    )
    return message_id


def _observation(connection, message_id: int) -> BlueObservation:
    row = connection.execute(
        """SELECT m.*, a.status, a.session_state
           FROM messages AS m JOIN accounts AS a ON a.id=m.account_id
           WHERE m.id=?""",
        (message_id,),
    ).fetchone()
    return BlueObservation(
        message_id=row["id"],
        account_id=row["account_id"],
        channel=row["channel"],
        display_sender_name=row["display_sender_name"],
        auth_sender_address=row["auth_sender_address"],
        sender_auth_result=row["sender_auth_result"],
        signature_token=row["signature_token"],
        claimed_event_type=row["claimed_event_type"],
        claimed_event_ref=row["claimed_event_ref"],
        link_destination=row["link_destination"],
        ingress_channel=row["ingress_channel"],
        body_text=row["body_text"],
        created_step=row["created_step"],
        account_status_snapshot=row["status"],
        account_session_snapshot=row["session_state"],
    )


def _record_user_journey(
    connection,
    queue: EventQueue,
    match_id: int,
    message_id: int,
    account,
    urgency_level: str,
    warned: bool,
    rng: random.Random,
    is_phish_page: bool,
) -> str:
    event_ref = connection.execute(
        "SELECT claimed_event_ref FROM messages WHERE id=?", (message_id,)
    ).fetchone()["claimed_event_ref"]
    journey = run_state_machine(
        account["profile"],
        urgency_level,
        warned,
        lambda: official_event_exists(connection, account["id"], event_ref),
        rng,
    )
    decisive = "USER_IGNORE"
    for transition in journey.transitions:
        event = queue.record(
            transition.action,
            message_id,
            account["id"],
            {
                "from_state": transition.from_state.value,
                "to_state": transition.to_state.value,
            },
        )
        connection.execute(
            """INSERT INTO user_actions(
                 match_id, account_id, message_id, profile, action,
                 from_state, to_state, step_index
               ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                match_id, account["id"], message_id, account["profile"],
                transition.action, transition.from_state.value,
                transition.to_state.value, event.step_index,
            ),
        )
        if transition.action in {"USER_CLICK", "USER_SUBMIT", "USER_REPORT"}:
            decisive = transition.action
        elif transition.action == "USER_ABORT" and decisive == "USER_IGNORE":
            decisive = "USER_ABORT"

        if transition.action == "USER_SUBMIT" and is_phish_page:
            attempted_username = 1
            attempted_password = 1
            account_status = connection.execute(
                "SELECT status FROM accounts WHERE id=?", (account["id"],)
            ).fetchone()["status"]
            valid_submission = int(
                attempted_username
                and attempted_password
                and account_status == "active"
                and transition.to_state.value == "SUBMITTED"
            )
            connection.execute(
                """INSERT INTO capture_events(
                     match_id, message_id, account_id, attempted_username,
                     attempted_password, valid_synthetic_credentials_submitted,
                     submitted_to_phish, step_index
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    match_id, message_id, account["id"],
                    attempted_username, attempted_password,
                    valid_submission, 1, event.step_index,
                ),
            )
    return decisive


def _process_message(
    connection,
    queue: EventQueue,
    blue_repo: BlueRepo,
    params,
    match_id: int,
    message_id: int,
    account,
    structured: Mapping[str, Any],
    rng: random.Random,
    is_phish_page: bool,
) -> None:
    queue.record("MESSAGE_RECEIVED", message_id, account["id"])
    assessment = pre_delivery_assess(
        _observation(connection, message_id), blue_repo, params
    )
    assessment_event = queue.record(
        "BLUE_PRE_ASSESS",
        message_id,
        account["id"],
        {"risk_total": assessment.risk_total, "band": assessment.band},
    )
    assessment = replace(assessment, assessment_step=assessment_event.step_index)
    blue_repo.save_assessment(
        message_id,
        assessment.risk_total,
        assessment.band,
        assessment.pre_delivery_action,
        assessment.signals,
        assessment.assessment_step,
    )

    if assessment.pre_delivery_action == "quarantine":
        blue_repo.set_delivery_status(message_id, "quarantined")
        blue_repo.commit()
        return

    delivery_status = (
        "warned" if assessment.pre_delivery_action == "warn" else "delivered"
    )
    blue_repo.set_delivery_status(message_id, delivery_status)
    queue.record(
        "MESSAGE_DELIVERED", message_id, account["id"],
        {"warning_banner": assessment.pre_delivery_action == "warn"},
    )
    decisive = _record_user_journey(
        connection, queue, match_id, message_id, account,
        structured["urgency_level"],
        assessment.pre_delivery_action == "warn",
        rng, is_phish_page,
    )
    response_event = queue.record(
        "BLUE_POST_RESPONSE", message_id, account["id"],
        {"trigger_event": decisive},
    )
    post_action_response(
        {
            "event_type": decisive,
            "message_id": message_id,
            "account_id": account["id"],
            "step_index": response_event.step_index,
        },
        blue_repo,
        params,
    )


def _difficulty_list(difficulty: str) -> list[str]:
    return ["easy", "medium", "hard"] if difficulty == "mixed" else [difficulty]


def _row_dicts(rows) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _build_result(connection, match_id: int, summary: dict[str, Any], seed: int):
    messages = _row_dicts(
        connection.execute(
            """SELECT m.id, m.account_id, a.profile, m.display_sender_name,
                      m.auth_sender_address, m.subject_text, m.body_text,
                      m.rendered_html, m.delivery_status, b.risk_total, b.band,
                      b.pre_delivery_action, b.post_action_response,
                      b.signals_json
               FROM messages AS m
               JOIN accounts AS a ON a.id=m.account_id
               JOIN blue_assessments AS b ON b.message_id=m.id
               WHERE m.match_id=? ORDER BY m.id""",
            (match_id,),
        )
    )
    for message in messages:
        message["signals"] = json.loads(message.pop("signals_json"))

    evaluations = _row_dicts(
        connection.execute(
            """SELECT j.*, g.true_difficulty, a.profile
               FROM judge_evaluations AS j
               JOIN scenario_ground_truth AS g ON g.message_id=j.message_id
               JOIN messages AS m ON m.id=j.message_id
               JOIN accounts AS a ON a.id=m.account_id
               WHERE g.match_id=? ORDER BY j.message_id""",
            (match_id,),
        )
    )
    truth_by_id = {
        row["message_id"]: dict(row)
        for row in connection.execute(
            "SELECT * FROM scenario_ground_truth WHERE match_id=?", (match_id,)
        )
    }
    action_rows = _row_dicts(
        connection.execute(
            """SELECT * FROM user_actions
               WHERE match_id=? ORDER BY step_index""", (match_id,)
        )
    )
    actions_by_message: dict[int, set[str]] = {}
    for row in action_rows:
        actions_by_message.setdefault(row["message_id"], set()).add(row["action"])

    difficulty_metrics = []
    for level in ("easy", "medium", "hard"):
        ids = [
            mid for mid, truth in truth_by_id.items()
            if truth["is_forged"] and truth["true_difficulty"] == level
        ]
        selected = [m for m in messages if m["id"] in ids]
        difficulty_metrics.append(
            {
                "difficulty": level.title(),
                "delivered": sum(m["delivery_status"] == "delivered" for m in selected),
                "warned": sum(m["delivery_status"] == "warned" for m in selected),
                "quarantined": sum(
                    m["delivery_status"] == "quarantined" for m in selected
                ),
                "harm_click": sum(
                    "USER_CLICK" in actions_by_message.get(mid, set()) for mid in ids
                ),
                "harm_submit": sum(
                    "USER_SUBMIT" in actions_by_message.get(mid, set()) for mid in ids
                ),
            }
        )

    profile_metrics = []
    for profile in ("cautious", "average", "careless"):
        forged_ids = [
            m["id"] for m in messages
            if m["profile"] == profile and truth_by_id[m["id"]]["is_forged"]
        ]
        ids = [
            mid for mid in forged_ids
            if next(m for m in messages if m["id"] == mid)[
                "pre_delivery_action"
            ] != "quarantine"
        ]
        n = len(ids)
        counts = {
            "click_count": sum(
                "USER_CLICK" in actions_by_message.get(mid, set()) for mid in ids
            ),
            "submit_count": sum(
                "USER_SUBMIT" in actions_by_message.get(mid, set()) for mid in ids
            ),
            "report_count": sum(
                "USER_REPORT" in actions_by_message.get(mid, set()) for mid in ids
            ),
            "verify_count": sum(
                "USER_VERIFY" in actions_by_message.get(mid, set()) for mid in ids
            ),
        }
        warned_ids = [mid for mid in ids if next(
            m for m in messages if m["id"] == mid
        )["pre_delivery_action"] == "warn"]
        warning_escape_count = sum(
            "WARN_IGNORED" in actions_by_message.get(mid, set())
            and "USER_CLICK" in actions_by_message.get(mid, set())
            for mid in warned_ids
        )
        profile_metrics.append(
            {
                "profile": profile,
                **counts,
                "message_count": n,
                "forged_count": len(forged_ids),
                "warned_count": len(warned_ids),
                "warning_escape_count": warning_escape_count,
                "click_rate": counts["click_count"] / n if n else 0.0,
                "submit_rate": (
                    counts["submit_count"] / counts["click_count"]
                    if counts["click_count"] else 0.0
                ),
                "report_rate": counts["report_count"] / n if n else 0.0,
                "verify_rate": counts["verify_count"] / n if n else 0.0,
                "warning_escape_rate": (
                    warning_escape_count / len(warned_ids) if warned_ids else 0.0
                ),
            }
        )

    hard_pairs = []
    hard_forged = [
        mid for mid, truth in truth_by_id.items()
        if truth["is_forged"] and truth["true_difficulty"] == "hard"
    ]
    for forged_id in hard_forged:
        forged_message = next(m for m in messages if m["id"] == forged_id)
        ref = connection.execute(
            "SELECT account_id, claimed_event_ref FROM messages WHERE id=?",
            (forged_id,),
        ).fetchone()
        official = connection.execute(
            """SELECT m.id FROM messages AS m
               JOIN scenario_ground_truth AS g ON g.message_id=m.id
               WHERE m.account_id=? AND m.claimed_event_ref=?
                 AND g.true_origin='official' LIMIT 1""",
            (ref["account_id"], ref["claimed_event_ref"]),
        ).fetchone()
        if official:
            official_message = next(m for m in messages if m["id"] == official["id"])
            hard_pairs.append(
                {"official": official_message, "forged": forged_message}
            )

    events = _row_dicts(
        connection.execute(
            """SELECT step_index, event_type, message_id, account_id, payload_json
               FROM events WHERE match_id=? ORDER BY step_index""",
            (match_id,),
        )
    )
    for event in events:
        event["payload"] = json.loads(event.pop("payload_json"))
    previews = _row_dicts(
        connection.execute(
            """SELECT p.message_id, p.html, p.blocked, p.blocked_step
               FROM phish_pages AS p WHERE p.match_id=? ORDER BY p.message_id""",
            (match_id,),
        )
    )
    for preview in previews:
        preview["static_html"] = static_login_preview(preview.pop("html"))
    safety_events = _row_dicts(
        connection.execute(
            """SELECT kind, detail, ts FROM safety_events
               WHERE match_id=? ORDER BY id""",
            (match_id,),
        )
    )
    return {
        "match_id": match_id,
        "seed": seed,
        "scores": {
            "red": summary["red_score"],
            "blue": summary["blue_score"],
        },
        "metrics": {
            key: value for key, value in summary.items()
            if key not in {"red_score", "blue_score", "detail"}
        },
        "score_detail": summary["detail"],
        "difficulty_metrics": difficulty_metrics,
        "profile_metrics": profile_metrics,
        "signal_comparison": hard_pairs,
        "events": events,
        "messages": messages,
        "judge_evaluations": evaluations,
        "user_actions": action_rows,
        "previews": previews,
        "safety_events": safety_events,
    }


def run_match(
    difficulty: str = "mixed",
    strictness: str = "balanced",
    profiles: list[str] | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Run one complete game in a new private in-memory SQLite database."""
    difficulty = difficulty.lower()
    strictness = strictness.lower()
    chosen_profiles = profiles or ["cautious", "average", "careless"]
    if difficulty not in VALID_DIFFICULTIES:
        raise ValueError("난이도는 easy, medium, hard, mixed 중 하나여야 합니다.")
    if not chosen_profiles or not set(chosen_profiles) <= VALID_PROFILES:
        raise ValueError("하나 이상의 유효한 프로필이 필요합니다.")
    arena_gate()
    actual_seed = (
        random.SystemRandom().randrange(1, 2_147_483_647)
        if seed is None else int(seed)
    )
    rng = random.Random(actual_seed)
    registry = load_registry()
    visual = load_visual()
    params = get_params(strictness)
    connection = create_match_database()
    try:
        cursor = connection.execute(
            """INSERT INTO matches(
                 seed, difficulty_mix, strictness, started_at, status
               ) VALUES(?,?,?,?,?)""",
            (
                str(actual_seed), difficulty, strictness,
                f"simulated-seed-{actual_seed}", "running",
            ),
        )
        match_id = int(cursor.lastrowid)
        queue = EventQueue(connection, match_id)
        blue_repo = BlueRepo(connection, registry)
        accounts = create_accounts(connection, match_id, chosen_profiles)

        for account in accounts:
            for level in _difficulty_list(difficulty):
                placeholder = None
                if level == "hard":
                    hard_ref = f"AR-H-{account['id']:04d}"
                    event = queue.record(
                        "OFFICIAL_EVENT_CREATED", None, account["id"],
                        {"event_ref": hard_ref},
                    )
                    placeholder = create_official_event(
                        connection, match_id, account["id"], hard_ref,
                        "suspicious_login", "낯선 환경의 로그인 시도",
                        event.step_index,
                    )
                red_structured = build_scenario(
                    account, level, visual, placeholder
                )
                valid, reason = validate_red_output(red_structured)
                if not valid:
                    connection.execute(
                        """INSERT INTO safety_events(match_id, kind, detail, ts)
                           VALUES(?,?,?,?)""",
                        (
                            match_id, "discard", reason,
                            f"simulated-seed-{actual_seed}",
                        ),
                    )
                    continue

                if level != "hard":
                    official_ref = f"OF-{level[:1].upper()}-{account['id']:04d}"
                    event = queue.record(
                        "OFFICIAL_EVENT_CREATED", None, account["id"],
                        {"event_ref": official_ref},
                    )
                    create_official_event(
                        connection, match_id, account["id"], official_ref,
                        "suspicious_login", "낯선 환경의 로그인 시도",
                        event.step_index,
                    )
                else:
                    official_ref = red_structured["claimed_event_ref"]

                official_variant = (
                    "hard_triggered" if level == "hard"
                    else "infrastructure_drift"
                    if level == "medium" and account["profile"] == "careless"
                    else "route_drift" if level == "medium"
                    else "normal"
                )
                official_structured = build_official_scenario(
                    account, visual, red_structured, official_variant
                )
                official_structured["claimed_event_ref"] = official_ref

                official_rendered = materialize_scenario(
                    official_structured, registry
                )
                red_rendered = materialize_scenario(red_structured, registry)
                official_id = _insert_message(
                    connection, queue, match_id, account["id"],
                    official_structured, official_rendered, "official",
                )
                forged_id = _insert_message(
                    connection, queue, match_id, account["id"],
                    red_structured, red_rendered, "forged",
                )
                _process_message(
                    connection, queue, blue_repo, params, match_id,
                    official_id, account, official_structured, rng, False,
                )
                _process_message(
                    connection, queue, blue_repo, params, match_id,
                    forged_id, account, red_structured, rng, True,
                )

        queue.record("MATCH_CLOSED", None, None)
        connection.execute(
            """UPDATE matches SET ended_at=?, status='closed' WHERE id=?""",
            (f"simulated-seed-{actual_seed}", match_id),
        )
        summary = evaluate(JudgeRepo(connection), match_id)
        connection.commit()
        return _build_result(connection, match_id, summary, actual_seed)
    finally:
        connection.close()
