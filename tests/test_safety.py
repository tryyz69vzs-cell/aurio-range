"""Safety lock, no-egress, structured-Red, schema, and rendering tests."""

from __future__ import annotations

import ast
import inspect
import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from brandkit.renderer import render_email, render_login, static_login_preview
from engine.db import create_match_database, table_columns
from engine.platform_state import materialize_scenario
from engine.red_agent import build_scenario
from safety.constitution import FORBIDDEN_IMPORTS, LOCKED_FILES, SafetyViolation
from safety.guard import (
    arena_gate,
    run_startup_checks,
    validate_red_output,
    verify_config_hash,
)


ROOT = Path(__file__).resolve().parents[1]


def base_artifact(sender: str = "notice@aur1o.test"):
    visual = json.loads(
        (ROOT / "brandkit" / "aurio_visual.json").read_text(encoding="utf-8")
    )
    artifact = build_scenario(
        {"id": 1, "username": "민서"}, "easy", visual
    )
    artifact["synthetic_sender_address"] = sender
    return artifact


def _copy_locked_files(target_root: Path) -> None:
    for relative in (*LOCKED_FILES, "safety/SAFETY.lock"):
        source = ROOT / relative
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def test_hash_lock_targets_all_runtime_safety_files():
    locked = json.loads(
        (ROOT / "safety" / "SAFETY.lock").read_text(encoding="utf-8")
    )
    assert set(locked) == set(LOCKED_FILES)
    assert "brandkit/aurio_visual.json" not in locked
    assert "brandkit/renderer.py" in locked
    assert "brandkit/templates/email.html" in locked
    assert "brandkit/templates/login.html" in locked
    verify_config_hash()
    run_startup_checks()
    arena_gate()


def test_brandkit_is_not_part_of_hash_verification(tmp_path, monkeypatch):
    import safety.guard as guard

    temp_root = tmp_path / "copy"
    _copy_locked_files(temp_root)
    (temp_root / "brandkit").mkdir(exist_ok=True)
    (temp_root / "brandkit" / "aurio_visual.json").write_text(
        '{"brand_name":"Completely changed"}', encoding="utf-8"
    )
    monkeypatch.setattr(guard, "ROOT", temp_root)
    monkeypatch.setattr(guard, "LOCK_PATH", temp_root / "safety" / "SAFETY.lock")
    guard.verify_config_hash()


def test_engine_and_safety_have_no_forbidden_network_imports():
    found = []
    paths = [ROOT / "app.py"]
    for folder in ("engine", "safety", "brandkit"):
        paths.extend((ROOT / folder).glob("*.py"))
    for source_path in paths:
        if source_path.name == "relock.py":
            continue
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                names = []
            for name in names:
                if any(
                    name == denied or name.startswith(f"{denied}.")
                    for denied in FORBIDDEN_IMPORTS
                ):
                    found.append((source_path.name, name))
    assert found == []

    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    for denied in ("anthropic", "openai", "httpx", "aiohttp"):
        assert denied not in requirements


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("synthetic_sender_address", "alert@unsafe.com"),
        ("synthetic_sender_address", "alert@unsafe.kr"),
        ("synthetic_sender_address", "alert@unsafe.net"),
        ("synthetic_sender_address", "alert@google.test"),
        ("body_text", "문의: analyst@example.org"),
        ("body_text", "확인 http://outside.test"),
        ("body_text", "javascript:alert(1)"),
        ("body_text", "data:text/html,unsafe"),
        ("body_text", "<script>alert(1)</script>"),
        ("body_text", "<img src=x onerror=alert(1)>"),
        ("body_text", "<p style=color:red>unsafe</p>"),
        ("display_sender", "<b>Aurio</b>"),
        ("action_label", "<button onclick=x>go</button>"),
        ("destination_identifier", "/_sim/capture"),
        ("destination_identifier", "https://aur1o.test/_sim/capture"),
        ("claimed_event_ref", "AR-E-1<script>"),
    ],
)
def test_adversarial_structured_red_samples_are_discarded(field, value):
    artifact = base_artifact()
    artifact[field] = value
    passed, _ = validate_red_output(artifact)
    assert passed is False


