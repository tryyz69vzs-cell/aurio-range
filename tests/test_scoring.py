"""Risk boundaries, Hard signal construction, independent metrics, and scoring."""

from __future__ import annotations

import json

import pytest

from brandkit.renderer import load_registry
from engine.blue_agent import pre_delivery_assess
from engine.db import BlueRepo, JudgeRepo, create_match_database, table_columns
from engine.detection_params import (
    BAND_THRESHOLDS,
    SIGNAL_WEIGHTS,
    classify_risk,
    get_params,
)
from engine.judge import evaluate
from engine.observation import BlueObservation


@pytest.mark.parametrize(
    ("strictness", "value", "expected"),
    [
        ("balanced", 29, "LOW"),
        ("balanced", 30, "MEDIUM"),
        ("balanced", 69, "MEDIUM"),
        ("balanced", 70, "HIGH"),
        ("strict", 19, "LOW"),
        ("strict", 20, "MEDIUM"),
        ("strict", 54, "MEDIUM"),
        ("strict", 55, "HIGH"),
        ("permissive", 39, "LOW"),
        ("permissive", 40, "MEDIUM"),
        ("permissive", 89, "MEDIUM"),
        ("permissive", 90, "HIGH"),
    ],
)
def test_band_boundaries(strictness, value, expected):
    assert classify_risk(value, strictness)[0] == expected


def test_no_single_signal_reaches_high_and_urgency_alone_is_low():
    single_values = [
        max(options.values()) for options in SIGNAL_WEIGHTS.values()
    ]
    for strictness in BAND_THRESHOLDS:
        for value in single_values:
            assert classify_risk(value, strictness)[0] != "HIGH"
        assert classify_risk(10, strictness)[0] == "LOW"


def _risk_fixture():
    connection = create_match_database()
    connection.execute(
        """INSERT INTO matches(
             id,seed,difficulty_mix,strictness,started_at,status
           ) VALUES(1,'1','hard','balanced','sim','running')"""
    )
    connection.execute(
        """INSERT INTO accounts(
             id,match_id,username,email,profile,scenario_key,
             mfa_enabled,status,session_state
           ) VALUES(1,1,'민서','cautious@users.aurio.test','cautious',
                    'cautious-hard',1,'active','anomalous')"""
    )
    connection.execute(
        """INSERT INTO official_events(
             match_id,account_id,event_ref,event_type,description,created_step
           ) VALUES(1,1,'AR-H-0001','suspicious_login','synthetic',0)"""
    )
    return connection, BlueRepo(connection, load_registry())


def _hard_observation(**overrides):
    values = {
        "message_id": 1,
        "account_id": 1,
        "channel": "email",
        "display_sender_name": "Aurio 보안팀",
        "auth_sender_address": "security@aurio.test",
        "sender_auth_result": "PASS",
        "signature_token": "AURIO-SIG-AR-H-0001",
        "claimed_event_type": "suspicious_login",
        "claimed_event_ref": "AR-H-0001",
        "link_destination": "https://app.aurio.test/security/alerts",
        "ingress_channel": "relay:relay.aurio-mail.test",
        "body_text": "낯선 환경의 로그인 시도가 감지되었습니다. 즉시 활동을 확인해 주세요.",
        "created_step": 1,
        "account_status_snapshot": "active",
        "account_session_snapshot": "anomalous",
    }
    values.update(overrides)
    return BlueObservation(**values)


def test_official_and_hard_forged_scores_have_only_three_core_differences():
    connection, repo = _risk_fixture()
    try:
        official = pre_delivery_assess(
            _hard_observation(), repo, get_params("balanced")
        )
        forged = pre_delivery_assess(
            _hard_observation(
                message_id=2,
                sender_auth_result="SOFTFAIL",
                signature_token=None,
                link_destination="https://aurio-help.test/security/check",
            ),
            repo,
            get_params("balanced"),
        )
        assert official.risk_total == 10
        assert forged.risk_total == 70
        different = {
            key
            for key in official.signals
            if official.signals[key]["score"] != forged.signals[key]["score"]
        }
        assert different == {
            "sender_auth",
            "signature_validity",
            "destination_ownership",
        }
        assert official.signals["official_event_record"]["score"] == 0
        assert forged.signals["official_event_record"]["score"] == 0
        assert official.signals["ingress_channel"]["score"] == 0
        assert forged.signals["ingress_channel"]["score"] == 0
    finally:
        connection.close()


