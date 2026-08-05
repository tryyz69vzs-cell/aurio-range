"""Build the operator report bundle: markdown, JSON, CSV, artifacts, manifest.

Everything written here comes from an already-sanitized SafeRedReport plus
schematic artifact previews. No message copy, markup, URL, signature token,
account identifier, or database row id is ever written into the bundle.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from brandkit.renderer import load_visual
from reporting.artifacts import describe_artifact, render_preview
from reporting.formatter import (
    ACTION_LABELS,
    CONTAINMENT_LABELS,
    DESTINATION_LABELS,
    OUTCOME_LABELS,
    SENDER_LABELS,
    TAKEOVER_LABELS,
    summary_metrics,
)
from reporting.models import SafeRedReport
from reporting.sanitizer import (
    assert_text_is_clean,
    classify_destination,
    classify_official_record,
    classify_sender,
)


BUNDLE_VERSION = "1.0.0"
REQUIRED_ROOT_FILES = (
    "report.md",
    "report.json",
    "metrics.csv",
    "evolution-lineage.json",
    "manifest.json",
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def bundle_filename(seed: int, stamp: str | None = None) -> str:
    return f"aurio-report-{int(seed)}-{stamp or _stamp()}.zip"


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _plain(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(item) for item in value]
    return value


# --- artifact collection ----------------------------------------------------

def collect_artifacts(
    result: Mapping[str, Any], report: SafeRedReport
) -> list[dict[str, Any]]:
    """One schematic preview and metadata record per official/forged message."""
    visual = load_visual()
    messages = {int(row["id"]): row for row in result["messages"]}
    evaluations = {
        int(row["message_id"]): row for row in result["judge_evaluations"]
    }
    by_scenario: dict[str, dict[str, int]] = {}
    for message_id, message in messages.items():
        key = str(message["scenario_key"])
        origin = str(evaluations[message_id]["ground_truth"])
        by_scenario.setdefault(key, {})[origin] = message_id

    artifacts: list[dict[str, Any]] = []
    for attempt in report.attempts:
        forged_id = None
        official_id = None
        for key, pair in by_scenario.items():
            forged = pair.get("forged")
            if forged is None:
                continue
            level = str(evaluations[forged]["true_difficulty"])
            profile = str(messages[forged]["profile"])
            if level == attempt.difficulty and profile == attempt.target_profile:
                forged_id, official_id = forged, pair.get("official")
                break
        if forged_id is None:
            continue

        for kind, message_id in (
            ("forged_email", forged_id),
            ("forged_page", forged_id),
            ("official_email", official_id),
        ):
            if message_id is None:
                continue
            message = messages[message_id]
            signals = message["signals"]
            metadata = describe_artifact(
                kind,
                message,
                signals,
                str(evaluations[message_id]["true_difficulty"]),
                classify_sender(signals),
                classify_destination(signals),
                classify_official_record(signals),
            )
            metadata["attempt_id"] = attempt.attempt_id
            metadata["attempt_no"] = attempt.attempt_no
            name = f"{kind.replace('_', '-')}-{attempt.attempt_id}"
            artifacts.append(
                {
                    "name": name,
                    "metadata": metadata,
                    "png": render_preview(metadata, visual),
                }
            )
    return artifacts


# --- markdown ---------------------------------------------------------------

def _attempt_markdown(attempt) -> list[str]:
    rows = [
        f"### {attempt.attempt_id} · {attempt.tactic_name} "
        f"({OUTCOME_LABELS.get(attempt.red_outcome, attempt.red_outcome)})",
        "",
        f"- 난이도 / 엄격도: `{attempt.difficulty}` / `{attempt.strictness}`",
        f"- 전략: `{attempt.strategy_id}`"
        + (f" (부모 `{attempt.parent_strategy_id}`)" if attempt.parent_strategy_id else "")
        + (f", 세대 {attempt.generation}" if attempt.generation is not None else ""),
        f"- 전술 계열: `{attempt.tactic_family}` / 전술 ID `{attempt.tactic_id}`",
        f"- 대상 프로필: `{attempt.target_profile}`",
        "",
        "**Red는 무엇을 시험했는가**",
        "",
        f"- 사용 목적: {attempt.tactic_research_framing}",
        f"- 방어 가설: {attempt.hypothesis}",
        "",
        "**전달 타이밍과 짝짓기**",
        "",
        f"- 전달 타이밍: `{attempt.delivery_timing}`",
        f"- 공식 사건과의 관계: `{attempt.official_event_relation}`",
        f"- 알림 짝짓기: `{attempt.notification_pairing}`",
        "",
        "**심리적·시각적 구성**",
        "",
        f"- 템플릿 계열 / 레이아웃: `{attempt.template_family}` / `{attempt.layout_variant}`",
        f"- 긴급도 / 어조: `{attempt.urgency_level}` / `{attempt.wording_tone}`",
        f"- 정보 밀도: `{attempt.information_density}`",
        f"- CTA 유형: `{attempt.cta_class}`",
        f"- 개인화 수준: `{attempt.personalization_level}`",
        "",
        "**Blue 탐지**",
        "",
        f"- 위험 총점 {attempt.risk_total} → 밴드 `{attempt.band}` → "
        f"사전 조치 **{ACTION_LABELS.get(attempt.pre_delivery_action, attempt.pre_delivery_action)}**",
        f"- 발신 인증 `{attempt.sender_auth_level}` / 서명 `{attempt.signature_state}`",
        f"- 사건 기록 정합 `{attempt.event_record_alignment}` / "
        f"목적지 소유 `{attempt.destination_ownership_class}`",
        f"- 발신자 분류: {SENDER_LABELS.get(attempt.sender_class, attempt.sender_class)}",
        f"- 목적지 분류: {DESTINATION_LABELS.get(attempt.destination_class, attempt.destination_class)}",
    ]
    for finding in attempt.scoring_signals:
        if finding.score > 0:
            rows.append(f"  - `{finding.signal}` = `{finding.value}` (+{finding.score})")
    if attempt.neutral_signals:
        rows.append(f"- 구분력 없던 신호: `{', '.join(attempt.neutral_signals)}`")
    rows += [
        f"- 탐지 지연: {attempt.detection_latency_steps}단계"
        if attempt.detection_latency_steps is not None
        else "- 탐지 지연: —",
        "",
        attempt.detection_explanation,
        "",
        "**User 반응**",
        "",
        f"- 상태 전환: `{' → '.join(attempt.user_states) or '전환 없음'}`",
        f"- 검증 {attempt.user_verified} / 신고 {attempt.user_reported} / "
        f"클릭 {attempt.user_clicked} / 제출 {attempt.user_submitted}",
        f"- 경고 표시 {attempt.warning_shown} / 경고 이탈 {attempt.warning_escape}",
        "",
        attempt.user_explanation,
        "",
        "**최종 결과**",
        "",
        f"- 판정: **{OUTCOME_LABELS.get(attempt.red_outcome, attempt.red_outcome)}**",
        f"- 합성 자격증명 노출: `{attempt.credential_exposure}`",
        f"- 계정 탈취: `{TAKEOVER_LABELS.get(attempt.takeover_result, attempt.takeover_result)}`",
        f"- 제출 목적지: `{attempt.submission_target}` / "
        f"제출 시점 상태 `{attempt.account_status_at_submit}` · `{attempt.session_state_at_submit}`",
        f"- 봉쇄: {CONTAINMENT_LABELS.get(attempt.containment_result, attempt.containment_result)}"
        + (
            f" (지연 {attempt.containment_latency_steps}단계)"
            if attempt.containment_latency_steps is not None
            else ""
        ),
        "",
        attempt.outcome_reason,
        "",
        attempt.containment_assessment,
        "",
        "**전략 변경점**",
        "",
        f"- 변경 필드: `{', '.join(attempt.changed_fields) or '없음'}`",
        f"- 변경 이유: {attempt.change_reason}",
        "",
        "**다음 연구 메모**",
        "",
        attempt.research_note,
        "",
        f"미리보기: `artifacts/forged-preview-{attempt.attempt_id}.png`, "
        f"`artifacts/forged-page-{attempt.attempt_id}.png`, "
        f"`artifacts/official-preview-{attempt.attempt_id}.png`",
        "",
        "---",
        "",
    ]
    return rows


def _summary_table(report: SafeRedReport) -> list[str]:
    summary = report.summary
    return [
        "| 항목 | 값 |", "| --- | --- |",
        f"| 경기 시각 | `{{generated_at}}` |",
        f"| seed | `{summary.seed}` |",
        f"| 난이도 | `{summary.difficulty_mix}` |",
        f"| 엄격도 | `{summary.strictness}` |",
        f"| 사용자 프로필 | `{', '.join(sorted({a.target_profile for a in report.attempts})) or '—'}` |",
        f"| Red 점수 | **{summary.red_score:.0f}** |",
        f"| Blue 점수 | **{summary.blue_score:.0f}** |",
    ]


RAW_METRIC_ROWS = (
    ("false positive", "false_positive"),
    ("friction", "friction"),
    ("false negative", "false_negative"),
    ("warning escape", "warning_escape"),
    ("harm click", "harm_click"),
    ("harm submit", "harm_submit"),
    ("credential exposure", "credential_exposure"),
    ("takeover success", "takeover_success"),
    ("exposure prevented by prior lock", "exposure_prevented_by_prior_lock"),
    ("containment success", "containment_success"),
    ("user saved", "user_saved"),
    ("defensive overreaction", "overreaction"),
)


def _blue_signal_summary(report: SafeRedReport) -> dict[str, dict[str, int]]:
    totals: dict[str, dict[str, int]] = {}
    for attempt in report.attempts:
        for finding in attempt.scoring_signals:
            entry = totals.setdefault(
                finding.signal, {"total_score": 0, "attempts_scored": 0}
            )
            if finding.score > 0:
                entry["total_score"] += finding.score
                entry["attempts_scored"] += 1
    return dict(
        sorted(totals.items(), key=lambda kv: (-kv[1]["total_score"], kv[0]))
    )


def _profile_summary(report: SafeRedReport) -> dict[str, dict[str, int]]:
    rows: dict[str, dict[str, int]] = {}
    for attempt in report.attempts:
        entry = rows.setdefault(
            attempt.target_profile,
            {
                "attempts": 0, "verified": 0, "reported": 0, "warned": 0,
                "warning_escape": 0, "clicked": 0, "submitted": 0,
            },
        )
        entry["attempts"] += 1
        entry["verified"] += int(attempt.user_verified)
        entry["reported"] += int(attempt.user_reported)
        entry["warned"] += int(attempt.warning_shown)
        entry["warning_escape"] += int(attempt.warning_escape)
        entry["clicked"] += int(attempt.user_clicked)
        entry["submitted"] += int(attempt.user_submitted)
    return dict(sorted(rows.items()))


def build_markdown(report: SafeRedReport, generated_at: str) -> str:
    summary = report.summary
    rows = ["# Aurio Range Red Team 경기 보고서", "", "## 경기 요약", ""]
    rows += [
        row.replace("{generated_at}", generated_at)
        for row in _summary_table(report)
    ]
    rows += [
        "",
        "## 원시 지표",
        "",
        "| 지표 | 값 |", "| --- | --- |",
    ]
    for label, field in RAW_METRIC_ROWS:
        rows.append(f"| {label} | {getattr(summary, field)} |")
    rows += [
        f"| 평균 탐지 단계 | {summary.avg_detection_steps} |",
        f"| 평균 봉쇄 단계 | {summary.avg_containment_steps} |",
        f"| 위조 시도 / 격리 / 경고 / 허용 | {summary.forged_attempts} / "
        f"{summary.quarantined} / {summary.warned} / {summary.allowed} |",
        "",
        "## Red 시도 요약",
        "",
        "| ID | 난이도 | 프로필 | 전술 계열 | 전략 | 위험 | 조치 | 클릭 | 제출 | 결과 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for attempt in report.attempts:
        rows.append(
            f"| `{attempt.attempt_id}` | {attempt.difficulty} | "
            f"{attempt.target_profile} | `{attempt.tactic_family}` | "
            f"`{attempt.strategy_id}` | {attempt.risk_total} | "
            f"{ACTION_LABELS.get(attempt.pre_delivery_action, attempt.pre_delivery_action)} | "
            f"{'O' if attempt.user_clicked else '-'} | "
            f"{'O' if attempt.user_submitted else '-'} | "
            f"{OUTCOME_LABELS.get(attempt.red_outcome, attempt.red_outcome)} |"
        )
    rows += ["", "## Red 시도별 상세 분석", ""]
    for attempt in report.attempts:
        rows.extend(_attempt_markdown(attempt))

    rows += ["## 전략 진화 결과", ""]
    evolution = report.evolution
    if evolution is None or not evolution.enabled:
        rows += [
            "이 경기는 Adaptive Red를 사용하지 않았습니다. 고정된 합성 전술 "
            "템플릿으로 실행되었고, 각 시도의 전략 ID는 정적 식별자입니다.",
            "",
        ]
    else:
        rows += [
            f"- 세대 수 {evolution.generations} · 세대당 후보 {evolution.population_size}",
            f"- 최고 전략 `{evolution.best_strategy_id}`",
            f"- 훈련 fitness {evolution.best_training_fitness:.3f} / "
            f"숨김 평가 fitness {evolution.best_evaluation_fitness:.3f}",
            f"- 훈련 시드 {list(evolution.training_seeds)} · "
            f"숨김 평가 시드 {evolution.evaluation_seed_count}개",
            "",
            "| 세대 | 전략 | 부모 | 변경 필드 | 훈련 | 평가 | Δ | 판정 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for node in evolution.lineage:
            rows.append(
                f"| {node.generation} | `{node.strategy_id}` | "
                f"`{node.parent_strategy_id or '—'}` | "
                f"`{', '.join(node.changed_fields) or '—'}` | "
                f"{node.training_fitness:.3f} | {node.evaluation_fitness:.3f} | "
                f"{node.delta_from_parent:+.3f} | {node.keep_or_drop} |"
            )
        rows.append("")
        for node in evolution.lineage:
            rows.append(f"- **{node.strategy_id}**: {node.change_reason}")
        rows.append("")

    rows += ["## Blue 방어 분석", "", "| 신호 | 누적 점수 | 점수를 준 시도 수 |",
             "| --- | --- | --- |"]
    for name, entry in _blue_signal_summary(report).items():
        rows.append(
            f"| `{name}` | {entry['total_score']} | {entry['attempts_scored']} |"
        )
    top = next(iter(_blue_signal_summary(report).items()), None)
    rows += [
        "",
        (
            f"탐지에 가장 크게 기여한 신호는 `{top[0]}` 로, 누적 {top[1]['total_score']}점을 "
            f"기여했습니다."
            if top
            else "이번 경기에서는 위험 점수를 발생시킨 신호가 없었습니다."
        ),
        "",
        "## 사용자 행동 분석",
        "",
        "| 프로필 | 시도 | 검증 | 신고 | 경고 | 경고 이탈 | 클릭 | 제출 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for profile, entry in _profile_summary(report).items():
        rows.append(
            f"| {profile} | {entry['attempts']} | {entry['verified']} | "
            f"{entry['reported']} | {entry['warned']} | "
            f"{entry['warning_escape']} | {entry['clicked']} | "
            f"{entry['submitted']} |"
        )
    rows += ["", "## 연구 결론", ""]
    for index, text in enumerate(report.conclusions, 1):
        rows.append(f"{index}. {text}")
    rows += [
        "",
        "## 안전 고지",
        "",
        "- 이 보고서는 폐쇄형 합성 시뮬레이션의 결과만 담고 있습니다.",
        "- 실제 서비스, 실제 계정, 실제 자격증명, 실제 외부 공격은 사용되지 "
        "않았습니다.",
        "- 모든 사용자·계정·도메인은 합성이며 예약 도메인 안에서만 존재합니다.",
        "- 메시지 원문, 활성 마크업, 목적지 주소, 서명 토큰, 계정 식별자, "
        "데이터베이스 식별자는 의도적으로 제외되어 실제 발송에 재사용할 수 "
        "없습니다.",
        "- 첨부된 미리보기 이미지는 정적 래스터이며 클릭·입력·제출·네트워크 "
        "요청 기능이 없습니다.",
        "",
    ]
    return "\n".join(rows)


# --- json / csv -------------------------------------------------------------

def build_report_json(report: SafeRedReport, generated_at: str) -> dict[str, Any]:
    return {
        "schema_version": BUNDLE_VERSION,
        "generated_at": generated_at,
        "summary": _plain(report.summary),
        "headline_metrics": dict(summary_metrics(report)),
        "evolution": _plain(report.evolution),
        "attempts": [_plain(attempt) for attempt in report.attempts],
        "conclusions": list(report.conclusions),
        "redaction_notice": (
            "Message copy, markup, destinations, signature tokens, account "
            "identifiers and database ids are excluded by design."
        ),
    }


METRICS_COLUMNS = (
    "match_seed", "attempt_id", "generation", "strategy_id",
    "parent_strategy_id", "difficulty", "strictness", "target_profile",
    "tactic_family", "pre_delivery_action", "risk_total", "clicked",
    "submitted", "warning_escape", "credential_exposure", "takeover_success",
    "containment_success", "training_fitness", "evaluation_fitness",
    "keep_or_drop",
)


def _lineage_by_strategy(report: SafeRedReport) -> dict[str, Any]:
    evolution = report.evolution
    if evolution is None:
        return {}
    return {node.strategy_id: node for node in evolution.lineage}


def build_metrics_csv(report: SafeRedReport) -> str:
    """One analysable row per Red attempt, joined to lineage when present."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(METRICS_COLUMNS)
    lineage = _lineage_by_strategy(report)
    for attempt in report.attempts:
        node = lineage.get(attempt.strategy_id)
        writer.writerow(
            [
                report.summary.seed,
                attempt.attempt_id,
                "" if attempt.generation is None else attempt.generation,
                attempt.strategy_id,
                attempt.parent_strategy_id or "",
                attempt.difficulty,
                attempt.strictness,
                attempt.target_profile,
                attempt.tactic_family,
                attempt.pre_delivery_action,
                attempt.risk_total,
                int(attempt.user_clicked),
                int(attempt.user_submitted),
                int(attempt.warning_escape),
                int(attempt.credential_exposure != "none"),
                int(attempt.takeover_result == "takeover_success"),
                int(attempt.containment_result == "contained"),
                "" if node is None else f"{node.training_fitness:.6f}",
                "" if node is None else f"{node.evaluation_fitness:.6f}",
                "" if node is None else node.keep_or_drop,
            ]
        )
    return buffer.getvalue()


