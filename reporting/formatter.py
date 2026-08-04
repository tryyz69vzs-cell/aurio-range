"""Presentation layer: mobile card data for Streamlit and Telegram message text.

This module only reshapes an already-sanitized SafeRedReport. It never reads
the match database and never receives message bodies, markup, or destinations.
Its output is re-checked by the hash-locked sanitizer before delivery.
"""

from __future__ import annotations

from reporting.models import SafeAttemptReport, SafeRedReport


TELEGRAM_MAX_CHARS = 3500

CARD_SECTION_TITLES = (
    "Red 가설",
    "공격 시뮬레이션 개요",
    "Blue 탐지 결과",
    "User 반응",
    "최종 결과",
    "연구 메모",
)

OUTCOME_LABELS = {
    "success": "Red 성공",
    "partial": "부분 성공",
    "failure": "Red 실패",
}

ACTION_LABELS = {
    "allow": "허용",
    "warn": "경고",
    "quarantine": "격리",
}

CONTAINMENT_LABELS = {
    "contained": "봉쇄 완료",
    "partial": "부분 봉쇄",
    "none": "봉쇄 실패",
    "not_required": "봉쇄 불필요",
}

SENDER_LABELS = {
    "registered_official_sender": "등록된 공식 발신자",
    "synthetic_lookalike_sender": "공식 사칭 합성 발신자",
    "unregistered_synthetic_sender": "미등록 합성 발신자",
}

DESTINATION_LABELS = {
    "none": "제출 없음",
    "official_owned": "공식 소유 목적지",
    "synthetic_unowned": "미소유 합성 목적지",
    "internal_capture": "내부 캡처 경로",
}

RECORD_LABELS = {"present": "존재함", "absent": "없음"}

TAKEOVER_LABELS = {
    "takeover_success": "탈취 성공",
    "prevented_by_prior_defense": "선행 방어로 차단",
    "none": "해당 없음",
}


def _yes(value: bool) -> str:
    return "예" if value else "아니오"


def _steps(value: int | None) -> str:
    return "—" if value is None else f"{value}단계"


def summary_metrics(report: SafeRedReport) -> list[tuple[str, str]]:
    """The ten headline counters required at the top of the report screen."""
    summary = report.summary
    return [
        ("Red 점수", f"{summary.red_score:.0f}"),
        ("Blue 점수", f"{summary.blue_score:.0f}"),
        ("위조 시도", str(summary.forged_attempts)),
        ("격리", str(summary.quarantined)),
        ("경고", str(summary.warned)),
        ("허용", str(summary.allowed)),
        ("클릭 피해", str(summary.harm_click)),
        ("제출 피해", str(summary.harm_submit)),
        ("경고 이탈", str(summary.warning_escape)),
        ("봉쇄 성공", str(summary.containment_success)),
        ("합성 자격증명 노출", str(summary.credential_exposure)),
        ("시뮬레이션 계정 탈취", str(summary.takeover_success)),
    ]


def _overview_items(attempt: SafeAttemptReport) -> list[str]:
    items = [
        f"난이도: {attempt.difficulty} · 탐지 엄격도: {attempt.strictness}",
        f"전술 ID: {attempt.tactic_id}",
        f"대상 프로필: {attempt.target_profile}",
        f"시나리오 유형: {attempt.scenario_family}",
        f"발신자 분류: {SENDER_LABELS.get(attempt.sender_class, attempt.sender_class)}",
        f"목적지 분류: {DESTINATION_LABELS.get(attempt.destination_class, attempt.destination_class)}",
        f"공식 사건 기록: {RECORD_LABELS.get(attempt.official_event_record, attempt.official_event_record)}",
    ]
    if attempt.submission_sink != "none":
        items.append(f"제출 도달 지점: {DESTINATION_LABELS['internal_capture']}")
    if attempt.secondary_probe:
        items.append(f"부가 실험: {attempt.secondary_probe}")
    return items


def _detection_items(attempt: SafeAttemptReport) -> list[str]:
    items = [
        f"위험 총점: {attempt.risk_total} · 밴드: {attempt.band}",
        f"사전 조치: {ACTION_LABELS.get(attempt.pre_delivery_action, attempt.pre_delivery_action)}",
        f"전달 상태: {attempt.delivery_status}",
        f"탐지 지연: {_steps(attempt.detection_latency_steps)}",
    ]
    for finding in attempt.decisive_signals:
        items.append(f"핵심 신호 · {finding.signal}: {finding.value} (+{finding.score})")
    if attempt.neutral_signals:
        items.append(f"구분력 없던 신호: {', '.join(attempt.neutral_signals)}")
    items.append(attempt.detection_explanation)
    return items


def _user_items(attempt: SafeAttemptReport) -> list[str]:
    items = [
        f"검증 시도: {_yes(attempt.user_verified)} · 신고: {_yes(attempt.user_reported)}",
        f"클릭: {_yes(attempt.user_clicked)} · 제출: {_yes(attempt.user_submitted)}",
        f"경고 표시: {_yes(attempt.warning_shown)} · 경고 이탈: {_yes(attempt.warning_escape)}",
        f"상태 전환: {' → '.join(attempt.user_states) if attempt.user_states else '전환 없음'}",
        attempt.user_explanation,
    ]
    return items


