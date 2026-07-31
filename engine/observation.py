"""The exact, immutable telemetry surface visible to Blue."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BlueObservation:
    message_id: int
    account_id: int
    channel: str
    display_sender_name: str
    auth_sender_address: str
    sender_auth_result: str
    signature_token: str | None
    claimed_event_type: str
    claimed_event_ref: str | None
    link_destination: str
    ingress_channel: str
    body_text: str
    created_step: int
    account_status_snapshot: str
    account_session_snapshot: str
