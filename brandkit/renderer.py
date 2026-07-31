"""Trusted Jinja-only renderer for scenario data and static previews."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape


ROOT = Path(__file__).resolve().parents[1]
BRAND_PATH = ROOT / "brandkit" / "aurio_visual.json"
REGISTRY_PATH = ROOT / "safety" / "trusted_registry.json"
TEMPLATE_PATH = ROOT / "brandkit" / "templates"

DESTINATIONS = {
    "official_alerts": "https://app.aurio.test/security/alerts",
    "official_sessions": "https://app.aurio.test/account/sessions",
    "official_drift_route": "https://app.aurio.test/security/review",
    "synthetic_capture_easy": "https://aur1o.test/security/check",
    "synthetic_capture_medium": "https://aurio-help.test/security/check",
    "synthetic_capture_hard": "https://aurio-help.test/security/check",
}


def load_visual() -> dict[str, Any]:
    return json.loads(BRAND_PATH.read_text(encoding="utf-8"))


def load_registry() -> dict[str, Any]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_PATH)),
        autoescape=select_autoescape(("html", "xml"), default=True),
        undefined=StrictUndefined,
    )


def destination_url(identifier: str) -> str:
    try:
        return DESTINATIONS[identifier]
    except KeyError as exc:
        raise ValueError("허용되지 않은 목적지 식별자입니다.") from exc


def render_email(structured: Mapping[str, Any]) -> str:
    """Render fixed email markup; callers can only supply escaped variables."""
    visual = load_visual()
    context = {
        "font_stack": visual["font_stack"],
        "max_width": visual["email_layout"]["max_width"],
        "header_height": visual["email_layout"]["header_height"],
        "primary": visual["colors"]["primary"],
        "accent": visual["colors"]["accent"],
        "brand_name": visual["brand_name"],
        "subject_text": structured["subject_text"],
        "greeting_text": structured["greeting_text"],
        "body_text": structured["body_text"],
        "event_ref": structured["claimed_event_ref"],
        "action_label": structured["action_label"],
        "signoff_text": visual["tone"]["signoff"],
    }
    return _environment().get_template("email.html").render(**context)


def render_login(structured: Mapping[str, Any]) -> str:
    """Render a fixed, non-interactive login-shaped simulation preview."""
    visual = load_visual()
    context = {
        "font_stack": visual["font_stack"],
        "card_width": visual["login_layout"]["card_width"],
        "primary": visual["colors"]["primary"],
        "accent": visual["colors"]["accent"],
        "page_title": structured["page_title"],
        "page_body": structured["page_body"],
        "action_label": structured["page_action_label"],
    }
    return _environment().get_template("login.html").render(**context)


def static_login_preview(rendered_html: str) -> str:
    """Fail closed if a supposedly static preview contains interactive markup."""
    if re.search(
        r"<\s*(?:form|input|button|a|script|iframe|object|embed)\b"
        r"|(?:href|src|action)\s*="
        r"|\bon[a-z]+\s*=",
        rendered_html,
        flags=re.IGNORECASE,
    ):
        raise ValueError("비대화형 미리보기에 허용되지 않은 요소가 포함되었습니다.")
    return rendered_html


def destination_parts(identifier: str) -> tuple[str, str]:
    parsed = urlparse(destination_url(identifier))
    return parsed.hostname or "", parsed.path