@pytest.mark.parametrize(
    "sender",
    [
        "notice@aur1o.test",
        "notice@aurio-help.test",
        "notice@aurio-security.local",
        "security@aurio.test",
        "signal@accounts.local",
        "alert@relay-lab.test",
    ],
)
def test_reserved_synthetic_senders_are_accepted(sender):
    passed, reason = validate_red_output(base_artifact(sender))
    assert passed, reason


def test_red_contract_has_no_markup_payload_and_renderer_escapes():
    artifact = base_artifact()
    source = inspect.getsource(build_scenario).lower()
    assert "phish_page" not in source
    assert set(artifact).isdisjoint({"html", "css", "javascript", "phish_page"})
    artifact["body_text"] = "<b>escaped</b>"
    rendered = render_email(artifact)
    assert "&lt;b&gt;escaped&lt;/b&gt;" in rendered
    assert "<b>escaped</b>" not in rendered


def test_login_action_is_registry_forced_and_preview_is_static():
    artifact = base_artifact()
    artifact["internal_capture_path"] = "/unsafe/ignored"
    rendered = render_login(artifact)
    lowered_rendered = rendered.lower()
    for denied in ("<form", "<input", "<button", "<a ", "href=", "action="):
        assert denied not in lowered_rendered
    preview = static_login_preview(rendered)
    lowered = preview.lower()
    assert preview == rendered
    for denied in ("<form", "<input", "<button", "<a ", "href=", "action="):
        assert denied not in lowered


def test_email_preview_has_no_clickable_or_external_resource_elements():
    rendered = render_email(base_artifact())
    lowered = rendered.lower()
    for denied in (
        "<a ",
        "href=",
        "<script",
        "<iframe",
        "<form",
        "<input",
        "src=",
        "javascript:",
        "data:",
    ):
        assert denied not in lowered


def test_red_cannot_request_a_valid_platform_signature():
    artifact = base_artifact()
    artifact["tactics"]["signature_mode"] = "valid"
    passed, reason = validate_red_output(artifact)
    assert passed is False
    assert "서명" in reason


def test_red_cannot_claim_to_be_a_platform_scenario():
    artifact = base_artifact()
    artifact["scenario_type"] = "official_security_alert"
    passed, _ = validate_red_output(artifact)
    assert passed is False


def test_materializer_rejects_valid_signature_for_forged_scenario():
    artifact = base_artifact()
    artifact["tactics"]["signature_mode"] = "valid"
    registry = json.loads(
        (ROOT / "safety" / "trusted_registry.json").read_text(encoding="utf-8")
    )
    with pytest.raises(ValueError):
        materialize_scenario(artifact, registry)


def test_schema_contains_only_behavior_flags_and_no_account_secret():
    connection = create_match_database()
    try:
        account_columns = {row["name"] for row in table_columns(connection, "accounts")}
        assert "credential_token" not in account_columns
        capture = table_columns(connection, "capture_events")
        names = {row["name"] for row in capture}
        flags = {
            "attempted_username",
            "attempted_password",
            "valid_synthetic_credentials_submitted",
            "submitted_to_phish",
            "credential_exposure",
            "takeover_success",
        }
        assert names & flags == flags
        types = {row["name"]: row["type"].upper() for row in capture}
        assert all(types[flag] == "INTEGER" for flag in flags)
        # Submit-time snapshots are labels, never credential material.
        snapshot = {
            "submission_target",
            "account_status_at_submit",
            "session_state_at_submit",
        }
        assert names & snapshot == snapshot
        assert all(types[field] == "TEXT" for field in snapshot)
        assert not any(
            token in name
            for name in names
            for token in ("password_value", "secret", "plaintext", "credential_token")
        )
    finally:
        connection.close()


def test_no_engine_or_app_code_invokes_human_relock():
    for path in [ROOT / "app.py", *(ROOT / "engine").glob("*.py")]:
        assert "relock" not in path.read_text(encoding="utf-8").lower()


def test_tampered_hash_fails_closed(tmp_path, monkeypatch):
    import safety.guard as guard

    temp_root = tmp_path / "copy"
    _copy_locked_files(temp_root)
    with (temp_root / "safety" / "trusted_registry.json").open(
        "a", encoding="utf-8"
    ) as handle:
        handle.write("\n")
    monkeypatch.setattr(guard, "ROOT", temp_root)
    monkeypatch.setattr(guard, "LOCK_PATH", temp_root / "safety" / "SAFETY.lock")
    with pytest.raises(SafetyViolation):
        guard.verify_config_hash()