def _result_items(attempt: SafeAttemptReport) -> list[str]:
    return [
        f"판정: {OUTCOME_LABELS.get(attempt.red_outcome, attempt.red_outcome)}",
        f"합성 자격증명 노출: {attempt.credential_exposure}",
        f"계정 탈취 판정: {TAKEOVER_LABELS.get(attempt.takeover_result, attempt.takeover_result)}",
        f"제출 목적지: {DESTINATION_LABELS.get(attempt.submission_target, attempt.submission_target)}",
        f"제출 시점 계정 상태: {attempt.account_status_at_submit} · 세션: {attempt.session_state_at_submit}",
        f"사후 대응: {attempt.post_action_response}",
        f"봉쇄 결과: {CONTAINMENT_LABELS.get(attempt.containment_result, attempt.containment_result)}"
        f" · 봉쇄 지연: {_steps(attempt.containment_latency_steps)}",
        attempt.outcome_reason,
        attempt.containment_assessment,
    ]


def build_cards(report: SafeRedReport) -> list[dict[str, object]]:
    """One vertical, mobile-friendly card per synthetic forged attempt."""
    cards: list[dict[str, object]] = []
    for attempt in report.attempts:
        cards.append(
            {
                "title": f"위조 시도 #{attempt.attempt_no} · {attempt.tactic_name}",
                "badge": OUTCOME_LABELS.get(attempt.red_outcome, attempt.red_outcome),
                "outcome": attempt.red_outcome,
                "subtitle": (
                    f"{attempt.difficulty} · {attempt.target_profile} · "
                    f"위험 {attempt.risk_total}점 · "
                    f"{ACTION_LABELS.get(attempt.pre_delivery_action, attempt.pre_delivery_action)}"
                ),
                "sections": [
                    {
                        "title": "Red 가설",
                        "items": [attempt.hypothesis, attempt.tactic_research_framing],
                    },
                    {"title": "공격 시뮬레이션 개요", "items": _overview_items(attempt)},
                    {"title": "Blue 탐지 결과", "items": _detection_items(attempt)},
                    {"title": "User 반응", "items": _user_items(attempt)},
                    {"title": "최종 결과", "items": _result_items(attempt)},
                    {"title": "연구 메모", "items": [attempt.research_note]},
                ],
            }
        )
    return cards


def _summary_block(report: SafeRedReport) -> str:
    summary = report.summary
    rows = [f"· {label}: {value}" for label, value in summary_metrics(report)]
    header = (
        "Aurio Range 경기 보고서\n"
        f"시드 {summary.seed} · 난이도 {summary.difficulty_mix} · "
        f"엄격도 {summary.strictness}"
    )
    extra = (
        f"· 오격리: {summary.false_positive} · 마찰 경고: {summary.friction} · "
        f"미탐: {summary.false_negative} · 과잉 대응: {summary.overreaction}\n"
        f"· 공식 목적지 제출: {summary.official_submission} · "
        f"위조 목적지 제출: {summary.forged_submission}\n"
        f"· 선행 방어로 막힌 노출: {summary.exposure_prevented_by_prior_lock} · "
        f"사용자 자체 방어: {summary.user_saved} · 안전 이벤트: {summary.safety_events}"
    )
    return f"{header}\n\n[경기 전체 요약]\n" + "\n".join(rows) + "\n" + extra


def _attempt_block(attempt: SafeAttemptReport) -> str:
    lead = (
        f"[위조 시도 #{attempt.attempt_no}] {attempt.tactic_name} "
        f"({attempt.tactic_id})\n"
        f"판정: {OUTCOME_LABELS.get(attempt.red_outcome, attempt.red_outcome)} · "
        f"난이도 {attempt.difficulty} · 대상 {attempt.target_profile}"
    )
    body = []
    for title, items in (
        ("Red 가설", [attempt.hypothesis]),
        ("개요", _overview_items(attempt)),
        ("Blue 탐지", _detection_items(attempt)),
        ("User 반응", _user_items(attempt)),
        ("최종 결과", _result_items(attempt)),
        ("연구 메모", [attempt.research_note]),
    ):
        body.append(f"◆ {title}")
        body.extend(f"  - {item}" for item in items)
    return lead + "\n" + "\n".join(body)


def _conclusion_block(report: SafeRedReport) -> str:
    rows = [f"{index}. {text}" for index, text in enumerate(report.conclusions, 1)]
    return "[최종 연구 결론]\n" + "\n".join(rows)


def _split_long(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for row in text.split("\n"):
        piece = row[:limit]
        if size + len(piece) + 1 > limit and current:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(piece)
        size += len(piece) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def build_telegram_messages(report: SafeRedReport) -> list[str]:
    """Ordered parts: match summary, then each attempt, then the conclusions."""
    parts: list[str] = list(_split_long(_summary_block(report), TELEGRAM_MAX_CHARS))
    packed: list[str] = []
    for attempt in report.attempts:
        block = _attempt_block(attempt)
        for chunk in _split_long(block, TELEGRAM_MAX_CHARS):
            if packed and len(packed[-1]) + len(chunk) + 2 <= TELEGRAM_MAX_CHARS:
                packed[-1] = f"{packed[-1]}\n\n{chunk}"
            else:
                packed.append(chunk)
    parts.extend(packed)
    parts.extend(_split_long(_conclusion_block(report), TELEGRAM_MAX_CHARS))

    total = len(parts)
    return [f"[{index}/{total}]\n{body}" for index, body in enumerate(parts, 1)]
