"""Static checks on app.py wiring that do not require a Streamlit runtime.

The AppTest suite in test_app_smoke.py needs Streamlit installed. These checks
run everywhere and pin the invariants that were regressions in review:
one delivery call site, no stale network claim, and a live safety badge.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


def _source() -> str:
    return APP.read_text(encoding="utf-8")


def _tree() -> ast.AST:
    return ast.parse(_source())


def test_deliver_report_has_exactly_one_call_site():
    """Regression: a duplicated call would send every report twice."""
    calls = [
        node
        for node in ast.walk(_tree())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "deliver_report"
    ]
    assert len(calls) == 1


def test_delivery_is_decided_once_through_the_gate():
    tree = _tree()
    gate_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "plan_delivery"
    ]
    assert len(gate_calls) == 1
    source = _source()
    assert "if decision.should_send:" in source


def test_no_consecutive_duplicate_statements_in_app():
    """Catches an accidentally pasted repeat of any expression statement."""
    tree = _tree()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        previous = None
        for statement in body:
            if isinstance(statement, ast.Expr) and isinstance(
                statement.value, ast.Call
            ):
                current = ast.dump(statement.value)
                assert current != previous, "동일 호출이 연속으로 반복됩니다."
                previous = current
            else:
                previous = None


def test_network_badge_no_longer_claims_zero_egress_overall():
    source = _source()
    assert "NO NETWORK EGRESS" not in source
    assert "SIMULATION ENGINE · NO EGRESS" in source
    assert "REPORTING · OFFLINE" in source
    assert "REPORTING · TELEGRAM ONLY" in source


def test_safety_badge_is_bound_to_the_gate_result():
    source = _source()
    assert 'safety_badge_class = "safe" if safe else "blocked"' in source
    assert '"안전 게이트 통과" if safe else "안전 게이트 차단"' in source
    assert "{safety_badge_class}" in source
    assert "{safety_badge_text}" in source
    # A hard-coded pass badge must not survive anywhere.
    assert '<span class="badge safe">● 안전 게이트 통과</span>' not in source


def test_unsafe_gate_disables_running_and_sending():
    source = _source()
    assert "disabled=not safe or not profiles" in source
    assert 'can_send = safe and unlocked and TELEGRAM_STATE == "active"' in source


def test_readme_describes_the_reporting_exception():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "api.telegram.org" in readme
    assert "이그레스 없음" in readme
    assert "LLM 및 그 밖의 외부 API는 사용하지 않습니다" in readme
    assert "리다이렉트" in readme
