"""Delivery decision logic, kept out of the UI so it can be tested directly.

The UI layer owns session state; this module owns the rule. Auto delivery is
exactly-once per match run: a plain Streamlit rerun re-executes the script but
carries the same report token, so the gate refuses a second automatic send.
Manual delivery is an explicit operator action and is never auto-suppressed.
"""

from __future__ import annotations

from dataclasses import dataclass


AUTO = "auto"
MANUAL = "manual"


@dataclass(frozen=True)
class DeliveryDecision:
    """Whether to hand a report to the transport, and why."""

    should_send: bool
    reason: str


def plan_delivery(
    trigger: str | None,
    *,
    can_send: bool,
    auto_send_enabled: bool,
    report_token: int | None,
    already_sent_token: int | None,
) -> DeliveryDecision:
    """Decide once per script run whether a report should be delivered."""
    if trigger is None:
        return DeliveryDecision(False, "no_trigger")
    if trigger not in {AUTO, MANUAL}:
        return DeliveryDecision(False, "unknown_trigger")
    if not can_send:
        return DeliveryDecision(False, "delivery_locked")
    if report_token is None:
        return DeliveryDecision(False, "no_report")
    if trigger == AUTO:
        if not auto_send_enabled:
            return DeliveryDecision(False, "auto_disabled")
        if already_sent_token == report_token:
            return DeliveryDecision(False, "already_sent")
        return DeliveryDecision(True, "auto_send")
    return DeliveryDecision(True, "manual_send")
