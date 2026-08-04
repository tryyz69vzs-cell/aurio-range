"""Build the operator-facing Red Team report from a completed match result.

Runs only after the match and the Judge evaluation have finished. It reads the
already-returned result dictionary; it never touches the live match database,
never renders markup, and never receives message bodies or destinations.
Every produced string goes through the hash-locked sanitizer before use.
"""

from __future__ import annotations

from typing import Any, Mapping

from engine.detection_params import BAND_THRESHOLDS
from reporting.models import (
    SafeAttemptReport,
    SafeMatchSummary,
    SafeRedReport,
    SafeSignalFinding,
)
from reporting.sanitizer import (
    assert_report_is_clean,
    classify_destination,
    classify_official_record,
    classify_sender,
    clean_text,
)


GENERIC_TACTIC = {
    "name": "미분류 합성 전술",
    "framing": "unclassified_probe: 전술 목록에 없는 합성 시나리오로 방어 반응을 관찰하는 실험",
    "hypothesis": "분류되지 않은 합성 전술에 대해 방어 신호 조합이 어떻게 반응하는가",
}

TACTIC_LIBRARY: dict[str, dict[str, str]] = {
    "obvious-spoof": {
        "name": "명백한 발신 위조",
        "framing": (
            "direct_spoof_control: 기본 신호가 모두 어긋난 대조군으로 "
            "방어의 탐지 하한선을 재는 실험"
        ),
        "hypothesis": (
            "발신 인증·서명·목적지 소유권이 동시에 어긋나면 "
            "방어가 합성 사용자 노출 이전에 차단하는가"
        ),
    },
    "trusted-relay-abuse": {
        "name": "신뢰 유입 경로 남용",
        "framing": (
            "visual_trust_abuse: 공식과 동일한 Aurio 브랜드 외형과 승인된 합성 유입 "
            "경로가 사용자 판단에 미치는 영향 실험"
        ),
        "hypothesis": (
            "외형과 유입 경로가 공식과 같을 때, 공식 사건 기록의 부재만으로 "
            "방어가 위조를 구분할 수 있는가"
        ),
    },
    "event-shadowing": {
        "name": "사건 그림자",
        "framing": (
            "event_shadowing: 실제 합성 보안 사건 직후 같은 사건을 사칭해 "
            "사건 기록 신호를 무력화하는 실험"
        ),
        "hypothesis": (
            "사건 기록 신호가 무력화된 상태에서 발신 인증·서명·목적지 소유권만으로 "
            "방어가 성립하는가"
        ),
    },
}

SECONDARY_PROBE_FRAMING = (
    "warning_escape_test: Blue의 경고 이후 합성 사용자 유형별 경고 무시 행동 실험"
)

PROFILE_TRAITS = {
    "cautious": "검증 시도율이 가장 높고 경고 순응률도 가장 높은 유형",
    "average": "상황에 따라 검증과 클릭이 갈리는 중간 유형",
    "careless": "긴급 표현에 크게 반응하고 검증을 거의 하지 않는 유형",
}


def _signal_findings(signals: Mapping[str, Any]) -> tuple[SafeSignalFinding, ...]:
    ordered = sorted(
        signals.items(), key=lambda item: (-int(item[1]["score"]), item[0])
    )
    return tuple(
        SafeSignalFinding(
            signal=name,
            value=str(payload["value"]),
            score=int(payload["score"]),
        )
        for name, payload in ordered
    )


def _capture_snapshot(result, message_id: int) -> dict[str, str]:
    """Submit-time snapshot, or a neutral placeholder when nothing was submitted."""
    for row in result.get("capture_events", []):
        if int(row["message_id"]) == int(message_id):
            return {
                "submission_target": str(row["submission_target"]),
                "account_status_at_submit": str(row["account_status_at_submit"]),
                "session_state_at_submit": str(row["session_state_at_submit"]),
            }
    return {
        "submission_target": "none",
        "account_status_at_submit": "none",
        "session_state_at_submit": "none",
    }


def _actions_for(result: Mapping[str, Any], message_id: int) -> list[dict[str, Any]]:
    return [
        row
        for row in result["user_actions"]
        if int(row["message_id"]) == int(message_id)
    ]


