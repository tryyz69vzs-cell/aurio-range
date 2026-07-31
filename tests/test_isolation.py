"""Blue truth isolation and per-game database isolation tests."""

from __future__ import annotations

import inspect
from dataclasses import fields

import pytest

import engine.blue_agent as blue_agent
from brandkit.renderer import load_registry
from engine.blue_agent import pre_delivery_assess
from engine.db import BlueRepo, create_match_database
from engine.detection_params import get_params
from engine.observation import BlueObservation


FORBIDDEN_BLUE_IDENTIFIERS = (
    "scenario_ground_truth",
    "true_origin",
    "true_difficulty",
    "is_forged",
    "red_tactic_id",
    "GroundTruth",
    "JudgeRepo",
)


def test_blue_agent_source_has_no_truth_identifiers():
    source = inspect.getsource(blue_agent)
    for identifier in FORBIDDEN_BLUE_IDENTIFIERS:
        assert identifier not in source


def test_blue_observation_fields_match_exact_allowlist():
    allowed = {
        "message_id",
        "account_id",
        "channel",
        "display_sender_name",
        "auth_sender_address",
        "sender_auth_result",
        "signature_token",
        "claimed_event_type",
        "claimed_event_ref",
        "link_destination",
        "ingress_channel",
        "body_text",
        "created_step",
        "account_status_snapshot",
        "account_session_snapshot",
    }
    assert {field.name for field in fields(BlueObservation)} == allowed


def test_blue_repo_public_methods_never_reference_truth_table():
    for name, method in inspect.getmembers(BlueRepo, predicate=inspect.isfunction):
        if not name.startswith("_"):
            assert "scenario_ground_truth" not in inspect.getsource(method)


def test_pre_assessment_rejects_other_object_types():
    connection = create_match_database()
    repo = BlueRepo(connection, load_registry())
    try:
        with pytest.raises(TypeError):
            pre_delivery_assess(object(), repo, get_params("balanced"))
        with pytest.raises(TypeError):
            pre_delivery_assess({"message_id": 1}, repo, get_params("balanced"))
    finally:
        connection.close()


def test_each_match_database_is_private_and_memory_only():
    first = create_match_database()
    second = create_match_database()
    try:
        first.execute(
            """INSERT INTO matches(
                 seed,difficulty_mix,strictness,started_at,status
               ) VALUES('1','easy','balanced','sim','running')"""
        )
        assert first.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 1
        assert second.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 0
        first_path = first.execute("PRAGMA database_list").fetchone()["file"]
        second_path = second.execute("PRAGMA database_list").fetchone()["file"]
        assert first_path == ""
        assert second_path == ""
    finally:
        first.close()
        second.close()
