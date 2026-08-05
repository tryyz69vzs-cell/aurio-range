"""File-based Telegram delivery: one summary, one document, nothing else."""

from __future__ import annotations

import re
import urllib.error
from pathlib import Path

import pytest

import reporting.telegram_sender as sender
from engine.match import run_match
from reporting.bundle import build_bundle
from reporting.delivery import AUTO, MANUAL, plan_delivery
from reporting.formatter import build_telegram_summary
from reporting.red_report import build_red_report
from reporting.telegram_sender import (
    SafeReportBundle,
    TelegramCredentials,
    build_credentials,
    send_report_bundle,
)

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ["cautious", "average", "careless"]
SECRETS = {
    "enabled": True,
    "bot_token": "778899:CCC-bundle-delivery-token",
    "chat_id": "-100554433",
    "owner_pin": "246810",
}


def _bundle(seed: int = 1010):
    result = run_match("mixed", "permissive", PROFILES, seed)
    report = build_red_report(result)
    name, payload = build_bundle(result, report)
    summary = build_telegram_summary(report, "2026-08-04T00:00:00Z")
    return SafeReportBundle(name, payload, summary), report


class _Recorder:
    def __init__(self, fail_at=None):
        self.calls = []
        self.fail_at = fail_at

    def __call__(self, url, payload=None, timeout=8, body=None, content_type=None):
        self.calls.append(
            {
                "method": url.rsplit("/", 1)[-1],
                "url": url,
                "payload": payload,
                "body_len": len(body) if body else 0,
                "content_type": content_type,
            }
        )
        if self.fail_at is not None and len(self.calls) >= self.fail_at:
            raise OSError("connection reset")
        return 200


def test_one_summary_message_and_one_document_per_send():
    bundle, _ = _bundle()
    recorder = _Recorder()
    outcome = send_report_bundle(bundle, build_credentials(SECRETS), recorder)
    assert outcome.ok is True and outcome.status == "sent"
    methods = [call["method"] for call in recorder.calls]
    assert methods == ["sendMessage", "sendDocument"]
    assert methods.count("sendMessage") == 1
    assert methods.count("sendDocument") == 1
    # multipart body = form headers + the archive bytes
    assert recorder.calls[1]["body_len"] > len(bundle.content)
    assert "multipart/form-data" in recorder.calls[1]["content_type"]


def test_summary_message_is_short_and_complete():
    bundle, report = _bundle()
    text = bundle.summary_text
    assert len(text) < 900
    assert "Aurio Range 경기 완료" in text
    assert str(report.summary.seed) in text
    assert "상세 내용은 첨부 보고서를 확인하세요." in text
    for label in ("Red 점수", "Blue 점수", "위조 시도", "격리", "경고", "허용",
                  "클릭", "제출", "credential exposure", "takeover success"):
        assert label in text


def test_filename_is_safe_and_seed_stamped():
    bundle, report = _bundle()
    assert re.fullmatch(r"aurio-report-\d+-\d{8}-\d{6}\.zip", bundle.filename)
    assert str(report.summary.seed) in bundle.filename
    assert "/" not in bundle.filename and "\\" not in bundle.filename


def test_bundle_rejects_paths_and_non_zip_names():
    with pytest.raises(ValueError):
        SafeReportBundle("../escape.zip", b"x", "s")
    with pytest.raises(ValueError):
        SafeReportBundle("report.txt", b"x", "s")


def test_sender_refuses_anything_that_is_not_a_bundle():
    for payload in ({"filename": "a.zip"}, "report", 7, None):
        with pytest.raises(TypeError):
            send_report_bundle(payload, build_credentials(SECRETS), _Recorder())


def test_disabled_telegram_sends_nothing():
    bundle, _ = _bundle()
    recorder = _Recorder()
    outcome = send_report_bundle(bundle, None, recorder)
    assert outcome.attempted is False
    assert outcome.status == "missing_config"
    assert recorder.calls == []


def test_every_endpoint_is_the_approved_host():
    bundle, _ = _bundle()
    recorder = _Recorder()
    send_report_bundle(bundle, build_credentials(SECRETS), recorder)
    for call in recorder.calls:
        assert call["url"].startswith("https://api.telegram.org/bot")


