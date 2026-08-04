"""The single approved network-egress module in this project. Hash-locked.

Rules enforced here and re-checked by safety.guard at startup:
  * the only reachable host is the fixed Telegram API host;
  * the only accepted payload type is a sanitized SafeRedReport;
  * the report and every rendered message are re-validated by the locked
    sanitizer immediately before transmission;
  * bot token and chat id never appear in results, details, or exceptions;
  * a transport failure returns a status object and never raises upward,
    so a delivery problem can never fail a match.

Red, Blue, User, Judge, the renderer, and the safety engine do not import
this module and cannot reach it.
"""

from __future__ import annotations

import hmac
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from safety.constitution import TELEGRAM_ALLOWED_HOST as _POLICY_HOST
from reporting.formatter import build_telegram_messages
from reporting.models import SafeRedReport
from reporting.sanitizer import assert_report_is_clean, assert_text_is_clean


# Routing and validation both read the hash-locked policy value, never a
# mutable module global, so rebinding the alias below cannot redirect traffic.
TELEGRAM_ALLOWED_HOST = _POLICY_HOST
TELEGRAM_ALLOWED_SCHEME = "https"
TELEGRAM_SEND_METHOD = "sendMessage"
TIMEOUT_SECONDS = 8
REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
_SEPARATOR = "://"


class TelegramTransportError(RuntimeError):
    """Raised for a blocked endpoint, a redirect, or a rejected payload type."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect, including ones pointing back at the same host.

    Returning None makes urllib stop instead of following the Location header,
    so a 3xx surfaces as an HTTPError and never becomes a second request.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# A dedicated opener: the module never uses urlopen's global redirect handling.
_OPENER = urllib.request.build_opener(_NoRedirectHandler)


@dataclass(frozen=True)
class TelegramCredentials:
    """Fixed destination credentials. Never rendered in full anywhere."""

    bot_token: str
    chat_id: str

    def __repr__(self) -> str:
        return "TelegramCredentials(bot_token='***', chat_id='***')"

    __str__ = __repr__


@dataclass(frozen=True)
class TelegramSendResult:
    """Delivery outcome for the UI. Contains no secret material."""

    attempted: bool
    delivered: int
    total: int
    ok: bool
    status: str
    detail: str


def read_settings(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize a secrets section without ever raising on missing values."""
    if not isinstance(raw, Mapping):
        return {"enabled": False, "bot_token": "", "chat_id": "", "owner_pin": ""}
    return {
        "enabled": bool(raw.get("enabled", False)),
        "bot_token": str(raw.get("bot_token", "") or "").strip(),
        "chat_id": str(raw.get("chat_id", "") or "").strip(),
        "owner_pin": str(raw.get("owner_pin", "") or "").strip(),
    }


def telegram_status(raw: Mapping[str, Any] | None) -> str:
    """Return 'active', 'inactive', or 'missing' for the sidebar indicator."""
    settings = read_settings(raw)
    if not settings["bot_token"] or not settings["chat_id"]:
        return "missing"
    if not settings["enabled"]:
        return "inactive"
    return "active"


def build_credentials(raw: Mapping[str, Any] | None) -> TelegramCredentials | None:
    """Return credentials only when delivery is explicitly enabled and complete."""
    settings = read_settings(raw)
    if not settings["enabled"]:
        return None
    if not settings["bot_token"] or not settings["chat_id"]:
        return None
    return TelegramCredentials(settings["bot_token"], settings["chat_id"])


def owner_pin_configured(raw: Mapping[str, Any] | None) -> bool:
    return bool(read_settings(raw)["owner_pin"])


def verify_owner_pin(raw: Mapping[str, Any] | None, candidate: str | None) -> bool:
    """Constant-time PIN check. The candidate is never stored or echoed."""
    expected = read_settings(raw)["owner_pin"]
    if not expected or not candidate:
        return False
    return hmac.compare_digest(str(expected), str(candidate))


def assert_allowed_endpoint(url: str) -> None:
    """Reject every destination except the fixed Telegram API host."""
    parsed = urllib.parse.urlparse(str(url))
    if parsed.scheme != TELEGRAM_ALLOWED_SCHEME or parsed.hostname != _POLICY_HOST:
        raise TelegramTransportError("승인되지 않은 전송 목적지입니다.")


def _endpoint(credentials: TelegramCredentials) -> str:
    return (
        f"{TELEGRAM_ALLOWED_SCHEME}{_SEPARATOR}{_POLICY_HOST}"
        f"/bot{credentials.bot_token}/{TELEGRAM_SEND_METHOD}"
    )


def _scrub(text: str, credentials: TelegramCredentials | None) -> str:
    output = str(text)
    if credentials is not None:
        for secret in (credentials.bot_token, credentials.chat_id):
            if secret:
                output = output.replace(secret, "***")
    return output


def _https_post(url: str, payload: Mapping[str, Any], timeout: int) -> int:
    """POST once. A redirect is a hard failure, never a second request."""
    body = json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 0) or 0)
    except urllib.error.HTTPError as exc:
        code = int(getattr(exc, "code", 0) or 0)
        if code in REDIRECT_CODES:
            # Message carries no URL: the endpoint embeds the bot token.
            raise TelegramTransportError(
                f"리다이렉트 응답({code})을 받아 전송을 중단했습니다."
            ) from None
        raise TelegramTransportError(f"전송 오류 코드 {code}") from None
    if status in REDIRECT_CODES:
        raise TelegramTransportError(
            f"리다이렉트 응답({status})을 받아 전송을 중단했습니다."
        )
    return status


def send_report(
    report: SafeRedReport,
    credentials: TelegramCredentials | None,
    transport: Callable[[str, Mapping[str, Any], int], Any] | None = None,
    timeout: int = TIMEOUT_SECONDS,
) -> TelegramSendResult:
    """Deliver a sanitized report. Never raises; always returns a status."""
    if type(report) is not SafeRedReport:
        raise TypeError("SafeRedReport 객체만 전송할 수 있습니다.")
    if credentials is None:
        return TelegramSendResult(
            False, 0, 0, False, "missing_config",
            "Telegram이 비활성화되어 있거나 설정이 없어 전송하지 않았습니다.",
        )

    try:
        assert_report_is_clean(report)
        messages = build_telegram_messages(report)
        for message in messages:
            assert_text_is_clean(message, "Telegram 메시지")
        url = _endpoint(credentials)
        assert_allowed_endpoint(url)
    except TelegramTransportError as exc:
        return TelegramSendResult(
            False, 0, 0, False, "blocked", _scrub(str(exc), credentials)
        )
    except Exception as exc:  # sanitization or rendering refused the payload
        return TelegramSendResult(
            False, 0, 0, False, "blocked",
            _scrub(f"보고서 검증 실패: {exc}", credentials),
        )

    post = transport or _https_post
    delivered = 0
    try:
        for message in messages:
            post(
                url,
                {
                    "chat_id": credentials.chat_id,
                    "text": message,
                    "disable_web_page_preview": True,
                },
                timeout,
            )
            delivered += 1
    except Exception as exc:
        return TelegramSendResult(
            True, delivered, len(messages), False,
            "failed" if delivered == 0 else "partial",
            _scrub(f"전송 실패: {type(exc).__name__}", credentials),
        )
    return TelegramSendResult(
        True, delivered, len(messages), True, "sent",
        f"{delivered}개 메시지를 전송했습니다.",
    )
