"""Delivery-count and redirect-refusal regressions.

No test performs a real network call. The urllib path is exercised through a
fake opener so redirect handling can be verified offline.
"""

from __future__ import annotations

import urllib.error

import pytest

import reporting.telegram_sender as sender
from engine.match import run_match
from reporting.delivery import AUTO, MANUAL, plan_delivery
from reporting.formatter import build_telegram_messages
from reporting.red_report import build_red_report
from reporting.telegram_sender import (
    REDIRECT_CODES,
    TelegramCredentials,
    TelegramTransportError,
    build_credentials,
    send_report,
)


PROFILES = ["cautious", "average", "careless"]
SECRETS = {
    "enabled": True,
    "bot_token": "555444:BBB-redirect-probe-token",
    "chat_id": "-100112233",
    "owner_pin": "700100",
}


def _report(seed: int = 1010):
    return build_red_report(run_match("mixed", "permissive", PROFILES, seed))


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, url, payload, timeout):
        self.calls.append((url, dict(payload), timeout))
        return 200


class _SessionHarness:
    """Minimal stand-in for the app's session state and delivery wiring."""

    def __init__(self, *, can_send=True, auto_send=False):
        self.state = {"report_token": None, "auto_sent_token": None}
        self.can_send = can_send
        self.auto_send = auto_send
        self.sends = 0
        self.transport = _Recorder()

    def _maybe_send(self, trigger):
        decision = plan_delivery(
            trigger,
            can_send=self.can_send,
            auto_send_enabled=self.auto_send,
            report_token=self.state["report_token"],
            already_sent_token=self.state["auto_sent_token"],
        )
        if not decision.should_send:
            return decision
        self.sends += 1
        send_report(
            self.report, build_credentials(SECRETS), transport=self.transport
        )
        if trigger == AUTO:
            self.state["auto_sent_token"] = self.state["report_token"]
        return decision

    def run_match_click(self):
        self.report = _report()
        self.state["report_token"] = (self.state["report_token"] or 0) + 1
        return self._maybe_send(AUTO)

    def manual_click(self):
        return self._maybe_send(MANUAL)

    def plain_rerun(self):
        return self._maybe_send(None)


def test_auto_send_delivers_exactly_once_per_match():
    harness = _SessionHarness(auto_send=True)
    harness.run_match_click()
    assert harness.sends == 1


def test_summary_is_transmitted_exactly_once():
    """The chat now carries one short summary; detail rides in the ZIP."""
    harness = _SessionHarness(auto_send=True)
    harness.run_match_click()
    sent = [payload["text"] for _, payload, _ in harness.transport.calls]
    assert len(sent) == 1
    assert sent.count(sent[0]) == 1
    assert "Aurio Range 경기 완료" in sent[0]


def test_manual_send_delivers_exactly_once_per_click():
    harness = _SessionHarness(auto_send=False)
    harness.run_match_click()
    assert harness.sends == 0
    harness.manual_click()
    assert harness.sends == 1


def test_auto_then_manual_totals_exactly_two():
    harness = _SessionHarness(auto_send=True)
    harness.run_match_click()
    harness.manual_click()
    assert harness.sends == 2


def test_plain_rerun_never_resends_a_previous_report():
    harness = _SessionHarness(auto_send=True)
    harness.run_match_click()
    baseline = harness.sends
    for _ in range(5):
        decision = harness.plain_rerun()
        assert decision.should_send is False
        assert decision.reason == "no_trigger"
    assert harness.sends == baseline


def test_repeated_auto_trigger_on_same_report_is_suppressed():
    harness = _SessionHarness(auto_send=True)
    harness.run_match_click()
    decision = harness._maybe_send(AUTO)
    assert decision.should_send is False
    assert decision.reason == "already_sent"
    assert harness.sends == 1


def test_a_new_match_is_eligible_for_auto_send_again():
    harness = _SessionHarness(auto_send=True)
    harness.run_match_click()
    harness.run_match_click()
    assert harness.sends == 2


@pytest.mark.parametrize(
    ("trigger", "can_send", "auto", "token", "sent_token", "expected"),
    [
        (None, True, True, 1, None, False),
        (AUTO, False, True, 1, None, False),
        (AUTO, True, False, 1, None, False),
        (AUTO, True, True, None, None, False),
        (AUTO, True, True, 1, 1, False),
        (AUTO, True, True, 2, 1, True),
        (MANUAL, True, False, 1, 1, True),
        (MANUAL, False, True, 1, None, False),
        ("something", True, True, 1, None, False),
    ],
)
def test_delivery_gate_truth_table(
    trigger, can_send, auto, token, sent_token, expected
):
    decision = plan_delivery(
        trigger,
        can_send=can_send,
        auto_send_enabled=auto,
        report_token=token,
        already_sent_token=sent_token,
    )
    assert decision.should_send is expected


