"""Report sanitization, delivery boundary, and secret-hygiene tests.

No test performs a real network call. Delivery is exercised through an injected
transport so the approved module's behaviour can be checked offline.
"""

from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path

import pytest

from engine.match import run_match
from reporting.formatter import (
    CARD_SECTION_TITLES,
    build_cards,
    build_telegram_messages,
    summary_metrics,
)
from reporting.models import SafeRedReport
from reporting.red_report import build_red_report
from reporting.sanitizer import (
    ReportSanitizationError,
    assert_report_is_clean,
    assert_text_is_clean,
)
from reporting.telegram_sender import (
    TelegramCredentials,
    TelegramTransportError,
    assert_allowed_endpoint,
    build_credentials,
    owner_pin_configured,
    send_report,
    telegram_status,
    verify_owner_pin,
)


ROOT = Path(__file__).resolve().parents[1]
PROFILES = ["cautious", "average", "careless"]
SECRETS = {
    "enabled": True,
    "bot_token": "111222:AAA-secret-bot-token-value",
    "chat_id": "-100987654321",
    "owner_pin": "482913",
}


def _report(seed: int = 1010):
    return build_red_report(run_match("mixed", "permissive", PROFILES, seed))


class _Recorder:
    def __init__(self, fail_at: int | None = None):
        self.calls = []
        self.fail_at = fail_at

    def __call__(self, url, payload, timeout):
        self.calls.append((url, dict(payload), timeout))
        if self.fail_at is not None and len(self.calls) >= self.fail_at:
            raise OSError(f"connection reset for {url}")
        return 200


def test_report_contains_no_urls_markup_tokens_or_identifiers():
    report = _report()
    assert_report_is_clean(report)
    blob = json.dumps(build_cards(report), ensure_ascii=False)
    blob += "\n".join(build_telegram_messages(report))
    lowered = blob.lower()
    for denied in (
        "http", "://", "<div", "<span", "<script", "href=", "style=",
        "aurio-sig-", "@users.", "aurio.test", "aur1o", ".com", ".kr",
        "instagram", "javascript:",
    ):
        assert denied not in lowered, denied


def test_report_never_carries_message_bodies_or_destinations():
    result = run_match("mixed", "permissive", PROFILES, 1010)
    report = build_red_report(result)
    blob = "\n".join(build_telegram_messages(report))
    for message in result["messages"]:
        assert message["body_text"] not in blob
        assert message["subject_text"] not in blob
        assert message["rendered_html"] not in blob


@pytest.mark.parametrize(
    "dirty",
    [
        "확인 https://aurio-help.test/check",
        "<div>보고서</div>",
        "서명 AURIO-SIG-AR-H-0001",
        "문의 analyst@example.com",
        "호스트 aur1o.test",
        "사건 AR-H-0001",
        "password=hunter2",
        "message_id=17",
        "instagram 계정",
        "style=color:red",
        "javascript:alert(1)",
        "도메인 example.kr",
    ],
)
def test_sanitizer_rejects_each_forbidden_category(dirty):
    with pytest.raises(ReportSanitizationError):
        assert_text_is_clean(dirty)


def test_sanitizer_catches_tampered_report_field():
    report = _report()
    poisoned = replace(
        report.attempts[0], research_note="자세히 https://aur1o.test/check"
    )
    tampered = SafeRedReport(
        summary=report.summary,
        attempts=(poisoned,) + report.attempts[1:],
        conclusions=report.conclusions,
    )
    with pytest.raises(ReportSanitizationError):
        assert_report_is_clean(tampered)


def test_mobile_cards_have_all_required_sections_and_fields():
    report = _report()
    cards = build_cards(report)
    assert cards
    for card in cards:
        assert set(card) >= {"title", "badge", "outcome", "subtitle", "sections"}
        titles = [section["title"] for section in card["sections"]]
        assert titles == list(CARD_SECTION_TITLES)
        for section in card["sections"]:
            assert section["items"]
            assert all(str(item).strip() for item in section["items"])
    headline = dict(summary_metrics(report))
    for label in (
        "Red 점수", "Blue 점수", "위조 시도", "격리", "경고", "허용",
        "클릭 피해", "제출 피해", "경고 이탈", "봉쇄 성공",
        "합성 자격증명 노출", "시뮬레이션 계정 탈취",
    ):
        assert label in headline


def test_same_seed_produces_identical_report():
    assert _report(1010) == _report(1010)


def test_telegram_messages_are_ordered_and_chunked():
    messages = build_telegram_messages(_report())
    assert len(messages) >= 3
    total = len(messages)
    for index, body in enumerate(messages, 1):
        assert body.startswith(f"[{index}/{total}]")
        assert len(body) <= 3700
    assert "경기 전체 요약" in messages[0]
    assert "최종 연구 결론" in messages[-1]


def test_status_and_credentials_handle_missing_configuration():
    assert telegram_status(None) == "missing"
    assert telegram_status({}) == "missing"
    assert telegram_status({"bot_token": "t", "chat_id": "c"}) == "inactive"
    assert telegram_status(SECRETS) == "active"
    assert build_credentials(None) is None
    assert build_credentials({"enabled": True, "bot_token": "t"}) is None
    assert build_credentials({**SECRETS, "enabled": False}) is None
    assert build_credentials(SECRETS) is not None


