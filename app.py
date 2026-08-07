"""Streamlit control room for one-shot, session-isolated Aurio matches."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import streamlit as st

from engine.match import run_match
from evolution.controller import run_evolution
from evolution.models import EvolutionConfig, clamp_config
from evolution.reporting import build_evolution_summary
from reporting.bundle import build_bundle, build_markdown, build_metrics_csv, build_report_json
from reporting.delivery import AUTO, MANUAL, plan_delivery
from reporting.formatter import build_cards, build_telegram_summary, summary_metrics
from reporting.red_report import build_red_report
from reporting.telegram_sender import (
    SafeReportBundle,
    build_credentials,
    owner_pin_configured,
    send_report_bundle,
    telegram_status,
    verify_owner_pin,
)
from safety.constitution import SafetyViolation
from safety.guard import run_startup_checks, verify_config_hash


st.set_page_config(
    page_title="Aurio Range",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="auto",
)

st.markdown(
    """
<style>
:root{--ink:#f8fafc;--muted:#93a4ba;--line:rgba(148,163,184,.14);--teal:#14b8a6;--blue:#3b6fca}
html,body,[class*="css"]{font-family:Pretendard,Inter,system-ui,sans-serif}
.stApp{background:
 radial-gradient(circle at 78% -10%,rgba(46,90,172,.25),transparent 34rem),
 radial-gradient(circle at 18% 12%,rgba(20,184,166,.10),transparent 28rem),
 #07111f;color:var(--ink)}
[data-testid="stSidebar"]{background:#0a1525;border-right:1px solid var(--line)}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p{color:#b8c5d6}
.block-container{padding-top:2rem;max-width:1480px}
.hero{position:relative;overflow:hidden;padding:32px 34px;margin-bottom:20px;border:1px solid var(--line);
 border-radius:22px;background:linear-gradient(145deg,rgba(21,37,60,.96),rgba(10,23,39,.96));
 box-shadow:0 22px 70px rgba(0,0,0,.22)}
.hero:after{content:"";position:absolute;width:260px;height:260px;right:-70px;top:-105px;border:1px solid rgba(20,184,166,.25);border-radius:50%;box-shadow:0 0 0 36px rgba(46,90,172,.08),0 0 0 76px rgba(20,184,166,.035)}
.kicker{font-size:11px;letter-spacing:.2em;color:#5eead4;font-weight:800;margin-bottom:12px}
.hero h1{position:relative;margin:0 0 9px;font-size:clamp(34px,5vw,58px);line-height:1;letter-spacing:-.045em}
.hero p{position:relative;max-width:760px;margin:0;color:#a8b7ca;font-size:15px;line-height:1.7}
.badges{display:flex;gap:8px;flex-wrap:wrap;margin-top:20px}
.badge{font-size:11px;font-weight:700;color:#d8e4f3;padding:7px 10px;border:1px solid var(--line);border-radius:999px;background:rgba(255,255,255,.035)}
.badge.safe{color:#6ee7d7;border-color:rgba(20,184,166,.3);background:rgba(20,184,166,.08)}
.badge.blocked{color:#fca5a5;border-color:rgba(248,113,113,.35);background:rgba(248,113,113,.10)}
.section-label{margin:28px 0 10px;color:#7f91aa;font-size:11px;font-weight:800;letter-spacing:.16em;text-transform:uppercase}
div[data-testid="stMetric"]{padding:19px 20px;border:1px solid var(--line);border-radius:16px;background:linear-gradient(145deg,rgba(22,38,61,.9),rgba(12,26,44,.9));box-shadow:0 12px 36px rgba(0,0,0,.13)}
div[data-testid="stMetricLabel"]{color:#92a4ba}
div[data-testid="stMetricValue"]{letter-spacing:-.03em}
.score-red div[data-testid="stMetric"]{border-top:2px solid #f97366}
.score-blue div[data-testid="stMetric"]{border-top:2px solid #4e8df5}
.quiet-card{padding:16px 18px;border:1px solid var(--line);border-radius:14px;background:rgba(13,28,47,.72);color:#a9b8ca;font-size:13px;line-height:1.65}
.status-ok{padding:12px 14px;border-radius:12px;background:rgba(20,184,166,.10);border:1px solid rgba(20,184,166,.25);color:#67e8d5;font-size:12px;font-weight:700}
.status-bad{padding:12px 14px;border-radius:12px;background:rgba(248,113,113,.1);border:1px solid rgba(248,113,113,.25);color:#fca5a5;font-size:12px;font-weight:700}
.timeline-row{display:grid;grid-template-columns:58px 175px 1fr;gap:12px;align-items:center;padding:9px 12px;margin:5px 0;border-left:2px solid rgba(20,184,166,.35);background:rgba(255,255,255,.025);border-radius:0 10px 10px 0}
.timeline-step{color:#5eead4;font-family:monospace;font-size:12px}.timeline-event{font-size:12px;font-weight:750;color:#d8e5f3}.timeline-meta{font-size:11px;color:#778ba5}
.stButton>button{border:0;border-radius:11px;background:linear-gradient(120deg,#2e5aac,#14b8a6);color:white;font-weight:800;min-height:44px;box-shadow:0 10px 25px rgba(20,184,166,.18)}
.stButton>button:hover{color:white;border:0;filter:brightness(1.08)}
div[data-testid="stDataFrame"]{border:1px solid var(--line);border-radius:13px;overflow:hidden}
[data-baseweb="tab-list"]{gap:4px;background:rgba(10,22,38,.75);padding:5px;border-radius:13px}
[data-baseweb="tab"]{height:40px;border-radius:9px;padding:0 16px}
.footer-note{margin-top:28px;padding:18px 0;border-top:1px solid var(--line);font-size:11px;color:#667991}
.rt-card{padding:18px 18px 6px;margin:12px 0;border:1px solid var(--line);border-radius:16px;background:linear-gradient(150deg,rgba(20,36,58,.92),rgba(11,24,41,.92))}
.rt-head{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:4px}
.rt-title{font-size:15px;font-weight:800;color:#e6eefa;letter-spacing:-.01em}
.rt-badge{font-size:10px;font-weight:800;padding:4px 9px;border-radius:999px;white-space:nowrap}
.rt-success{background:rgba(248,113,113,.14);color:#fca5a5;border:1px solid rgba(248,113,113,.3)}
.rt-partial{background:rgba(250,204,21,.12);color:#fde68a;border:1px solid rgba(250,204,21,.28)}
.rt-failure{background:rgba(20,184,166,.12);color:#6ee7d7;border:1px solid rgba(20,184,166,.3)}
.rt-sub{font-size:11px;color:#8399b4;margin-bottom:12px;font-family:monospace}
.rt-sec{margin:11px 0 0}
.rt-sec-title{font-size:10px;font-weight:800;letter-spacing:.13em;color:#5eead4;text-transform:uppercase;margin-bottom:5px}
.rt-item{font-size:12.5px;line-height:1.65;color:#bccbdd;padding:3px 0 3px 11px;border-left:2px solid rgba(148,163,184,.16)}
.tg-pill{display:inline-block;font-size:10px;font-weight:800;padding:5px 9px;border-radius:999px;margin-bottom:8px}
@media(max-width:700px){.rt-card{padding:15px 14px 4px}.rt-item{font-size:12px}}
@media(max-width:700px){.block-container{padding:1rem}.hero{padding:25px 22px}.timeline-row{grid-template-columns:44px 1fr}.timeline-meta{grid-column:2}}
</style>
""",
    unsafe_allow_html=True,
)


def safety_status() -> tuple[bool, str]:
    try:
        verify_config_hash()
        run_startup_checks()
        return True, "해시 잠금과 안전 불변식이 모두 정상입니다."
    except SafetyViolation as exc:
        return False, str(exc)


def telegram_secrets() -> dict[str, Any]:
    """Read [telegram] from st.secrets. Missing secrets must never break the app."""
    try:
        section = st.secrets["telegram"]
    except Exception:
        return {}
    try:
        return dict(section)
    except Exception:
        return {}


TELEGRAM_RAW = telegram_secrets()
TELEGRAM_STATE = telegram_status(TELEGRAM_RAW)
TELEGRAM_STATE_LABEL = {
    "active": ("활성", "rt-failure"),
    "inactive": ("비활성", "rt-partial"),
    "missing": ("설정 누락", "rt-partial"),
}


REPORTING_BADGE = {
    "active": "REPORTING · TELEGRAM ONLY",
    "inactive": "REPORTING · OFFLINE",
    "missing": "REPORTING · OFFLINE",
}


def deliver_report(report, trigger: str) -> None:
    """Send once. A delivery problem may never break the match result."""
    try:
        bundle = st.session_state.get("report_bundle")
        if bundle is None:
            st.session_state["telegram_result"] = (
                "blocked", "보고서 번들이 준비되지 않았습니다.",
            )
            return
        filename, payload, generated_at = bundle
        safe_bundle = SafeReportBundle(
            filename, payload, build_telegram_summary(report, generated_at)
        )
        outcome = send_report_bundle(
            safe_bundle, build_credentials(TELEGRAM_RAW)
        )
        st.session_state["telegram_result"] = (outcome.status, outcome.detail)
    except Exception:
        st.session_state["telegram_result"] = (
            "failed",
            "전송 모듈에서 처리되지 않은 오류가 발생했습니다.",
        )
    if trigger == AUTO:
        # Mark this match as auto-delivered so a rerun cannot repeat it.
        st.session_state["auto_sent_token"] = st.session_state.get("report_token")


safe, safety_message = safety_status()

with st.sidebar:
    st.markdown("### ◈ Aurio Range")
    st.caption("폐쇄형 계정탈취 방어 실험실")
    st.markdown(
        f'<div class="{"status-ok" if safe else "status-bad"}">'
        f'{"● SAFETY GATE · PASS" if safe else "● SAFETY GATE · BLOCKED"}<br>'
        f'<span style="font-weight:500;opacity:.78">{safety_message}</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown("#### 경기 구성")
    difficulty_label = st.selectbox(
        "난이도",
        ["Mixed", "Easy", "Medium", "Hard"],
        help="Mixed는 세 난이도를 모두 실행합니다.",
    )
    strictness = st.select_slider(
        "탐지 엄격도",
        options=["permissive", "balanced", "strict"],
        value="balanced",
    )
    profiles = st.multiselect(
        "합성 사용자",
        ["cautious", "average", "careless"],
        default=["cautious", "average", "careless"],
    )
    fixed_seed = st.toggle("고정 시드 사용", value=True)
    seed_value = st.number_input(
        "시드",
        min_value=1,
        max_value=2_147_483_646,
        value=20260731,
        step=1,
        disabled=not fixed_seed,
    )
    run_clicked = st.button(
        "경기 실행",
        width="stretch",
        disabled=not safe or not profiles,
        type="primary",
    )
    st.caption("각 실행은 이 브라우저 세션의 독립 인메모리 DB에서만 처리됩니다.")

    st.markdown("#### 보고서 전송")
    state_text, state_class = TELEGRAM_STATE_LABEL[TELEGRAM_STATE]
    st.markdown(
        f'<span class="tg-pill {state_class}">TELEGRAM · {state_text}</span>',
        unsafe_allow_html=True,
    )
    pin_ready = owner_pin_configured(TELEGRAM_RAW)
    unlocked = bool(st.session_state.get("owner_verified", False))

    if not pin_ready:
        unlocked = False
        st.session_state["owner_verified"] = False
        st.caption(
            "관리자 PIN이 설정되지 않아 전송이 잠겨 있습니다. "
            "st.secrets의 [telegram] owner_pin을 설정하면 열립니다."
        )
    elif unlocked:
        st.caption("✅ 관리자 인증됨 · 현재 브라우저 세션 동안 유지")
    else:
        pin_input = st.text_input(
            "관리자 PIN",
            type="password",
            key="owner_pin_input",
            help="한 번 인증하면 현재 브라우저 세션 동안 다시 입력하지 않습니다.",
        )
        if pin_input:
            if verify_owner_pin(TELEGRAM_RAW, pin_input):
                st.session_state["owner_verified"] = True
                st.rerun()
            else:
                st.caption("PIN이 일치하지 않습니다.")

    can_send = safe and unlocked and TELEGRAM_STATE == "active"
    auto_send = st.checkbox(
        "경기 종료 후 자동 전송",
        value=False,
        disabled=not can_send,
        help="공개 앱 보호를 위해 기본값은 꺼짐이며 관리자 PIN이 맞아야 켤 수 있습니다.",
    )
    manual_send = st.button(
        "이번 경기 보고서 전송",
        width="stretch",
        disabled=not can_send or "red_report" not in st.session_state,
    )
    st.markdown("#### Adaptive Red Lab")
    evolution_on = st.checkbox("Adaptive Red 활성화", value=False)
    gen_count = st.slider("세대 수", 1, 10, 3, disabled=not evolution_on)
    pop_size = st.slider("세대당 후보", 2, 30, 8, disabled=not evolution_on)
    train_seeds = st.slider("training seed 수", 1, 6, 2, disabled=not evolution_on)
    eval_seeds = st.slider("hidden evaluation seed 수", 1, 6, 2,
                           disabled=not evolution_on)
    max_matches = st.slider("최대 경기 수", 10, 2000, 240, step=10,
                            disabled=not evolution_on)
    max_seconds = st.slider("최대 실행 시간(초)", 10, 900, 90, step=10,
                            disabled=not evolution_on)
    min_novelty = st.slider("최소 novelty", 0.0, 1.0, 0.05, step=0.01,
                            disabled=not evolution_on)
    min_repro = st.slider("최소 reproducibility", 0.0, 1.0, 0.5, step=0.05,
                          disabled=not evolution_on)
    evolve_clicked = st.button(
        "Red 진화 실행", width="stretch", disabled=not safe or not evolution_on
    )
    best_run_clicked = st.button(
        "현재 최고 전략으로 경기 실행",
        width="stretch",
        disabled=not safe or "evolution_outcome" not in st.session_state,
    )
    reset_clicked = st.button("진화 상태 초기화", width="stretch")
    if reset_clicked:
        for key in ("evolution_outcome", "evolution_summary"):
            st.session_state.pop(key, None)
        st.caption("진화 상태를 초기화했습니다.")

    result_state = st.session_state.get("telegram_result")
    if result_state:
        status_text, status_detail = result_state
        renderer = st.success if status_text == "sent" else st.warning
        renderer(f"전송 상태: {status_text} · {status_detail}")

if run_clicked:
    with st.spinner("폐쇄형 시뮬레이션을 실행하고 있습니다…"):
        match_result = run_match(
            difficulty=difficulty_label.lower(),
            strictness=strictness,
            profiles=profiles,
            seed=int(seed_value) if fixed_seed else None,
        )
    st.session_state["match_result"] = match_result
    st.session_state["red_report"] = build_red_report(
        match_result, st.session_state.get("evolution_summary")
    )
    st.session_state["report_token"] = st.session_state.get("report_token", 0) + 1
    st.session_state.pop("telegram_result", None)
    st.session_state.pop("report_bundle", None)
    st.session_state.pop("bundle_error", None)
    try:
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        filename, payload = build_bundle(
            match_result, st.session_state["red_report"]
        )
        st.session_state["report_bundle"] = (filename, payload, generated_at)
    except Exception as error:
        # A bundling problem must never fail the match itself.
        st.session_state["bundle_error"] = str(error)[:300]

if evolve_clicked:
    with st.spinner("Adaptive Red 전략을 진화시키고 있습니다…"):
        outcome = run_evolution(
            clamp_config(
                EvolutionConfig(
                    generations=int(gen_count),
                    population_size=int(pop_size),
                    training_seed_count=int(train_seeds),
                    evaluation_seed_count=int(eval_seeds),
                    profiles=tuple(profiles),
                    difficulty=difficulty_label.lower(),
                    strictness=strictness,
                    max_matches=int(max_matches),
                    max_seconds=float(max_seconds),
                    min_novelty=float(min_novelty),
                    min_reproducibility=float(min_repro),
                    base_seed=int(seed_value) if fixed_seed else 20260731,
                )
            )
        )
    st.session_state["evolution_outcome"] = outcome
    st.session_state["evolution_summary"] = build_evolution_summary(outcome)

if best_run_clicked and "evolution_outcome" in st.session_state:
    outcome = st.session_state["evolution_outcome"]
    with st.spinner("최고 전략으로 경기를 실행하고 있습니다…"):
        match_result = run_match(
            difficulty=difficulty_label.lower(),
            strictness=strictness,
            profiles=profiles,
            seed=int(seed_value) if fixed_seed else None,
            strategy=outcome.get("best_strategy_fields"),
        )
    st.session_state["match_result"] = match_result
    st.session_state["red_report"] = build_red_report(
        match_result, st.session_state.get("evolution_summary")
    )
    st.session_state["report_token"] = st.session_state.get("report_token", 0) + 1
    st.session_state.pop("telegram_result", None)
    st.session_state.pop("report_bundle", None)
    try:
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        filename, payload = build_bundle(
            match_result, st.session_state["red_report"]
        )
        st.session_state["report_bundle"] = (filename, payload, generated_at)
    except Exception as error:
        st.session_state["bundle_error"] = str(error)[:300]

trigger = AUTO if run_clicked else MANUAL if manual_send else None
decision = plan_delivery(
    trigger,
    can_send=can_send,
    auto_send_enabled=bool(auto_send),
    report_token=st.session_state.get("report_token"),
    already_sent_token=st.session_state.get("auto_sent_token"),
)
if decision.should_send:
    deliver_report(st.session_state["red_report"], trigger)

safety_badge_class = "safe" if safe else "blocked"
safety_badge_text = "안전 게이트 통과" if safe else "안전 게이트 차단"
reporting_badge = REPORTING_BADGE[TELEGRAM_STATE]

st.markdown(
    f"""
<section class="hero">
  <div class="kicker">CLOSED DEFENSE SIMULATION · SEED-SAFE</div>
  <h1>Aurio <span style="color:#5eead4">Range</span></h1>
  <p>공식 알림과 외형이 같은 합성 위조 알림을 시스템 신호로 구분하고,
  사용자의 검증·경고 이탈·제출 행동과 Blue의 사전 탐지·사후 봉쇄를 단계별로 관찰합니다.</p>
  <div class="badges">
    <span class="badge {safety_badge_class}">● {safety_badge_text}</span>
    <span class="badge">SIMULATION ENGINE · NO EGRESS</span>
    <span class="badge">{reporting_badge}</span>
    <span class="badge">NO LLM</span>
    <span class="badge">IN-MEMORY SQLITE</span>
    <span class="badge">NO CREDENTIAL SECRETS</span>
  </div>
</section>
""",
    unsafe_allow_html=True,
)

if "match_result" not in st.session_state:
    left, right = st.columns([1.35, 1])
    with left:
        st.markdown('<div class="section-label">READY TO RUN</div>', unsafe_allow_html=True)
        st.markdown("### 첫 경기를 실행해 보세요")
        st.write(
            "왼쪽에서 난이도와 탐지 엄격도를 선택한 뒤 **경기 실행**을 누르면 "
            "Red, Blue, User, Judge가 한 번의 폐쇄형 경기를 진행합니다."
        )
    with right:
        st.markdown('<div class="section-label">SAFETY MODEL</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="quiet-card">실제 이메일·SNS·외부 도메인에 연결하지 않습니다. '
            '제출은 텍스트가 아닌 행동 플래그로만 기록되고, 경기가 끝나면 DB 연결도 닫힙니다.</div>',
            unsafe_allow_html=True,
        )
    st.stop()

result: dict[str, Any] = st.session_state["match_result"]
scores = result["scores"]
metrics = result["metrics"]

st.markdown('<div class="section-label">MATCH OUTCOME</div>', unsafe_allow_html=True)
score_col1, score_col2, seed_col = st.columns([1, 1, 1.4])
with score_col1:
    st.markdown('<div class="score-red">', unsafe_allow_html=True)
    st.metric("RED SCORE", f"{scores['red']:.0f}")
    st.markdown("</div>", unsafe_allow_html=True)
with score_col2:
    st.markdown('<div class="score-blue">', unsafe_allow_html=True)
    st.metric("BLUE SCORE", f"{scores['blue']:.0f}")
    st.markdown("</div>", unsafe_allow_html=True)
with seed_col:
    st.metric(
        "MATCH SEED",
        str(result["seed"]),
        f"{metrics['n_official']} official · {metrics['n_forged']} forged",
        delta_color="off",
    )

(
    overview_tab,
    report_tab,
    behavior_tab,
    compare_tab,
    timeline_tab,
    audit_tab,
) = st.tabs(
    ["개요", "Red Team 보고서", "행동 분석", "신호 비교", "이벤트 타임라인", "감사·미리보기"]
)

with report_tab:
    report = st.session_state.get("red_report")
    if report is None:
        st.info("경기를 실행하면 Red Team 보고서가 생성됩니다.")
    else:
        st.markdown(
            '<div class="section-label">MATCH REPORT SUMMARY</div>',
            unsafe_allow_html=True,
        )
        headline = summary_metrics(report)
        for start in range(0, len(headline), 2):
            cols = st.columns(2)
            for col, (label, value) in zip(cols, headline[start : start + 2]):
                col.metric(label, value)

        bundle = st.session_state.get("report_bundle")
        st.markdown(
            '<div class="section-label">REPORT DOWNLOADS</div>',
            unsafe_allow_html=True,
        )
        if st.session_state.get("bundle_error"):
            st.warning(
                "보고서 번들 생성에 실패했습니다: "
                f"{st.session_state['bundle_error']}"
            )
        generated_at = bundle[2] if bundle else ""
        st.download_button(
            "Markdown 보고서 다운로드",
            data=build_markdown(report, generated_at).encode("utf-8"),
            file_name=f"aurio-report-{report.summary.seed}.md",
            mime="text/markdown",
            width="stretch",
        )
        st.download_button(
            "JSON 보고서 다운로드",
            data=json.dumps(
                build_report_json(report, generated_at),
                ensure_ascii=False, indent=2,
            ).encode("utf-8"),
            file_name=f"aurio-report-{report.summary.seed}.json",
            mime="application/json",
            width="stretch",
        )
        st.download_button(
            "CSV 지표 다운로드",
            data=build_metrics_csv(report).encode("utf-8"),
            file_name=f"aurio-metrics-{report.summary.seed}.csv",
            mime="text/csv",
            width="stretch",
        )
        if bundle:
            st.download_button(
                "전체 보고서 ZIP 다운로드",
                data=bundle[1],
                file_name=bundle[0],
                mime="application/zip",
                width="stretch",
            )

        if report.evolution is not None and report.evolution.enabled:
            st.markdown(
                '<div class="section-label">ADAPTIVE RED LINEAGE</div>',
                unsafe_allow_html=True,
            )
            evo = report.evolution
            cols = st.columns(2)
            cols[0].metric("세대", evo.generations)
            cols[1].metric("최고 평가 fitness", f"{evo.best_evaluation_fitness:.2f}")
            for node in evo.lineage:
                st.markdown(
                    '<div class="rt-card">'
                    f'<div class="rt-title">{node.strategy_id} · {node.keep_or_drop}</div>'
                    f'<div class="rt-sub">gen {node.generation} · 부모 '
                    f'{node.parent_strategy_id or "—"} · 변경 '
                    f'{", ".join(node.changed_fields) or "—"}</div>'
                    f'<div class="rt-item">훈련 {node.training_fitness:.2f} / '
                    f'평가 {node.evaluation_fitness:.2f} '
                    f'(Δ{node.delta_from_parent:+.2f})</div>'
                    f'<div class="rt-item">{node.change_reason}</div>'
                    f'<div class="rt-item">{node.user_behavior_summary}</div>'
                    "</div>",
                    unsafe_allow_html=True,
                )

        st.markdown(
            '<div class="section-label">ATTEMPT REPORTS</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            "본문·URL·서명 토큰·계정 식별자는 보고서에 포함되지 않습니다. "
            "발신자와 목적지는 분류 라벨로만 표시됩니다."
        )
        badge_class = {
            "success": "rt-success",
            "partial": "rt-partial",
            "failure": "rt-failure",
        }
        for card in build_cards(report):
            blocks = [
                '<div class="rt-card">',
                '<div class="rt-head">',
                f'<span class="rt-title">{card["title"]}</span>',
                f'<span class="rt-badge {badge_class[card["outcome"]]}">'
                f'{card["badge"]}</span>',
                "</div>",
                f'<div class="rt-sub">{card["subtitle"]}</div>',
            ]
            for section in card["sections"]:
                blocks.append('<div class="rt-sec">')
                blocks.append(
                    f'<div class="rt-sec-title">{section["title"]}</div>'
                )
                for item in section["items"]:
                    blocks.append(f'<div class="rt-item">{item}</div>')
                blocks.append("</div>")
            blocks.append("</div>")
            st.markdown("".join(blocks), unsafe_allow_html=True)

        st.markdown(
            '<div class="section-label">RESEARCH CONCLUSIONS</div>',
            unsafe_allow_html=True,
        )
        for index, text in enumerate(report.conclusions, 1):
            st.markdown(
                f'<div class="rt-item">{index}. {text}</div>',
                unsafe_allow_html=True,
            )

with overview_tab:
    st.markdown('<div class="section-label">RAW METRICS</div>', unsafe_allow_html=True)
    labels = [
        ("false_positive", "False Positive"),
        ("friction", "Friction"),
        ("false_negative", "False Negative"),
        ("warning_escape", "Warning Escape"),
        ("harm_click", "Harm · Click"),
        ("harm_submit", "Harm · Submit"),
        ("credential_exposure", "Synthetic Credential Exposure"),
        ("takeover_success", "Simulated Takeover Success"),
        ("exposure_prevented_by_prior_lock", "Exposure Prevented"),
        ("containment_success", "Containment"),
        ("overreaction", "Over-reaction"),
        ("user_saved", "User Saved"),
        ("official_submission", "Official Submission"),
        ("forged_submission", "Forged Submission"),
    ]
    for start in range(0, len(labels), 3):
        cols = st.columns(3)
        for col, (key, label) in zip(cols, labels[start : start + 3]):
            col.metric(label, metrics[key])
    latency_a, latency_b = st.columns(2)
    latency_a.metric(
        "평균 탐지 단계",
        "—" if metrics["avg_detection_steps"] is None
        else f"{metrics['avg_detection_steps']:.1f}",
    )
    latency_b.metric(
        "평균 봉쇄 단계",
        "—" if metrics["avg_containment_steps"] is None
        else f"{metrics['avg_containment_steps']:.1f}",
    )
    st.info("지연값은 참고 지표입니다. MVP의 Red·Blue 점수에는 포함되지 않습니다.")

    st.markdown('<div class="section-label">BY DIFFICULTY</div>', unsafe_allow_html=True)
    st.dataframe(
        result["difficulty_metrics"],
        width="stretch",
        hide_index=True,
        column_config={
            "difficulty": "난이도",
            "delivered": "허용",
            "warned": "경고",
            "quarantined": "격리",
            "harm_click": "클릭 피해",
            "harm_submit": "제출 피해",
        },
    )

    operational = [
        {
            "메시지": row["id"],
            "프로필": row["profile"],
            "표시 발신자": row["display_sender_name"],
            "인증 주소": row["auth_sender_address"],
            "위험점수": row["risk_total"],
            "밴드": row["band"],
            "사전조치": row["pre_delivery_action"],
            "사후대응": row["post_action_response"] or "—",
            "전달상태": row["delivery_status"],
        }
        for row in result["messages"]
    ]
    st.markdown('<div class="section-label">BLUE OPERATIONS</div>', unsafe_allow_html=True)
    st.caption("이 표에는 정답 데이터가 없습니다.")
    st.dataframe(operational, width="stretch", hide_index=True)

with behavior_tab:
    st.markdown('<div class="section-label">USER STATE MACHINE</div>', unsafe_allow_html=True)
    profile_rows = []
    for row in result["profile_metrics"]:
        profile_rows.append(
            {
                "프로필": row["profile"],
                "검증률": row["verify_rate"],
                "신고율": row["report_rate"],
                "클릭률": row["click_rate"],
                "제출률": row["submit_rate"],
                "경고 이탈률": row["warning_escape_rate"],
            }
        )
    st.dataframe(
        profile_rows,
        width="stretch",
        hide_index=True,
        column_config={
            key: st.column_config.ProgressColumn(
                key, min_value=0.0, max_value=1.0, format="%.0f%%"
            )
            for key in ("검증률", "신고율", "클릭률", "제출률", "경고 이탈률")
        },
    )
    st.markdown("#### 상태 전환 기록")
    transition_rows = [
        {
            "step": row["step_index"],
            "message": row["message_id"],
            "profile": row["profile"],
            "event": row["action"],
            "transition": f"{row['from_state']} → {row['to_state']}",
        }
        for row in result["user_actions"]
    ]
    st.dataframe(transition_rows, width="stretch", hide_index=True)

with compare_tab:
    st.markdown('<div class="section-label">HARD · SIDE BY SIDE</div>', unsafe_allow_html=True)
    if not result["signal_comparison"]:
        st.warning("Hard 시나리오를 포함해 실행하면 공식·위조 비교가 표시됩니다.")
    else:
        pair = result["signal_comparison"][0]
        official_col, forged_col = st.columns(2)
        with official_col:
            st.markdown("#### 공식 알림")
            st.iframe(pair["official"]["rendered_html"], height=530)
        with forged_col:
            st.markdown("#### 합성 위조 알림")
            st.iframe(pair["forged"]["rendered_html"], height=530)
        st.caption(
            "두 메시지는 같은 브랜드킷과 고정 템플릿으로 렌더됩니다. "
            "Red는 HTML·CSS·JavaScript를 생성하지 않습니다."
        )
        signal_rows = []
        for signal in pair["official"]["signals"]:
            signal_rows.append(
                {
                    "신호": signal,
                    "공식 값": pair["official"]["signals"][signal]["value"],
                    "공식 점수": pair["official"]["signals"][signal]["score"],
                    "위조 값": pair["forged"]["signals"][signal]["value"],
                    "위조 점수": pair["forged"]["signals"][signal]["score"],
                    "Hard 구분력": (
                        "동일"
                        if signal in {"official_event_record", "ingress_channel"}
                        else "독립 신호"
                    ),
                }
            )
        st.dataframe(signal_rows, width="stretch", hide_index=True)
        st.success(
            "Hard에서는 official_event_record와 ingress_channel이 양쪽 동일합니다. "
            "핵심 차이는 sender_auth, signature_validity, destination_ownership입니다."
        )

with timeline_tab:
    st.markdown('<div class="section-label">STEP-INDEXED EVENT QUEUE</div>', unsafe_allow_html=True)
    for event in result["events"]:
        meta = []
        if event["message_id"] is not None:
            meta.append(f"message {event['message_id']}")
        if event["account_id"] is not None:
            meta.append(f"account {event['account_id']}")
        st.markdown(
            f'<div class="timeline-row"><span class="timeline-step">#{event["step_index"]:03d}</span>'
            f'<span class="timeline-event">{event["event_type"]}</span>'
            f'<span class="timeline-meta">{" · ".join(meta) or "match scope"}</span></div>',
            unsafe_allow_html=True,
        )

with audit_tab:
    judge_tab, preview_tab, safety_tab = st.tabs(
        ["Judge 평가", "비대화형 페이지", "안전 이벤트"]
    )
    with judge_tab:
        st.caption("정답과 correct 값은 Judge 영역에서만 결합됩니다.")
        st.dataframe(result["judge_evaluations"], width="stretch", hide_index=True)
    with preview_tab:
        if result["previews"]:
            selected = st.selectbox(
                "합성 위조 페이지",
                options=[row["message_id"] for row in result["previews"]],
                format_func=lambda value: f"메시지 #{value}",
            )
            preview = next(
                row for row in result["previews"] if row["message_id"] == selected
            )
            st.iframe(preview["static_html"], height=520)
            st.caption(
                "폼·입력칸·제출 버튼은 정적 플레이스홀더로 치환됐습니다. "
                "자유 텍스트 입력이나 자격증명 수집 기능은 없습니다."
            )
        else:
            st.info("현재 실행에 표시할 위조 페이지가 없습니다.")
    with safety_tab:
        if result["safety_events"]:
            st.dataframe(result["safety_events"], width="stretch", hide_index=True)
        else:
            st.success("안전 이벤트 없음 · 모든 구조화 Red 산출물이 검증을 통과했습니다.")

st.markdown(
    '<div class="footer-note">AURIO RANGE · CLOSED SYNTHETIC RESEARCH ENVIRONMENT · '
    '각 경기는 세션별 인메모리 SQLite 연결에서 실행되고 종료 즉시 연결이 닫힙니다.</div>',
    unsafe_allow_html=True,
)
