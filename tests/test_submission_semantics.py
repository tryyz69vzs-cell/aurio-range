"""Submission-target semantics, exposure vs takeover, and scenario isolation.

These cover the state-transition redesign: an official-destination submission is
ordinary platform use and must not trigger containment, while exposure is
recorded from the submit-time snapshot independently of takeover.
"""

from __future__ import annotations

import pytest

from brandkit.renderer import load_registry
from engine.blue_agent import post_action_response, pre_delivery_assess
from engine.db import BlueRepo, create_match_database
from engine.detection_params import get_params
from engine.match import run_match
from engine.platform_state import classify_submission_target


PROFILES = ["cautious", "average", "careless"]
METRIC_KEYS = (
    "credential_exposure",
    "takeover_success",
    "exposure_prevented_by_prior_lock",
    "containment_success",
    "official_submission",
    "forged_submission",
    "overreaction",
    "false_negative",
    "false_positive",
    "friction",
    "warning_escape",
    "user_harm_click",
    "user_harm_submit",
    "correct",
)


def _account_fixture(status: str = "active", session: str = "normal"):
    connection = create_match_database()
    connection.execute(
        """INSERT INTO matches(
             id,seed,difficulty_mix,strictness,started_at,status
           ) VALUES(1,'1','mixed','balanced','sim','running')"""
    )
    connection.execute(
        """INSERT INTO accounts(
             id,match_id,username,email,profile,scenario_key,
             mfa_enabled,status,session_state
           ) VALUES(1,1,'민서','cautious@users.aurio.test','cautious',
                    'cautious-easy',1,?,?)""",
        (status, session),
    )
    connection.execute(
        """INSERT INTO messages(
             id,match_id,account_id,channel,display_sender_name,
             auth_sender_address,sender_auth_result,signature_token,
             claimed_event_type,claimed_event_ref,link_destination,
             ingress_channel,subject_text,body_text,rendered_html,created_step
           ) VALUES(1,1,1,'email','Aurio 보안팀','security@aurio.test','PASS',
                    NULL,'suspicious_login','REF-1',
                    'https://app.aurio.test/security/alerts','internal_service',
                    's','b','h',0)"""
    )
    connection.execute(
        """INSERT INTO blue_assessments(
             message_id,risk_total,band,pre_delivery_action,signals_json,
             assessment_step
           ) VALUES(1,10,'LOW','allow','{}',2)"""
    )
    return connection, BlueRepo(connection, load_registry())


def _status(connection):
    row = connection.execute(
        "SELECT status, session_state FROM accounts WHERE id=1"
    ).fetchone()
    return row["status"], row["session_state"]


def test_official_destination_submit_never_changes_account_state():
    connection, repo = _account_fixture()
    try:
        outcome = post_action_response(
            {
                "event_type": "USER_SUBMIT",
                "message_id": 1,
                "account_id": 1,
                "step_index": 9,
                "destination_class": "official_owned",
            },
            repo,
            get_params("balanced"),
        )
        assert outcome.response == "no_action_official_destination"
        assert outcome.page_blocked is False
        assert _status(connection) == ("active", "normal")
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("destination_class", "expected_status", "expected_session"),
    [
        ("internal_capture", "recovery_pending", "revoked"),
        ("synthetic_unowned", "recovery_pending", "revoked"),
    ],
)
def test_forged_destination_submit_triggers_containment(
    destination_class, expected_status, expected_session
):
    connection, repo = _account_fixture()
    try:
        outcome = post_action_response(
            {
                "event_type": "USER_SUBMIT",
                "message_id": 1,
                "account_id": 1,
                "step_index": 9,
                "destination_class": destination_class,
            },
            repo,
            get_params("balanced"),
        )
        assert outcome.response == "contained"
        assert _status(connection) == (expected_status, expected_session)
    finally:
        connection.close()


def test_official_destination_click_does_not_force_stepup():
    connection, repo = _account_fixture()
    try:
        post_action_response(
            {
                "event_type": "USER_CLICK",
                "message_id": 1,
                "account_id": 1,
                "step_index": 9,
                "destination_class": "official_owned",
            },
            repo,
            get_params("balanced"),
        )
        assert _status(connection) == ("active", "normal")
    finally:
        connection.close()


def test_post_response_rejects_unknown_destination_class():
    connection, repo = _account_fixture()
    try:
        with pytest.raises(ValueError):
            post_action_response(
                {
                    "event_type": "USER_SUBMIT",
                    "message_id": 1,
                    "account_id": 1,
                    "step_index": 9,
                    "destination_class": "somewhere_else",
                },
                repo,
                get_params("balanced"),
            )
    finally:
        connection.close()


def test_submission_target_uses_only_observable_telemetry():
    connection, _ = _account_fixture()
    registry = load_registry()
    try:
        assert classify_submission_target(connection, registry, 1) == "official_owned"
        connection.execute(
            "UPDATE messages SET link_destination=? WHERE id=1",
            ("https://aurio-help.test/security/check",),
        )
        assert (
            classify_submission_target(connection, registry, 1) == "synthetic_unowned"
        )
        connection.execute(
            """INSERT INTO phish_pages(
                 match_id,message_id,url_path,html,created_step,blocked
               ) VALUES(1,1,'/security/check','h',0,0)"""
        )
        assert (
            classify_submission_target(connection, registry, 1) == "internal_capture"
        )
        # An unregistered path on a registered host is still not owned.
        connection.execute(
            "UPDATE messages SET link_destination=? WHERE id=1",
            ("https://app.aurio.test/security/review",),
        )
        assert (
            classify_submission_target(connection, registry, 1) == "internal_capture"
        )
    finally:
        connection.close()