class _FakeOpener:
    """Stands in for the module opener so no socket is ever created."""

    def __init__(self, error=None, status=200):
        self.error = error
        self.status = status
        self.opened = []

    def open(self, request, timeout=None):
        self.opened.append(getattr(request, "full_url", request))
        if self.error is not None:
            raise self.error
        opener = self

        class _Response:
            status = opener.status

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

        return _Response()


def _redirect_error(code: int, location: str, token: str):
    return urllib.error.HTTPError(
        f"https://api.telegram.org/bot{token}/sendMessage",
        code,
        "Redirect",
        {"Location": location},
        None,
    )


@pytest.mark.parametrize("code", sorted(REDIRECT_CODES))
def test_every_redirect_code_is_refused(code, monkeypatch):
    opener = _FakeOpener(
        error=_redirect_error(code, "https://evil.test/steal", SECRETS["bot_token"])
    )
    monkeypatch.setattr(sender, "_OPENER", opener)
    with pytest.raises(TelegramTransportError):
        sender._https_post(
            f"https://api.telegram.org/bot{SECRETS['bot_token']}/sendMessage",
            {"chat_id": "1", "text": "t"},
            5,
        )
    assert len(opener.opened) == 1


def test_redirect_to_the_same_host_is_also_refused(monkeypatch):
    opener = _FakeOpener(
        error=_redirect_error(
            302, "https://api.telegram.org/other/path", SECRETS["bot_token"]
        )
    )
    monkeypatch.setattr(sender, "_OPENER", opener)
    with pytest.raises(TelegramTransportError):
        sender._https_post(
            f"https://api.telegram.org/bot{SECRETS['bot_token']}/sendMessage",
            {"chat_id": "1", "text": "t"},
            5,
        )
    assert len(opener.opened) == 1


def test_redirect_status_returned_as_a_response_is_refused(monkeypatch):
    opener = _FakeOpener(status=307)
    monkeypatch.setattr(sender, "_OPENER", opener)
    with pytest.raises(TelegramTransportError):
        sender._https_post(
            f"https://api.telegram.org/bot{SECRETS['bot_token']}/sendMessage",
            {"chat_id": "1", "text": "t"},
            5,
        )
    assert len(opener.opened) == 1


def test_redirect_error_message_never_leaks_credentials(monkeypatch):
    opener = _FakeOpener(
        error=_redirect_error(
            301,
            f"https://evil.test/{SECRETS['bot_token']}",
            SECRETS["bot_token"],
        )
    )
    monkeypatch.setattr(sender, "_OPENER", opener)
    try:
        sender._https_post(
            f"https://api.telegram.org/bot{SECRETS['bot_token']}/sendMessage",
            {"chat_id": SECRETS["chat_id"], "text": "t"},
            5,
        )
        raise AssertionError("리다이렉트는 반드시 실패해야 합니다.")
    except TelegramTransportError as exc:
        assert SECRETS["bot_token"] not in str(exc)


def test_redirect_during_send_is_contained_and_scrubbed(monkeypatch):
    opener = _FakeOpener(
        error=_redirect_error(308, "https://evil.test/x", SECRETS["bot_token"])
    )
    monkeypatch.setattr(sender, "_OPENER", opener)
    outcome = send_report(_report(), build_credentials(SECRETS))
    assert outcome.ok is False
    assert outcome.status == "failed"
    assert SECRETS["bot_token"] not in outcome.detail
    assert SECRETS["chat_id"] not in outcome.detail
    # One attempt only: the redirect did not become a second request.
    assert len(opener.opened) == 1


def test_match_result_survives_a_redirect_failure(monkeypatch):
    opener = _FakeOpener(
        error=_redirect_error(302, "https://evil.test/x", SECRETS["bot_token"])
    )
    monkeypatch.setattr(sender, "_OPENER", opener)
    result = run_match("mixed", "balanced", PROFILES, 20260731)
    report = build_red_report(result)
    outcome = send_report(report, build_credentials(SECRETS))
    assert outcome.ok is False
    assert result["scores"]["red"] == 0
    assert result["scores"]["blue"] == 29
    assert report.attempts


def test_module_opener_refuses_redirects_by_construction():
    handler = next(
        h for h in sender._OPENER.handlers
        if isinstance(h, sender._NoRedirectHandler)
    )
    assert handler.redirect_request(None, None, 302, "Found", {}, "x") is None


def test_direct_transport_injection_still_reports_success():
    recorder = _Recorder()
    outcome = send_report(
        _report(), TelegramCredentials(SECRETS["bot_token"], SECRETS["chat_id"]),
        transport=recorder,
    )
    assert outcome.ok is True
    assert len(recorder.calls) == outcome.total
