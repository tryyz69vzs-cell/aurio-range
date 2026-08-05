"""Streamlit smoke tests for the initial view and one complete match.

Requires Streamlit. Where it is not installed this module records a single
explicit skip instead of a collection error; CI has it installed and runs the
whole file.

Expected values changed with the submission-semantics redesign. See
docs/SCORING_CHANGELOG.md for why BLUE moved from 33 to 29 on this seed.
"""

from __future__ import annotations

from pathlib import Path

import pytest


streamlit_testing = pytest.importorskip(
    "streamlit.testing.v1",
    reason="Streamlit이 설치되지 않아 AppTest 스모크 테스트를 건너뜁니다.",
)
AppTest = streamlit_testing.AppTest


ROOT = Path(__file__).resolve().parents[1]


def _app():
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    app.run()
    return app


def test_streamlit_app_renders_and_runs_one_match():
    app = _app()
    assert not app.exception
    labels = [button.label for button in app.button]
    assert "경기 실행" in labels
    run_button = next(b for b in app.button if b.label == "경기 실행")
    assert run_button.disabled is False

    run_button.click().run()
    assert not app.exception
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["RED SCORE"] == "0"
    assert metrics["BLUE SCORE"] == "29"
    assert metrics["MATCH SEED"] == "20260731"
    # The ambiguous compromise card is gone; exposure and takeover are separate.
    assert "Synthetic Credential Exposure" in metrics
    assert "Simulated Takeover Success" in metrics
    assert "Synthetic Compromise" not in metrics
    assert len(app.dataframe) >= 5


def test_app_starts_and_locks_delivery_without_telegram_secrets():
    """No secrets file exists in CI; the app must start with send locked."""
    app = _app()
    assert not app.exception
    for button in app.button:
        if button.label == "이번 경기 보고서 전송":
            assert button.disabled is True
    for box in app.checkbox:
        if box.label == "경기 종료 후 자동 전송":
            assert box.disabled is True


def test_hero_badges_describe_the_real_network_and_safety_state():
    app = _app()
    assert not app.exception
    rendered = "\n".join(block.value for block in app.markdown)
    assert "SIMULATION ENGINE · NO EGRESS" in rendered
    # Stale absolute claim must be gone now that a reporting path exists.
    assert "NO NETWORK EGRESS" not in rendered
    # Without secrets the reporting path is offline.
    assert "REPORTING · OFFLINE" in rendered
    assert "REPORTING · TELEGRAM ONLY" not in rendered
    # The safety badge reflects the gate, which passes in a clean checkout.
    assert "안전 게이트 통과" in rendered
    assert "안전 게이트 차단" not in rendered


def test_no_delivery_happens_on_a_plain_rerun():
    app = _app()
    run_button = next(b for b in app.button if b.label == "경기 실행")
    run_button.click().run()
    assert not app.exception
    token = app.session_state["report_token"]
    app.run()
    assert not app.exception
    # A rerun must not produce a new report token or a new delivery.
    assert app.session_state["report_token"] == token
    # SafeSessionState does not implement .get(); membership is supported.
    assert "auto_sent_token" not in app.session_state