def test_failure_is_contained_and_scrubbed():
    bundle, _ = _bundle()
    recorder = _Recorder(fail_at=1)
    outcome = send_report_bundle(bundle, build_credentials(SECRETS), recorder)
    assert outcome.ok is False
    assert SECRETS["bot_token"] not in outcome.detail
    assert SECRETS["chat_id"] not in outcome.detail


def test_redirect_blocks_the_document_upload(monkeypatch):
    class _FakeOpener:
        def __init__(self):
            self.opened = []

        def open(self, request, timeout=None):
            self.opened.append(request)
            raise urllib.error.HTTPError(
                f"https://api.telegram.org/bot{SECRETS['bot_token']}/sendMessage",
                302, "Found", {"Location": "https://evil.test/x"}, None,
            )

    opener = _FakeOpener()
    monkeypatch.setattr(sender, "_OPENER", opener)
    bundle, _ = _bundle()
    outcome = send_report_bundle(bundle, build_credentials(SECRETS))
    assert outcome.ok is False
    assert len(opener.opened) == 1
    assert SECRETS["bot_token"] not in outcome.detail


def test_match_and_downloads_survive_a_delivery_failure():
    result = run_match("mixed", "balanced", PROFILES, 20260731)
    report = build_red_report(result)
    name, payload = build_bundle(result, report)
    recorder = _Recorder(fail_at=1)
    outcome = send_report_bundle(
        SafeReportBundle(name, payload, build_telegram_summary(report, "T")),
        build_credentials(SECRETS), recorder,
    )
    assert outcome.ok is False
    assert result["scores"]["red"] == 0 and result["scores"]["blue"] == 29
    assert payload and name


def test_auto_send_is_one_bundle_and_a_rerun_sends_nothing():
    bundle, _ = _bundle()
    credentials = build_credentials(SECRETS)
    recorder = _Recorder()
    state = {"report_token": 1, "auto_sent_token": None}
    decision = plan_delivery(
        AUTO, can_send=True, auto_send_enabled=True,
        report_token=state["report_token"],
        already_sent_token=state["auto_sent_token"],
    )
    assert decision.should_send
    send_report_bundle(bundle, credentials, recorder)
    state["auto_sent_token"] = state["report_token"]
    assert len(recorder.calls) == 2

    for _ in range(3):
        rerun = plan_delivery(
            None, can_send=True, auto_send_enabled=True,
            report_token=state["report_token"],
            already_sent_token=state["auto_sent_token"],
        )
        assert rerun.should_send is False
    repeat = plan_delivery(
        AUTO, can_send=True, auto_send_enabled=True,
        report_token=state["report_token"],
        already_sent_token=state["auto_sent_token"],
    )
    assert repeat.should_send is False
    assert len(recorder.calls) == 2

    manual = plan_delivery(
        MANUAL, can_send=True, auto_send_enabled=True,
        report_token=state["report_token"],
        already_sent_token=state["auto_sent_token"],
    )
    assert manual.should_send
    send_report_bundle(bundle, credentials, recorder)
    assert len(recorder.calls) == 4


def test_workflow_only_commits_state_and_reports():
    workflow = (ROOT / ".github" / "workflows" / "evolve.yml").read_text("utf-8")
    assert "workflow_dispatch" in workflow
    assert "tools.commit_guard" in workflow
    assert "python -m pytest -q" in workflow
    assert "arena_gate" in workflow
    assert "git add evolution_state reports" in workflow
    assert "TELEGRAM_BOT_TOKEN" in workflow
    guard = (ROOT / "tools" / "commit_guard.py").read_text("utf-8")
    assert "evolution_state/" in guard and "reports/" in guard


@pytest.mark.parametrize(
    "path",
    ["app.py", "safety/constitution.py", "engine/judge.py",
     "brandkit/renderer.py", "requirements.txt",
     ".github/workflows/evolve.yml", "tests/test_evolution.py"],
)
def test_commit_guard_rejects_forbidden_paths(path):
    import tools.commit_guard as guard

    allowed = path.startswith(guard.ALLOWED_PREFIXES) and path.endswith(
        guard.ALLOWED_SUFFIXES
    )
    assert allowed is False