def _manual_case(
    origin: str,
    prediction: str,
    actions: tuple[str, ...] = (),
    capture: bool = False,
    contained: bool = False,
    submission_target: str = "internal_capture",
    status_at_submit: str = "active",
    session_at_submit: str = "normal",
    post_response: str | None = None,
):
    connection = create_match_database()
    connection.execute(
        """INSERT INTO matches(
             id,seed,difficulty_mix,strictness,started_at,status
           ) VALUES(1,'1','hard','balanced','sim','closed')"""
    )
    status = "recovery_pending" if contained else "active"
    session = "revoked" if contained else "normal"
    connection.execute(
        """INSERT INTO accounts(
             id,match_id,username,email,profile,scenario_key,
             mfa_enabled,status,session_state
           ) VALUES(1,1,'민서','cautious@users.aurio.test','cautious',
                    'cautious-hard',1,?,?)""",
        (status, session),
    )
    delivery = {
        "allow": "delivered", "warn": "warned", "quarantine": "quarantined"
    }[prediction]
    connection.execute(
        """INSERT INTO messages(
             id,match_id,account_id,channel,display_sender_name,
             auth_sender_address,sender_auth_result,signature_token,
             claimed_event_type,claimed_event_ref,link_destination,
             ingress_channel,subject_text,body_text,rendered_html,
             created_step,delivery_status
           ) VALUES(1,1,1,'email','Aurio 보안팀','security@aurio.test',
                    'PASS',NULL,'suspicious_login','REF-1',
                    'https://app.aurio.test/security/alerts','internal_service',
                    'subject','body','html',0,?)""",
        (delivery,),
    )
    if post_response is None:
        post_response = "contained" if contained else "observed"
    connection.execute(
        """INSERT INTO blue_assessments(
             message_id,risk_total,band,pre_delivery_action,signals_json,
             assessment_step,response_step,post_action_response
           ) VALUES(1,10,'LOW',?,'{}',2,8,?)""",
        (prediction, post_response),
    )
    forged = int(origin == "forged")
    connection.execute(
        """INSERT INTO scenario_ground_truth(
             message_id,match_id,true_origin,true_difficulty,generator,
             red_tactic_id,scenario_goal,is_forged,expected_classification
           ) VALUES(1,1,?,'hard',?,'tactic','goal',?,?)""",
        (
            origin, "red" if forged else "platform", forged,
            "flag_expected" if forged else "allow_expected",
        ),
    )
    steps = 3
    for action in actions:
        connection.execute(
            """INSERT INTO user_actions(
                 match_id,account_id,message_id,profile,action,
                 from_state,to_state,step_index
               ) VALUES(1,1,1,'cautious',?,'X','Y',?)""",
            (action, steps),
        )
        steps += 1
    if forged:
        connection.execute(
            """INSERT INTO phish_pages(
                 match_id,message_id,url_path,html,created_step,blocked,blocked_step
               ) VALUES(1,1,'/check','html',0,?,?)""",
            (int(contained), 8 if contained else None),
        )
    if capture:
        to_phish = int(submission_target == "internal_capture")
        exposure = to_phish
        takeover = int(
            exposure
            and status_at_submit == "active"
            and session_at_submit not in {"revoked", "stepup_required"}
        )
        connection.execute(
            """INSERT INTO capture_events(
                 match_id,message_id,account_id,submission_target,
                 account_status_at_submit,session_state_at_submit,
                 attempted_username,attempted_password,
                 valid_synthetic_credentials_submitted,submitted_to_phish,
                 credential_exposure,takeover_success,step_index
               ) VALUES(1,1,1,?,?,?,1,1,1,?,?,?,5)""",
            (
                submission_target, status_at_submit, session_at_submit,
                to_phish, exposure, takeover,
            ),
        )
    events = [
        (0, "MESSAGE_CREATED"),
        (1, "MESSAGE_RECEIVED"),
        (2, "BLUE_PRE_ASSESS"),
    ]
    for step, action in enumerate(actions, start=3):
        events.append((step, action))
    events.append((steps, "BLUE_POST_RESPONSE"))
    events.append((steps + 1, "MATCH_CLOSED"))
    for step, event_type in events:
        connection.execute(
            """INSERT INTO events(
                 match_id,step_index,event_type,message_id,account_id,
                 payload_json,wall_ms
               ) VALUES(1,?,?,1,1,'{}',0)""",
            (step, event_type),
        )
    summary = evaluate(JudgeRepo(connection), 1)
    evaluation = dict(
        connection.execute("SELECT * FROM judge_evaluations").fetchone()
    )
    return connection, summary, evaluation


@pytest.mark.parametrize(
    ("origin", "prediction", "actions", "capture", "contained", "expected"),
    [
        ("official", "quarantine", (), False, False, {"false_positive": 1}),
        ("official", "warn", (), False, False, {"friction": 1, "false_positive": 0}),
        ("forged", "allow", (), False, False, {"false_negative": 1}),
        ("forged", "warn", ("WARN_IGNORED", "USER_CLICK"), False, False, {"warning_escape": 1, "user_harm_click": 1}),
        ("forged", "allow", ("USER_CLICK",), False, False, {"user_harm_click": 1, "user_harm_submit": 0}),
        ("forged", "allow", ("USER_CLICK", "USER_SUBMIT"), True, False, {"user_harm_submit": 1, "credential_exposure": 1, "takeover_success": 1}),
        ("forged", "warn", ("USER_CLICK", "USER_SUBMIT"), True, True, {"containment_success": 1}),
        ("forged", "allow", ("USER_REPORT",), False, False, {"user_saved": 1, "false_negative": 1}),
    ],
)
def test_metrics_are_independent(
    origin, prediction, actions, capture, contained, expected
):
    connection, _, evaluation = _manual_case(
        origin, prediction, actions, capture, contained
    )
    try:
        for key, value in expected.items():
            assert evaluation[key] == value
    finally:
        connection.close()


def test_blue_table_has_no_correct_column_and_latency_not_scored():
    connection, summary, evaluation = _manual_case(
        "forged",
        "warn",
        ("USER_CLICK", "USER_SUBMIT"),
        True,
        True,
    )
    try:
        blue_columns = {
            row["name"] for row in table_columns(connection, "blue_assessments")
        }
        judge_columns = {
            row["name"] for row in table_columns(connection, "judge_evaluations")
        }
        assert "correct" not in blue_columns
        assert "correct" in judge_columns
        assert summary["detail"]["latency_scoring"] == "excluded_in_mvp"
        assert evaluation["detection_latency_steps"] == 1
        assert evaluation["containment_latency_steps"] >= 1
    finally:
        connection.close()