def test_seed_1088_official_submissions_do_not_lock_accounts():
    """Regression: official submits used to poison every later scenario."""
    result = run_match("mixed", "permissive", PROFILES, 1088)
    messages = {row["id"]: row for row in result["messages"]}
    captures = result["capture_events"]
    assert captures, "이 시드는 제출 행동을 포함해야 합니다."

    official_owned = [
        row for row in captures if row["submission_target"] == "official_owned"
    ]
    assert official_owned, "공식 목적지 제출이 최소 한 건 있어야 합니다."
    for row in official_owned:
        message = messages[row["message_id"]]
        assert message["post_action_response"] == "no_action_official_destination"
        assert row["credential_exposure"] == 0
        assert row["takeover_success"] == 0

    # Every submit snapshot in this seed was taken on a still-active account:
    # no earlier scenario leaked its containment state forward.
    for row in captures:
        assert row["account_status_at_submit"] == "active"


def test_seed_1010_splits_exposure_from_takeover():
    """Exposure is state-independent; takeover requires an active account."""
    result = run_match("mixed", "permissive", PROFILES, 1010)
    evaluations = {row["message_id"]: row for row in result["judge_evaluations"]}
    captures = {row["message_id"]: row for row in result["capture_events"]}

    exposed = [
        message_id
        for message_id, row in evaluations.items()
        if row["credential_exposure"]
    ]
    assert len(exposed) == 2

    took_over = [mid for mid in exposed if evaluations[mid]["takeover_success"]]
    prevented = [
        mid
        for mid in exposed
        if evaluations[mid]["exposure_prevented_by_prior_lock"]
    ]
    assert len(took_over) == 1
    assert len(prevented) == 1
    assert set(took_over).isdisjoint(prevented)

    # Submitted while the account was still active -> takeover.
    assert captures[took_over[0]]["account_status_at_submit"] == "active"
    # Submitted after this scenario's own defense had already fired -> exposure
    # is still 1, takeover is 0.
    assert captures[prevented[0]]["account_status_at_submit"] != "active"
    assert captures[prevented[0]]["credential_exposure"] == 1
    assert captures[prevented[0]]["takeover_success"] == 0


def test_official_and_forged_submissions_are_never_mixed():
    for seed in (1010, 1088, 1005):
        result = run_match("mixed", "permissive", PROFILES, seed)
        for row in result["judge_evaluations"]:
            assert not (row["official_submission"] and row["forged_submission"])
        for row in result["capture_events"]:
            official = row["submission_target"] == "official_owned"
            if official:
                assert row["credential_exposure"] == 0
                assert row["submitted_to_phish"] == 0
            if row["credential_exposure"]:
                assert row["submission_target"] == "internal_capture"


def _scenario_metrics(result):
    messages = {row["id"]: row for row in result["messages"]}
    return {
        (
            messages[row["message_id"]]["scenario_key"],
            row["ground_truth"],
        ): tuple(row[key] for key in METRIC_KEYS)
        for row in result["judge_evaluations"]
    }


@pytest.mark.parametrize("seed", [1010, 1088, 1005, 1042])
def test_scenario_results_do_not_depend_on_execution_order(seed):
    """Running a difficulty alone must match its slice of the mixed run."""
    for strictness in ("permissive", "balanced", "strict"):
        mixed = _scenario_metrics(run_match("mixed", strictness, PROFILES, seed))
        for level in ("easy", "medium", "hard"):
            solo = _scenario_metrics(run_match(level, strictness, PROFILES, seed))
            assert solo, "각 난이도는 최소 하나의 시나리오를 만들어야 합니다."
            for key, value in solo.items():
                assert mixed[key] == value


def test_each_scenario_uses_a_fresh_account():
    result = run_match("mixed", "permissive", PROFILES, 1010)
    keys = [row["scenario_key"] for row in result["messages"]]
    assert len(set(keys)) == 9
    accounts_per_scenario = {}
    for row in result["messages"]:
        accounts_per_scenario.setdefault(row["scenario_key"], set()).add(
            row["account_id"]
        )
    # One account per scenario, shared by that scenario's official/forged pair.
    assert all(len(value) == 1 for value in accounts_per_scenario.values())
    assert len({next(iter(v)) for v in accounts_per_scenario.values()}) == 9


def test_blue_still_cannot_see_origin_in_pre_assessment():
    connection, repo = _account_fixture()
    try:
        from engine.observation import BlueObservation

        observation = BlueObservation(
            message_id=1,
            account_id=1,
            channel="email",
            display_sender_name="Aurio 보안팀",
            auth_sender_address="security@aurio.test",
            sender_auth_result="PASS",
            signature_token="AURIO-SIG-REF-1",
            claimed_event_type="suspicious_login",
            claimed_event_ref="REF-1",
            link_destination="https://app.aurio.test/security/alerts",
            ingress_channel="internal_service",
            body_text="확인해 주세요.",
            created_step=1,
            account_status_snapshot="active",
            account_session_snapshot="normal",
        )
        assessment = pre_delivery_assess(observation, repo, get_params("balanced"))
        assert assessment.pre_delivery_action == "allow"
        assert "submission_target" not in assessment.signals
    finally:
        connection.close()