def _describe_detection(
    attempt_signals: tuple[SafeSignalFinding, ...],
    risk_total: int,
    band: str,
    action: str,
    strictness: str,
) -> str:
    scoring = [item for item in attempt_signals if item.score > 0]
    neutral = [item.signal for item in attempt_signals if item.score == 0]
    limits = BAND_THRESHOLDS[strictness]
    if scoring:
        drivers = ", ".join(
            f"{item.signal}({item.value}, +{item.score})" for item in scoring[:3]
        )
        lead = f"위험 점수를 만든 핵심 신호는 {drivers} 입니다."
    else:
        lead = "위험 점수를 올린 신호가 없습니다."
    tail = (
        f"점수를 올리지 못한 신호는 {', '.join(neutral)} 로, "
        "이 시도에서는 구분력이 없었습니다."
        if neutral
        else "모든 신호가 위험 점수에 기여했습니다."
    )
    return clean_text(
        f"총점 {risk_total}점으로 {strictness} 임계값(경고 {limits['medium']}점, "
        f"격리 {limits['high']}점) 기준 {band} 밴드가 되어 사전 조치 {action} 이 "
        f"적용됐습니다. {lead} {tail}"
    )


def _describe_user(
    profile: str,
    states: tuple[str, ...],
    warning_shown: bool,
    verified: bool,
    record_state: str,
    clicked: bool,
    submitted: bool,
    reported: bool,
) -> str:
    parts: list[str] = [f"{profile} 프로필은 {PROFILE_TRAITS.get(profile, '규칙 기반 합성 유형')}입니다."]
    if warning_shown:
        if "WARN_IGNORED" in states:
            parts.append("Blue의 경고 배너가 붙었지만 이를 무시하고 진행했습니다.")
        else:
            parts.append("Blue의 경고 배너를 수용하고 진행을 멈췄습니다.")
    if verified:
        if record_state == "present":
            parts.append(
                "공식 앱에서 사건 기록을 확인했고 기록이 실제로 존재해 "
                "메시지의 주장이 사실처럼 보였습니다."
            )
        else:
            parts.append(
                "공식 앱에서 사건 기록을 확인했으나 기록이 없어 의심 신호를 얻었습니다."
            )
    else:
        parts.append("공식 기록을 확인하지 않은 채 메시지 표면만 보고 판단했습니다.")
    if submitted:
        parts.append("결국 합성 제출 행동까지 진행했습니다.")
    elif clicked:
        parts.append("링크를 눌렀지만 제출 직전에 중단했습니다.")
    elif reported:
        parts.append("스스로 신고해 방어에 기여했습니다.")
    else:
        parts.append("행동하지 않고 무시했습니다.")
    return clean_text(" ".join(parts))


def _describe_containment(
    containment_result: str,
    response: str,
    latency: int | None,
    clicked: bool,
    submitted: bool,
) -> str:
    if containment_result == "not_required":
        return clean_text(
            "합성 사용자의 위험 행동이 없어 사후 봉쇄가 필요하지 않았습니다. "
            "이 경우 방어 평가는 사전 검사 단계에서 끝납니다."
        )
    delay = (
        f" 봉쇄 지연은 {latency}단계입니다." if latency is not None else ""
    )
    if containment_result == "contained":
        return clean_text(
            "제출 이후 위조 페이지 차단, 합성 세션 폐기, 계정 보호 상태 전환이 "
            f"모두 완료되어 봉쇄가 충분했습니다. 기록된 사후 대응은 {response} 입니다.{delay}"
        )
    if containment_result == "partial":
        trigger = "제출" if submitted else "클릭"
        return clean_text(
            f"{trigger} 이후 일부 조치만 적용됐습니다. 기록된 사후 대응은 {response} 이며, "
            f"계정 보호 상태 전환까지는 도달하지 못했습니다.{delay}"
        )
    return clean_text(
        "위험 행동이 있었지만 사후 봉쇄 조치가 완료되지 않았습니다. "
        f"기록된 사후 대응은 {response} 입니다.{delay}"
    )