@pytest.mark.parametrize(
    "path",
    ["evolution_state/state.json", "evolution_state/lineage.json",
     "reports/aurio-report-1-2.zip", "reports/latest.md"],
)
def test_commit_guard_allows_state_and_reports(path):
    import tools.commit_guard as guard

    allowed = path.startswith(guard.ALLOWED_PREFIXES) and path.endswith(
        guard.ALLOWED_SUFFIXES
    )
    assert allowed is True


def test_workflow_gates_telegram_on_both_secrets():
    """The condition must not read a step-local env var it also declares."""
    workflow = (ROOT / ".github" / "workflows" / "evolve.yml").read_text("utf-8")
    lines = workflow.splitlines()
    job_env = workflow.index("    env:")
    steps = workflow.index("    steps:")
    assert job_env < steps, "secrets는 job 수준 env로 매핑되어야 합니다."
    assert "TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}" in workflow
    assert "TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}" in workflow
    # Both secrets are required, and the gate is a step output, not env in if.
    assert '-n "$TELEGRAM_BOT_TOKEN"' in workflow
    assert '-n "$TELEGRAM_CHAT_ID"' in workflow
    assert "if: steps.telegram.outputs.configured == 'true'" in workflow
    assert "${{ env.TELEGRAM_BOT_TOKEN != '' }}" not in workflow
    # The secret values themselves are never echoed.
    for index, line in enumerate(lines):
        if "echo" in line:
            assert "$TELEGRAM_BOT_TOKEN" not in line, index
            assert "$TELEGRAM_CHAT_ID" not in line, index


def test_send_cli_exit_codes_distinguish_skip_success_and_failure(tmp_path, monkeypatch):
    import tools.send_latest_report as cli
    from reporting.telegram_sender import TelegramSendResult

    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "latest.txt").write_text("aurio-report-1-2.zip", encoding="utf-8")
    (reports / "aurio-report-1-2.zip").write_bytes(b"PK\x03\x04payload")
    monkeypatch.setattr(cli, "REPORT_DIR", reports)

    monkeypatch.setattr(cli.os, "environ", {})
    assert cli.main() == 0  # no secrets -> deliberate skip

    env = {
        "TELEGRAM_BOT_TOKEN": SECRETS["bot_token"],
        "TELEGRAM_CHAT_ID": SECRETS["chat_id"],
    }
    monkeypatch.setattr(cli.os, "environ", env)

    outcomes = {
        "sent": (TelegramSendResult(True, 2, 2, True, "sent", "ok"), 0),
        "failed": (TelegramSendResult(True, 0, 2, False, "failed", "전송 실패"), 1),
        "partial": (TelegramSendResult(True, 1, 2, False, "partial", "부분 전송"), 1),
        "blocked": (TelegramSendResult(False, 0, 2, False, "blocked", "차단"), 1),
    }
    for status, (result, expected) in outcomes.items():
        monkeypatch.setattr(cli, "send_report_bundle", lambda *a, **k: result)
        assert cli.main() == expected, status


def test_send_cli_never_prints_the_secrets(tmp_path, monkeypatch, capsys=None):
    import io
    import contextlib

    import tools.send_latest_report as cli
    from reporting.telegram_sender import TelegramSendResult

    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "latest.txt").write_text("aurio-report-1-2.zip", encoding="utf-8")
    (reports / "aurio-report-1-2.zip").write_bytes(b"PK\x03\x04payload")
    monkeypatch.setattr(cli, "REPORT_DIR", reports)
    monkeypatch.setattr(
        cli.os, "environ",
        {
            "TELEGRAM_BOT_TOKEN": SECRETS["bot_token"],
            "TELEGRAM_CHAT_ID": SECRETS["chat_id"],
        },
    )
    monkeypatch.setattr(
        cli, "send_report_bundle",
        lambda *a, **k: TelegramSendResult(
            True, 0, 2, False, "failed", "전송 실패: OSError"
        ),
    )
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert cli.main() == 1
    printed = buffer.getvalue()
    assert SECRETS["bot_token"] not in printed
    assert SECRETS["chat_id"] not in printed