def build_lineage_json(report: SafeRedReport) -> dict[str, Any]:
    evolution = report.evolution
    if evolution is None or not evolution.enabled:
        return {
            "schema_version": BUNDLE_VERSION,
            "evolution_enabled": False,
            "note": "진화를 사용하지 않은 경기입니다. 현재 전략 정보만 담습니다.",
            "current_strategies": [
                {
                    "attempt_id": attempt.attempt_id,
                    "strategy_id": attempt.strategy_id,
                    "tactic_family": attempt.tactic_family,
                    "tactic_id": attempt.tactic_id,
                    "difficulty": attempt.difficulty,
                    "target_profile": attempt.target_profile,
                }
                for attempt in report.attempts
            ],
            "lineage": [],
        }
    return {
        "schema_version": BUNDLE_VERSION,
        "evolution_enabled": True,
        "generations": evolution.generations,
        "population_size": evolution.population_size,
        "best_strategy_id": evolution.best_strategy_id,
        "training_seeds": list(evolution.training_seeds),
        "evaluation_seed_count": evolution.evaluation_seed_count,
        "lineage": [_plain(node) for node in evolution.lineage],
    }


# --- bundle -----------------------------------------------------------------

def build_bundle(
    result: Mapping[str, Any], report: SafeRedReport
) -> tuple[str, bytes]:
    """Return (filename, zip bytes). Every text member is sanitizer-checked."""
    generated_at = _now()
    stamp = _stamp()
    markdown = build_markdown(report, generated_at)
    report_json = build_report_json(report, generated_at)
    metrics = build_metrics_csv(report)
    lineage = build_lineage_json(report)
    artifacts = collect_artifacts(result, report)

    match_summary = {
        "generated_at": generated_at,
        "seed": report.summary.seed,
        "difficulty_mix": report.summary.difficulty_mix,
        "strictness": report.summary.strictness,
        "metrics": dict(summary_metrics(report)),
        "attempt_count": len(report.attempts),
    }
    artifact_index = {
        "schema_version": BUNDLE_VERSION,
        "count": len(artifacts),
        "interactive": False,
        "watermark": "SYNTHETIC SIMULATION",
        "entries": [
            {
                "attempt_id": item["metadata"]["attempt_id"],
                "artifact_type": item["metadata"]["artifact_type"],
                "png": f"{item['name']}.png",
                "metadata": f"{item['name']}.json",
            }
            for item in artifacts
        ],
    }

    members: list[tuple[str, bytes]] = [
        ("report.md", markdown.encode("utf-8")),
        (
            "report.json",
            json.dumps(report_json, ensure_ascii=False, indent=2).encode("utf-8"),
        ),
        ("metrics.csv", metrics.encode("utf-8")),
        (
            "evolution-lineage.json",
            json.dumps(lineage, ensure_ascii=False, indent=2).encode("utf-8"),
        ),
        (
            "artifacts/match-summary.json",
            json.dumps(match_summary, ensure_ascii=False, indent=2).encode("utf-8"),
        ),
        (
            "artifacts/artifact-index.json",
            json.dumps(artifact_index, ensure_ascii=False, indent=2).encode("utf-8"),
        ),
    ]
    for item in artifacts:
        members.append((f"artifacts/{item['name']}.png", item["png"]))
        members.append(
            (
                f"artifacts/{item['name']}.json",
                json.dumps(
                    item["metadata"], ensure_ascii=False, indent=2
                ).encode("utf-8"),
            )
        )

    # Fail closed on every text member before anything is packed.
    for name, payload in members:
        if name.endswith((".md", ".json", ".csv")):
            assert_text_is_clean(payload.decode("utf-8"), name)

    manifest = {
        "schema_version": BUNDLE_VERSION,
        "generator": "Aurio Range reporting bundle",
        "generated_at": generated_at,
        "seed": report.summary.seed,
        "difficulty_mix": report.summary.difficulty_mix,
        "strictness": report.summary.strictness,
        "evolution_enabled": bool(
            report.evolution is not None and report.evolution.enabled
        ),
        "files": [
            {
                "path": name,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            for name, payload in members
        ],
    }
    members.append(
        (
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members:
            archive.writestr(name, payload)
    return bundle_filename(report.summary.seed, stamp), buffer.getvalue()