def _research_note(
    exposure: bool,
    takeover: bool,
    warning_escape: bool,
    false_negative: bool,
    user_saved: bool,
    quarantined: bool,
    containment_result: str,
    strictness: str,
) -> str:
    if takeover:
        return clean_text(
            "합성 자격증명 노출과 시뮬레이션 계정 탈취까지 이어진 전술입니다. "
            "탐지 엄격도를 한 단계 높였을 때 이 전술이 사전 격리되는지, 그리고 "
            "공식 알림 오격리가 몇 건 늘어나는지 같은 시드로 나란히 측정할 것."
        )
    if exposure:
        return clean_text(
            "합성 자격증명 노출은 발생했지만 제출 시점에 계정이 이미 보호 상태여서 "
            "탈취로는 이어지지 않았습니다. 사전 방어가 노출 자체를 막지 못한 이유와, "
            "선행 보호가 없었다면 결과가 달라졌을지 같은 시드로 확인할 것."
        )
    if warning_escape:
        return clean_text(
            "경고 판정은 옳았지만 사용자가 경고를 넘겼습니다. 경고 문구 자체보다 "
            "경고 이후 공식 앱 확인을 강제하는 흐름이 유효한지 프로필별로 비교할 것."
        )
    if false_negative and user_saved:
        return clean_text(
            "방어 탐지는 실패했으나 합성 사용자의 신고가 피해를 막았습니다. "
            "신고 경로를 더 잘 노출했을 때 다른 프로필에서도 재현되는지 확인할 것."
        )
    if false_negative:
        return clean_text(
            "허용 판정으로 사용자에게 그대로 전달됐습니다. 허용을 만든 신호 조합을 기록하고, "
            "destination_ownership 가중치를 올렸을 때 오탐 증가폭이 얼마인지 함께 볼 것."
        )
    if quarantined:
        return clean_text(
            f"{strictness} 기준에서 사전 격리에 성공했습니다. 같은 전술을 더 느슨한 "
            "임계값에서 재실행해 방어 여유폭이 어디서 사라지는지 측정할 것."
        )
    if containment_result in {"partial", "none"}:
        return clean_text(
            "사후 봉쇄가 완결되지 않았습니다. 클릭 단계 대응에서도 세션 폐기까지 "
            "확장했을 때 사용자 마찰이 얼마나 늘어나는지 확인할 것."
        )
    return clean_text(
        "이 전술의 결과를 다른 프로필과 엄격도 조합에서 반복 실행해 "
        "단일 경기 결과가 아닌 누적 경향으로 확인할 것."
    )


def _outcome(
    action: str,
    clicked: bool,
    submitted: bool,
    reported: bool,
    exposure: bool,
    takeover: bool,
    prevented: bool,
) -> tuple[str, str]:
    if action == "quarantine":
        return "failure", clean_text(
            "사전 검사에서 격리되어 합성 사용자에게 도달하지 못했습니다. "
            "방어가 노출 이전에 성립했습니다."
        )
    if submitted:
        if takeover:
            detail = (
                "합성 자격증명이 캡처 지점에 도달했고 제출 시점의 계정이 활성 상태여서 "
                "시뮬레이션상 계정 탈취 조건까지 충족됐습니다."
            )
        elif prevented:
            detail = (
                "합성 자격증명 노출은 발생했지만 제출 시점에 계정이 이미 보호 상태여서 "
                "탈취로는 이어지지 않았습니다. 노출과 탈취는 별개 지표로 집계됩니다."
            )
        elif exposure:
            detail = "합성 자격증명 노출이 기록됐습니다."
        else:
            detail = (
                "제출 행동은 있었지만 캡처 지점에 도달하지 않아 노출로 집계되지 "
                "않았습니다."
            )
        return "success", clean_text(
            f"사전 방어를 통과하고 사용자 행동을 끝까지 유도했습니다. {detail}"
        )
    if clicked:
        return "partial", clean_text(
            "사전 방어를 통과하고 링크 클릭까지 유도했으나 제출 직전에 중단됐습니다."
        )
    if reported:
        return "failure", clean_text(
            "사용자에게 전달되기는 했으나 합성 사용자가 신고해 시도가 무산됐습니다."
        )
    return "partial", clean_text(
        "사전 방어는 통과했지만 합성 사용자의 행동을 전혀 유도하지 못했습니다."
    )


