"""Streamlit smoke tests for the initial view and one complete match."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_app_renders_and_runs_one_match():
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    app.run()
    assert not app.exception
    assert len(app.button) == 1
    assert app.button[0].label == "경기 실행"
    assert app.button[0].disabled is False

    app.button[0].click().run()
    assert not app.exception
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["RED SCORE"] == "0"
    assert metrics["BLUE SCORE"] == "33"
    assert metrics["MATCH SEED"] == "20260731"
    assert len(app.dataframe) >= 5