def test_owner_pin_is_required_and_compared_exactly():
    assert owner_pin_configured(SECRETS) is True
    assert owner_pin_configured({}) is False
    assert verify_owner_pin(SECRETS, "482913") is True
    assert verify_owner_pin(SECRETS, "482914") is False
    assert verify_owner_pin(SECRETS, "") is False
    assert verify_owner_pin(SECRETS, None) is False
    assert verify_owner_pin({}, "482913") is False


@pytest.mark.parametrize(
    "url",
    [
        "https://example.test/bot1/sendMessage",
        "http://api.telegram.org/bot1/sendMessage",
        "https://api.telegram.org.evil.test/bot1/sendMessage",
        "https://evil.test/api.telegram.org/sendMessage",
    ],
)
def test_endpoint_guard_rejects_every_other_destination(url):
    with pytest.raises(TelegramTransportError):
        assert_allowed_endpoint(url)


def test_endpoint_guard_accepts_the_approved_host():
    assert_allowed_endpoint("https://api.telegram.org/bot1/sendMessage")


def test_rebinding_the_host_alias_cannot_redirect_traffic(monkeypatch):
    """Routing reads the hash-locked policy value, not this module's global."""
    import reporting.telegram_sender as sender

    recorder = _Recorder()
    monkeypatch.setattr(sender, "TELEGRAM_ALLOWED_HOST", "evil.test")
    outcome = sender.send_report(
        _report(), TelegramCredentials(SECRETS["bot_token"], SECRETS["chat_id"]),
        transport=recorder,
    )
    assert outcome.ok is True
    assert recorder.calls
    for url, _, _ in recorder.calls:
        assert url.startswith("https://api.telegram.org/bot")
        assert "evil.test" not in url


def test_disabled_telegram_returns_status_without_sending():
    recorder = _Recorder()
    outcome = send_report(_report(), None, transport=recorder)
    assert outcome.attempted is False
    assert outcome.status == "missing_config"
    assert recorder.calls == []


def test_successful_delivery_uses_only_the_approved_endpoint():
    recorder = _Recorder()
    credentials = build_credentials(SECRETS)
    outcome = send_report(_report(), credentials, transport=recorder)
    assert outcome.ok is True
    assert outcome.status == "sent"
    assert outcome.delivered == outcome.total == len(recorder.calls)
    for url, payload, _ in recorder.calls:
        assert url.startswith("https://api.telegram.org/bot")
        assert payload["chat_id"] == SECRETS["chat_id"]
        assert payload["disable_web_page_preview"] is True


def test_transport_failure_is_contained_and_scrubbed():
    recorder = _Recorder(fail_at=2)
    credentials = build_credentials(SECRETS)
    outcome = send_report(_report(), credentials, transport=recorder)
    assert outcome.ok is False
    assert outcome.status in {"failed", "partial"}
    assert SECRETS["bot_token"] not in outcome.detail
    assert SECRETS["chat_id"] not in outcome.detail


def test_secrets_never_appear_in_results_repr_or_report():
    credentials = build_credentials(SECRETS)
    assert SECRETS["bot_token"] not in repr(credentials)
    assert SECRETS["bot_token"] not in str(credentials)
    assert SECRETS["chat_id"] not in repr(credentials)
    report = _report()
    blob = "\n".join(build_telegram_messages(report))
    assert SECRETS["bot_token"] not in blob
    assert SECRETS["owner_pin"] not in blob


def test_match_result_and_database_never_store_secrets():
    result = run_match("mixed", "permissive", PROFILES, 1010)
    blob = json.dumps(result, ensure_ascii=False, default=str)
    for secret in (SECRETS["bot_token"], SECRETS["chat_id"], SECRETS["owner_pin"]):
        assert secret not in blob


def test_sender_refuses_any_payload_that_is_not_a_safe_report():
    credentials = build_credentials(SECRETS)
    for payload in ({"summary": "x"}, "보고서", 42, None):
        with pytest.raises(TypeError):
            send_report(payload, credentials, transport=_Recorder())


def test_match_completes_normally_with_telegram_absent():
    result = run_match("mixed", "balanced", PROFILES, 1010)
    assert result["safety_events"] == []
    assert build_red_report(result).attempts


def test_engine_never_imports_the_delivery_path():
    for folder in ("engine", "safety", "brandkit"):
        # safety/ is the enforcer of the boundary, so it names the approved
        # host on purpose; the agent packages must not mention it at all.
        for path in (ROOT / folder).glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    assert not name.startswith("reporting"), path.name
            if folder != "safety":
                source = path.read_text(encoding="utf-8").lower()
                assert "telegram" not in source, path.name


def test_only_the_approved_module_may_reach_the_network():
    egress = ROOT / "reporting" / "telegram_sender.py"
    for path in (ROOT / "reporting").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        if path != egress:
            assert not any(name.startswith("urllib") for name in imported), path.name
        else:
            assert "urllib.request" in imported
    source = egress.read_text(encoding="utf-8")
    # The host is not a literal here on purpose: it comes from the hash-locked
    # policy so rebinding a module global cannot redirect traffic.
    assert "safety.constitution" in source
    from safety.constitution import TELEGRAM_ALLOWED_HOST

    assert TELEGRAM_ALLOWED_HOST == "api.telegram.org"
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    for denied in ("requests", "httpx", "aiohttp", "anthropic", "openai"):
        assert denied not in requirements