def _conclusions(
    summary: SafeMatchSummary, attempts: tuple[SafeAttemptReport, ...]
) -> tuple[str, ...]:
    notes: list[str] = []
    lead = "Red" if summary.red_score > summary.blue_score else "Blue"
    notes.append(
        clean_text(
            f"이번 경기의 종합 점수는 Red {summary.red_score:.0f} 대 "
            f"Blue {summary.blue_score:.0f} 으로 {lead} 가 앞섰습니다. "
            f"위조 시도 {summary.forged_attempts}건 중 격리 {summary.quarantined}건, "
            f"경고 {summary.warned}건, 허용 {summary.allowed}건입니다."
        )
    )
    successes = [a for a in attempts if a.red_outcome == "success"]
    if successes:
        worst = successes[0]
        notes.append(
            clean_text(
                f"가장 위험했던 전술은 {worst.tactic_name}({worst.tactic_id}) 이며 "
                f"{worst.target_profile} 프로필에서 제출까지 이어졌습니다. "
                f"이 시도의 위험 총점은 {worst.risk_total}점으로 "
                f"{worst.band} 밴드였습니다."
            )
        )
    else:
        notes.append(
            clean_text(
                "이번 경기에서는 제출까지 도달한 전술이 없어, 방어가 모든 시도를 "
                "행동 이전 또는 행동 중간에 멈췄습니다."
            )
        )
    notes.append(
        clean_text(
            f"방어 비용 지표는 오격리 {summary.false_positive}건, "
            f"마찰 경고 {summary.friction}건, 미탐 {summary.false_negative}건입니다. "
            "임계값을 조정할 때는 미탐 감소와 오격리 증가를 항상 함께 볼 것."
        )
    )
    escapes = [a for a in attempts if a.warning_escape]
    if escapes:
        profiles = sorted({a.target_profile for a in escapes})
        notes.append(
            clean_text(
                f"경고 이탈이 {len(escapes)}건 발생했고 해당 프로필은 "
                f"{', '.join(profiles)} 입니다. 경고 이후 행동 차단 실험이 필요합니다."
            )
        )
    notes.append(
        clean_text(
            f"다음 경기 제안: 같은 시드 {summary.seed} 를 유지한 채 탐지 엄격도만 "
            "바꿔 재실행하고, 미탐과 오격리가 교차하는 지점을 기록할 것."
        )
    )
    return tuple(notes)


