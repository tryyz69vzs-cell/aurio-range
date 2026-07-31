"""Hash checks, startup invariants, and structured Red-output validation."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from safety.constitution import (
    FORBIDDEN_IMPORTS,
    LOCKED_FILES,
    RED_ALLOWED_KEYS,
    RED_DESTINATION_IDENTIFIERS,
    SafetyViolation,
)


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "safety" / "SAFETY.lock"
REGISTRY_PATH = ROOT / "safety" / "trusted_registry.json"
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,})\b", re.IGNORECASE)
HOST_PATTERN = re.compile(r"^[a-z0-9.-]+$", re.IGNORECASE)
SAFE_REF_PATTERN = re.compile(r"^[A-Z0-9-]{4,48}$")
MARKUP_PATTERN = re.compile(
    r"<|>|javascript\s*:|data\s*:|on(?:click|error|load)\s*=|style\s*=|script",
    re.IGNORECASE,
)
URL_PATTERN = re.compile(r"(?:https?|ftp|file|data|javascript)\s*:", re.IGNORECASE)
UNSAFE_TEMPLATE_PATTERN = re.compile(
    r"<\s*(?:script|form|input|button|iframe|object|embed|link|a)\b"
    r"|(?:href|src|action)\s*="
    r"|\bon[a-z]+\s*="
    r"|javascript\s*:"
    r"|data\s*:",
    re.IGNORECASE,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _registry() -> dict[str, Any]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def verify_config_hash() -> None:
    if not LOCK_PATH.exists():
        raise SafetyViolation("SAFETY.lock 파일이 없습니다.")
    try:
        locked = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SafetyViolation("SAFETY.lock을 읽을 수 없습니다.") from exc
    if set(locked) != set(LOCKED_FILES):
        raise SafetyViolation("해시 잠금 대상이 승인된 런타임 안전 파일과 다릅니다.")
    for relative in LOCKED_FILES:
        target = ROOT / relative
        if not target.exists() or locked[relative] != _sha256(target):
            raise SafetyViolation(f"안전 잠금 불일치: {relative}")


def _import_names(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise SafetyViolation(f"소스 검사 실패: {path.name}") from exc
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _reserved_host(value: str, registry: dict[str, Any]) -> bool:
    lowered = value.lower().rstrip(".")
    return (
        bool(lowered)
        and bool(HOST_PATTERN.fullmatch(lowered))
        and any(lowered.endswith(tld) for tld in registry["allowed_reserved_tlds"])
        and not any(lowered.endswith(tld) for tld in registry["forbidden_tlds"])
        and not any(token in lowered for token in registry["forbidden_brand_tokens"])
    )


def run_startup_checks() -> None:
    registry = _registry()
    if registry.get("internal_capture_path") != "/_sim/capture":
        raise SafetyViolation("내부 캡처 경로가 변경되었습니다.")
    for address in registry.get("official_senders", []):
        if "@" not in address or not _reserved_host(address.rsplit("@", 1)[1], registry):
            raise SafetyViolation("공식 합성 발신자 주소가 예약 도메인이 아닙니다.")
    host_values = (
        list(registry.get("official_hosts", []))
        + list(registry.get("authorized_relays", []))
    )
    if not host_values or not all(_reserved_host(host, registry) for host in host_values):
        raise SafetyViolation("신뢰 호스트가 예약 도메인이 아닙니다.")

    runtime_sources = [ROOT / "app.py"]
    for package in ("engine", "safety", "brandkit"):
        runtime_sources.extend((ROOT / package).glob("*.py"))
    for path in runtime_sources:
        if path.name == "relock.py":
            continue
        for imported in _import_names(path):
            if any(
                imported == denied or imported.startswith(f"{denied}.")
                for denied in FORBIDDEN_IMPORTS
            ):
                raise SafetyViolation(f"금지 네트워크 import: {imported}")

    for relative in (
        "brandkit/templates/email.html",
        "brandkit/templates/login.html",
    ):
        template = (ROOT / relative).read_text(encoding="utf-8")
        if UNSAFE_TEMPLATE_PATTERN.search(template):
            raise SafetyViolation(f"대화형 또는 외부 연결 템플릿 요소 감지: {relative}")

    from engine.db import create_match_database, table_columns

    connection = create_match_database()
    try:
        account_names = {row["name"] for row in table_columns(connection, "accounts")}
        if "credential_token" in account_names:
            raise SafetyViolation("accounts에 비밀 토큰 필드가 존재합니다.")
        capture = table_columns(connection, "capture_events")
        expected = {
            "attempted_username",
            "attempted_password",
            "valid_synthetic_credentials_submitted",
            "submitted_to_phish",
        }
        found = {row["name"] for row in capture} & expected
        if found != expected:
            raise SafetyViolation("합성 제출 행동 플래그 스키마가 올바르지 않습니다.")
        for row in capture:
            if row["name"] in expected and row["type"].upper() != "INTEGER":
                raise SafetyViolation("합성 제출 행동은 정수 불리언이어야 합니다.")
    finally:
        connection.close()


def _all_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        output: list[str] = []
        for key, nested in value.items():
            output.append(str(key))
            output.extend(_all_strings(nested))
        return output
    if isinstance(value, (list, tuple)):
        output = []
        for nested in value:
            output.extend(_all_strings(nested))
        return output
    return []


def validate_red_output(artifact: dict[str, Any]) -> tuple[bool, str]:
    """Accept only the fixed, non-markup scenario contract."""
    if not isinstance(artifact, dict):
        return False, "Red 산출물은 구조화된 객체여야 합니다."
    keys = set(artifact)
    if keys != set(RED_ALLOWED_KEYS):
        return False, "Red 산출물 필드 집합이 허용 계약과 다릅니다."
    if artifact.get("difficulty") not in {"easy", "medium", "hard"}:
        return False, "허용되지 않은 난이도입니다."
    if artifact.get("urgency_level") not in {"low", "high"}:
        return False, "허용되지 않은 긴급성 수준입니다."
    if artifact.get("destination_identifier") not in RED_DESTINATION_IDENTIFIERS:
        return False, "허용되지 않은 목적지 식별자입니다."
    if not SAFE_REF_PATTERN.fullmatch(str(artifact.get("claimed_event_ref", ""))):
        return False, "사건 참조 ID 형식이 안전하지 않습니다."

    tactics = artifact.get("tactics")
    allowed_tactic_keys = {
        "tactic_id", "sender_auth_result", "signature_mode",
        "ingress_mode", "layout_variant",
    }
    if not isinstance(tactics, dict) or set(tactics) != allowed_tactic_keys:
        return False, "전술 파라미터 계약이 올바르지 않습니다."
    if tactics["sender_auth_result"] not in {"PASS", "SOFTFAIL", "FAIL"}:
        return False, "합성 발신 인증 값이 올바르지 않습니다."
    if tactics["signature_mode"] not in {"invalid", "none"}:
        return False, "Red는 유효한 플랫폼 서명을 생성할 수 없습니다."
    if tactics["ingress_mode"] not in {
        "internal_service", "authorized_relay", "synthetic_external"
    }:
        return False, "유입 전술 값이 올바르지 않습니다."
    if tactics["layout_variant"] != "shared":
        return False, "고정 공용 레이아웃만 사용할 수 있습니다."
    if artifact.get("scenario_type") != "forged_security_alert":
        return False, "Red는 위조 보안 알림 시나리오만 생성할 수 있습니다."

    strings = _all_strings(artifact)
    if any(MARKUP_PATTERN.search(text) or URL_PATTERN.search(text) for text in strings):
        return False, "태그·스타일·스크립트·URL 직접 삽입은 허용되지 않습니다."

    address = str(artifact.get("synthetic_sender_address", "")).lower()
    match = EMAIL_PATTERN.fullmatch(address)
    if not match or not _reserved_host(match.group(1), _registry()):
        return False, "합성 발신 주소는 안전한 예약 도메인이어야 합니다."

    for text in strings:
        for email_match in EMAIL_PATTERN.finditer(text):
            if not _reserved_host(email_match.group(1), _registry()):
                return False, "실제 이메일 도메인이 포함되어 있습니다."
    return True, "ok"


def arena_gate() -> None:
    verify_config_hash()
    run_startup_checks()
