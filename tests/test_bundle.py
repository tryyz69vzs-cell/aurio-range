"""Report bundle: required members, manifest integrity, and redaction."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile

import pytest

from engine.match import run_match
from reporting.bundle import (
    REQUIRED_ROOT_FILES,
    build_bundle,
    build_markdown,
    build_metrics_csv,
    build_report_json,
)
from reporting.formatter import summary_metrics
from reporting.red_report import build_red_report
from reporting.sanitizer import ReportSanitizationError, assert_text_is_clean

PROFILES = ["cautious", "average", "careless"]


def _bundle(seed: int = 1010, strictness: str = "permissive"):
    result = run_match("mixed", strictness, PROFILES, seed)
    report = build_red_report(result)
    name, payload = build_bundle(result, report)
    return result, report, name, zipfile.ZipFile(io.BytesIO(payload))


def test_bundle_contains_every_required_member():
    _, report, name, archive = _bundle()
    names = set(archive.namelist())
    for required in REQUIRED_ROOT_FILES:
        assert required in names
    assert "artifacts/artifact-index.json" in names
    assert "artifacts/match-summary.json" in names
    for attempt in report.attempts:
        assert f"artifacts/forged-email-{attempt.attempt_id}.png" in names
        assert f"artifacts/forged-email-{attempt.attempt_id}.json" in names
        assert f"artifacts/forged-page-{attempt.attempt_id}.png" in names
        assert f"artifacts/official-email-{attempt.attempt_id}.png" in names
    assert re.fullmatch(r"aurio-report-\d+-\d{8}-\d{6}\.zip", name)


def test_manifest_hashes_match_every_member():
    _, _, _, archive = _bundle()
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["schema_version"]
    assert manifest["seed"]
    assert manifest["files"]
    for entry in manifest["files"]:
        payload = archive.read(entry["path"])
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"]
        assert len(payload) == entry["bytes"]


def test_markdown_and_json_agree_on_every_headline_value():
    _, report, _, archive = _bundle()
    markdown = archive.read("report.md").decode("utf-8")
    payload = json.loads(archive.read("report.json"))
    assert payload["summary"]["seed"] == report.summary.seed
    assert str(report.summary.seed) in markdown
    for label, value in summary_metrics(report):
        assert payload["headline_metrics"][label] == value
        assert value in markdown
    assert payload["summary"]["red_score"] == report.summary.red_score
    assert payload["summary"]["blue_score"] == report.summary.blue_score
    assert len(payload["attempts"]) == len(report.attempts)


def test_markdown_has_every_required_section():
    _, _, _, archive = _bundle()
    markdown = archive.read("report.md").decode("utf-8")
    for section in (
        "## 경기 요약", "## 원시 지표", "## Red 시도 요약",
        "## Red 시도별 상세 분석", "## 전략 진화 결과", "## Blue 방어 분석",
        "## 사용자 행동 분석", "## 연구 결론", "## 안전 고지",
    ):
        assert section in markdown


def test_metrics_csv_rows_match_the_attempts():
    _, report, _, archive = _bundle()
    rows = list(csv.DictReader(io.StringIO(archive.read("metrics.csv").decode())))
    assert len(rows) == len(report.attempts)
    by_id = {row["attempt_id"]: row for row in rows}
    for attempt in report.attempts:
        row = by_id[attempt.attempt_id]
        assert int(row["match_seed"]) == report.summary.seed
        assert row["difficulty"] == attempt.difficulty
        assert row["target_profile"] == attempt.target_profile
        assert int(row["risk_total"]) == attempt.risk_total
        assert int(row["clicked"]) == int(attempt.user_clicked)
        assert int(row["submitted"]) == int(attempt.user_submitted)
    assert sum(int(r["clicked"]) for r in rows) == report.summary.harm_click
    assert sum(int(r["submitted"]) for r in rows) == report.summary.harm_submit


def test_bundle_text_members_carry_no_forbidden_content():
    result, _, _, archive = _bundle()
    bodies = {
        name: archive.read(name).decode("utf-8")
        for name in archive.namelist()
        if name.endswith((".md", ".json", ".csv"))
    }
    for name, body in bodies.items():
        assert_text_is_clean(body, name)
        lowered = body.lower()
        for denied in ("http", "://", "<div", "<script", "href=", "aurio-sig-",
                       "@users.", "aurio.test", "instagram", ".com"):
            assert denied not in lowered, f"{name}: {denied}"
    joined = "\n".join(bodies.values())
    for message in result["messages"]:
        assert message["body_text"] not in joined
        assert message["rendered_html"] not in joined


def test_only_this_match_appears_in_the_bundle():
    result_a, report_a, _, archive_a = _bundle(1010)
    _, report_b, _, _ = _bundle(1088)
    payload = json.loads(archive_a.read("report.json"))
    assert payload["summary"]["seed"] == report_a.summary.seed
    assert payload["summary"]["seed"] != report_b.summary.seed
    assert len(payload["attempts"]) == len(report_a.attempts)


def test_bundle_is_deterministic_for_the_same_match():
    result = run_match("mixed", "permissive", PROFILES, 1010)
    report = build_red_report(result)
    first = build_report_json(report, "T")
    second = build_report_json(report, "T")
    assert first == second
    assert build_metrics_csv(report) == build_metrics_csv(report)
    assert build_markdown(report, "T") == build_markdown(report, "T")


def test_artifact_metadata_matches_the_attempt_and_is_non_interactive():
    _, report, _, archive = _bundle()
    index = json.loads(archive.read("artifacts/artifact-index.json"))
    assert index["interactive"] is False
    assert index["watermark"] == "SYNTHETIC SIMULATION"
    assert index["count"] == len(index["entries"])
    for attempt in report.attempts:
        meta = json.loads(
            archive.read(f"artifacts/forged-email-{attempt.attempt_id}.json")
        )
        assert meta["interactive"] is False
        assert meta["artifact_type"] == "forged_email"
        assert meta["attempt_id"] == attempt.attempt_id
        assert meta["urgency_level"] == attempt.urgency_level
        assert meta["template_family"] == attempt.template_family
        assert meta["layout_variant"] == attempt.layout_variant
        assert meta["sender_class"] == attempt.sender_class
        assert meta["redaction_notice"]
        assert meta["semantic_sequence"]


def test_preview_images_are_static_rasters_with_no_active_content():
    _, report, _, archive = _bundle()
    for attempt in report.attempts[:2]:
        for kind in ("forged-email", "forged-page", "official-email"):
            raw = archive.read(f"artifacts/{kind}-{attempt.attempt_id}.png")
            assert raw.startswith(b"\x89PNG\r\n\x1a\n")
            lowered = raw.lower()
            for denied in (b"<script", b"<form", b"<input", b"javascript:",
                           b"http://", b"https://", b"onclick"):
                assert denied not in lowered


def test_sanitizer_still_rejects_a_poisoned_member():
    with pytest.raises(ReportSanitizationError):
        assert_text_is_clean("보고서 https://aur1o.test/login", "report.md")