def build_red_report(result: Mapping[str, Any]) -> SafeRedReport:
    """Create the sanitized Red Team report for a finished match."""
    if not isinstance(result, Mapping) or "judge_evaluations" not in result:
        raise ValueError("완료된 경기 결과 객체가 필요합니다.")

    strictness = str(result.get("strictness", "balanced"))
    difficulty_mix = str(result.get("difficulty", "mixed"))
    messages_by_id = {int(row["id"]): row for row in result["messages"]}

    attempts: list[SafeAttemptReport] = []
    quarantined = warned = allowed = 0
    attempt_no = 0
    for evaluation in result["judge_evaluations"]:
        if str(evaluation["ground_truth"]) != "forged":
            continue
        message = messages_by_id[int(evaluation["message_id"])]
        signals = message["signals"]
        action = str(message["pre_delivery_action"])
        if action == "quarantine":
            quarantined += 1
        elif action == "warn":
            warned += 1
        else:
            allowed += 1

        attempt_no += 1
        actions = _actions_for(result, int(evaluation["message_id"]))
        states = tuple(str(row["action"]) for row in actions)
        clicked = "USER_CLICK" in states
        submitted = "USER_SUBMIT" in states
        reported = "USER_REPORT" in states
        verified = "USER_VERIFY" in states
        warning_shown = action == "warn"
        warning_escape = bool(evaluation["warning_escape"])
        exposure = bool(evaluation["credential_exposure"])
        takeover = bool(evaluation["takeover_success"])
        prevented = bool(evaluation["exposure_prevented_by_prior_lock"])
        capture = _capture_snapshot(result, int(evaluation["message_id"]))
        response = str(message["post_action_response"] or "none")

        if not clicked and not submitted:
            containment_result = "not_required"
        elif bool(evaluation["containment_success"]):
            containment_result = "contained"
        elif response in {"page_blocked_stepup_required", "reported_handled", "contained"}:
            containment_result = "partial"
        else:
            containment_result = "none"

        findings = _signal_findings(signals)
        tactic_id = str(evaluation["red_tactic_id"] or "unclassified")
        tactic = TACTIC_LIBRARY.get(tactic_id, GENERIC_TACTIC)
        record_state = classify_official_record(signals)
        outcome, reason = _outcome(
            action, clicked, submitted, reported, exposure, takeover, prevented
        )

        attempts.append(
            SafeAttemptReport(
                attempt_no=attempt_no,
                difficulty=str(evaluation["true_difficulty"]),
                strictness=strictness,
                tactic_id=tactic_id,
                tactic_name=tactic["name"],
                tactic_research_framing=clean_text(tactic["framing"]),
                secondary_probe="warning_escape_test" if warning_shown else None,
                hypothesis=clean_text(tactic["hypothesis"]),
                target_profile=str(message["profile"]),
                scenario_family=str(message["claimed_event_type"]),
                sender_class=classify_sender(signals),
                destination_class=classify_destination(signals),
                submission_sink="internal_capture" if submitted else "none",
                official_event_record=record_state,
                risk_total=int(message["risk_total"]),
                band=str(message["band"]),
                pre_delivery_action=action,
                delivery_status=str(message["delivery_status"]),
                scoring_signals=findings,
                decisive_signals=tuple(f for f in findings if f.score > 0)[:3],
                neutral_signals=tuple(f.signal for f in findings if f.score == 0),
                user_states=states,
                user_verified=verified,
                user_reported=reported,
                user_clicked=clicked,
                user_submitted=submitted,
                warning_shown=warning_shown,
                warning_escape=warning_escape,
                credential_exposure=(
                    "synthetic_credentials_submitted" if exposure else "none"
                ),
                takeover_result=(
                    "takeover_success" if takeover
                    else "prevented_by_prior_defense" if prevented
                    else "none"
                ),
                submission_target=capture["submission_target"],
                account_status_at_submit=capture["account_status_at_submit"],
                session_state_at_submit=capture["session_state_at_submit"],
                post_action_response=response,
                containment_result=containment_result,
                detection_latency_steps=evaluation["detection_latency_steps"],
                containment_latency_steps=evaluation["containment_latency_steps"],
                red_outcome=outcome,
                outcome_reason=reason,
                detection_explanation=_describe_detection(
                    findings,
                    int(message["risk_total"]),
                    str(message["band"]),
                    action,
                    strictness,
                ),
                user_explanation=_describe_user(
                    str(message["profile"]),
                    states,
                    warning_shown,
                    verified,
                    record_state,
                    clicked,
                    submitted,
                    reported,
                ),
                containment_assessment=_describe_containment(
                    containment_result,
                    response,
                    evaluation["containment_latency_steps"],
                    clicked,
                    submitted,
                ),
                research_note=_research_note(
                    exposure,
                    takeover,
                    warning_escape,
                    bool(evaluation["false_negative"]),
                    bool(evaluation["user_saved"]),
                    action == "quarantine",
                    containment_result,
                    strictness,
                ),
            )
        )

    metrics = result["metrics"]
    summary = SafeMatchSummary(
        seed=int(result["seed"]),
        difficulty_mix=difficulty_mix,
        strictness=strictness,
        red_score=float(result["scores"]["red"]),
        blue_score=float(result["scores"]["blue"]),
        forged_attempts=len(attempts),
        quarantined=quarantined,
        warned=warned,
        allowed=allowed,
        harm_click=int(metrics["harm_click"]),
        harm_submit=int(metrics["harm_submit"]),
        warning_escape=int(metrics["warning_escape"]),
        containment_success=int(metrics["containment_success"]),
        false_positive=int(metrics["false_positive"]),
        friction=int(metrics["friction"]),
        false_negative=int(metrics["false_negative"]),
        official_submission=int(metrics["official_submission"]),
        forged_submission=int(metrics["forged_submission"]),
        credential_exposure=int(metrics["credential_exposure"]),
        takeover_success=int(metrics["takeover_success"]),
        exposure_prevented_by_prior_lock=int(
            metrics["exposure_prevented_by_prior_lock"]
        ),
        overreaction=int(metrics["overreaction"]),
        user_saved=int(metrics["user_saved"]),
        safety_events=len(result["safety_events"]),
    )
    ordered = tuple(
        sorted(
            attempts,
            key=lambda item: (
                {"success": 0, "partial": 1, "failure": 2}[item.red_outcome],
                -item.risk_total,
                item.attempt_no,
            ),
        )
    )
    report = SafeRedReport(
        summary=summary,
        attempts=tuple(attempts),
        conclusions=_conclusions(summary, ordered),
    )
    assert_report_is_clean(report)
    return report
