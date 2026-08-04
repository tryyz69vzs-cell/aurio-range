"""Locked safety policy constants for the closed Aurio sandbox."""

from __future__ import annotations


class SafetyViolation(RuntimeError):
    """Raised before a match when a safety invariant is violated."""


SAFETY_INVARIANTS = {
    "S1": "Every synthetic host and mail domain ends in .test or .local.",
    "S2": "Public top-level domains are denied.",
    "S3": "Real service tokens are denied in host and mail identifiers.",
    "S4": (
        "Simulation packages (engine, safety, brandkit, app) contain no "
        "network-egress imports."
    ),
    "S5": "Submission is represented only by state flags; no executable form exists.",
    "S6": "No credential secret value exists in storage, memory, logs, or UI.",
    "S7": "Unsafe structured Red output is discarded.",
    "S8": "The safety policy, registry, and delivery boundary are hash-locked.",
    "S9": "A failed invariant prevents match startup.",
    "S10": "Only a human may run the relock utility.",
    "S11": (
        "Only the approved reporting module may egress, only to the fixed "
        "Telegram API host, and only with a sanitized report object."
    ),
    "S12": (
        "Simulation packages never import the reporting package, so Red, Blue, "
        "User, and Judge cannot reach the delivery path."
    ),
}

LOCKED_FILES = (
    "safety/constitution.py",
    "safety/trusted_registry.json",
    "brandkit/renderer.py",
    "brandkit/templates/email.html",
    "brandkit/templates/login.html",
    "reporting/models.py",
    "reporting/sanitizer.py",
    "reporting/telegram_sender.py",
)

SIMULATION_PACKAGES = ("engine", "safety", "brandkit")

FORBIDDEN_IMPORTS = (
    "requests",
    "httpx",
    "aiohttp",
    "urllib.request",
    "socket",
    "smtplib",
    "anthropic",
    "openai",
    "google.generativeai",
)

REPORTING_PACKAGE = "reporting"
REPORTING_EGRESS_MODULE = "reporting/telegram_sender.py"
TELEGRAM_ALLOWED_HOST = "api.telegram.org"

REPORTING_SENDER_ALLOWED_IMPORTS = frozenset(
    {
        "__future__",
        "hmac",
        "json",
        "dataclasses",
        "typing",
        "urllib.error",
        "urllib.parse",
        "urllib.request",
        "reporting.formatter",
        "safety.constitution",
        "reporting.models",
        "reporting.sanitizer",
    }
)

RED_ALLOWED_KEYS = frozenset(
    {
        "scenario_type",
        "display_sender",
        "synthetic_sender_address",
        "subject_text",
        "greeting_text",
        "body_text",
        "action_label",
        "page_title",
        "page_body",
        "page_action_label",
        "urgency_level",
        "claimed_event_type",
        "claimed_event_ref",
        "destination_identifier",
        "difficulty",
        "tactics",
    }
)

RED_DESTINATION_IDENTIFIERS = frozenset(
    {
        "synthetic_capture_easy",
        "synthetic_capture_medium",
        "synthetic_capture_hard",
    }
)
