"""Redaction rules and the final fail-closed check for operator reports.

This module is hash-locked. It is the last gate before a report reaches the
Streamlit report tab or the Telegram transport, and it fails closed: any
forbidden pattern raises instead of being silently stripped.

Forbidden in reports (per operating policy):
  message bodies, phishing copy, HTML/CSS, full URLs, signature tokens,
  raw event reference ids, synthetic account emails or usernames,
  database row ids, credential-like strings, real service names,
  real domains, real email addresses, and reusable attack procedures.
"""

from __future__ import annotations

import json
import re
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "safety" / "trusted_registry.json"

MAX_FIELD_CHARS = 400


class ReportSanitizationError(RuntimeError):
    """Raised when a report still contains information that must never leave."""


SENDER_CLASS_BY_STATE = {
    ("registered", "PASS"): "registered_official_sender",
    ("registered", "SOFTFAIL"): "synthetic_lookalike_sender",
    ("registered", "FAIL"): "synthetic_lookalike_sender",
    ("unregistered", "PASS"): "unregistered_synthetic_sender",
    ("unregistered", "SOFTFAIL"): "unregistered_synthetic_sender",
    ("unregistered", "FAIL"): "unregistered_synthetic_sender",
}

_SCHEME_PATTERN = re.compile(r"[a-z][a-z0-9+.-]*\s*://", re.IGNORECASE)
_RISKY_SCHEME_PATTERN = re.compile(r"\b(?:javascript|data|file|ftp)\s*:", re.IGNORECASE)
_MARKUP_PATTERN = re.compile(r"<\s*/?\s*[a-z!]", re.IGNORECASE)
_STYLE_PATTERN = re.compile(r"(?:style|href|src|action|on[a-z]+)\s*=", re.IGNORECASE)
_EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+", re.IGNORECASE)
_RESERVED_HOST_PATTERN = re.compile(r"\b[a-z0-9][a-z0-9-]*\.(?:test|local)\b", re.IGNORECASE)
_EVENT_REF_PATTERN = re.compile(r"\b[A-Z]{2}-[A-Z]-\d{3,}\b")
_CREDENTIAL_PATTERN = re.compile(
    r"\b(?:password|passwd|pwd|secret|api[_-]?key|bot[_-]?token|chat[_-]?id)"
    r"\s*[:=]\s*\S+",
    re.IGNORECASE,
)
_ROW_ID_PATTERN = re.compile(
    r"\b(?:message_id|account_id|match_id|row_id|db_id)\s*[:=#]?\s*\d+",
    re.IGNORECASE,
)


def _registry() -> dict[str, Any]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def classify_sender(signals: dict[str, Any]) -> str:
    """Abstract the sender into one of the three approved report labels."""
    registry_state = str(signals.get("sender_registry", {}).get("value", "unregistered"))
    auth_state = str(signals.get("sender_auth", {}).get("value", "FAIL")).upper()
    return SENDER_CLASS_BY_STATE.get(
        (registry_state, auth_state), "unregistered_synthetic_sender"
    )


def classify_destination(signals: dict[str, Any]) -> str:
    """Abstract the link destination; never expose a host or a path."""
    ownership = str(
        signals.get("destination_ownership", {}).get("value", "unregistered")
    )
    return "official_owned" if ownership == "registered" else "synthetic_unowned"


def classify_official_record(signals: dict[str, Any]) -> str:
    value = str(signals.get("official_event_record", {}).get("value", "missing"))
    return "present" if value == "exists" else "absent"


def clean_text(value: str) -> str:
    """Collapse whitespace and cap length so no long payload can ride along."""
    collapsed = re.sub(r"\s+", " ", str(value)).strip()
    if len(collapsed) > MAX_FIELD_CHARS:
        collapsed = collapsed[: MAX_FIELD_CHARS - 1].rstrip() + "…"
    return collapsed


def _violations(text: str) -> list[str]:
    registry = _registry()
    found: list[str] = []
    lowered = text.lower()
    if _SCHEME_PATTERN.search(text):
        found.append("URL 스킴")
    if _RISKY_SCHEME_PATTERN.search(text):
        found.append("실행 가능 스킴")
    if _MARKUP_PATTERN.search(text):
        found.append("마크업 태그")
    if _STYLE_PATTERN.search(text):
        found.append("스타일 또는 속성 선언")
    if _EMAIL_PATTERN.search(text):
        found.append("이메일 주소")
    if _RESERVED_HOST_PATTERN.search(text):
        found.append("호스트 이름")
    if _EVENT_REF_PATTERN.search(text):
        found.append("사건 참조 ID 원문")
    if _CREDENTIAL_PATTERN.search(text):
        found.append("자격증명 유사 문자열")
    if _ROW_ID_PATTERN.search(text):
        found.append("데이터베이스 내부 ID")
    if registry["signature_prefix"].lower() in lowered:
        found.append("서명 토큰")
    for tld in registry["forbidden_tlds"]:
        if tld.lower() in lowered:
            found.append(f"실제 TLD({tld})")
    for token in registry["forbidden_brand_tokens"]:
        if token.lower() in lowered:
            found.append(f"실제 서비스 이름({token})")
    return found


def assert_text_is_clean(text: str, where: str = "보고서") -> None:
    """Raise when a single rendered string still carries forbidden content."""
    found = _violations(str(text))
    if found:
        raise ReportSanitizationError(
            f"{where}에 허용되지 않은 정보가 있습니다: {', '.join(sorted(set(found)))}"
        )


def _walk_strings(value: Any, path: str = "report") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(path, value)]
    if is_dataclass(value):
        output: list[tuple[str, str]] = []
        for field in fields(value):
            output.extend(
                _walk_strings(getattr(value, field.name), f"{path}.{field.name}")
            )
        return output
    if isinstance(value, dict):
        output = []
        for key, nested in value.items():
            output.append((f"{path}.<key>", str(key)))
            output.extend(_walk_strings(nested, f"{path}.{key}"))
        return output
    if isinstance(value, (list, tuple, set)):
        output = []
        for index, nested in enumerate(value):
            output.extend(_walk_strings(nested, f"{path}[{index}]"))
        return output
    return []


def assert_report_is_clean(report: Any) -> None:
    """Fail closed over every string reachable from the report object."""
    for path, text in _walk_strings(report):
        assert_text_is_clean(text, path)
