"""Frozen, already-sanitized report types. Hash-locked type boundary.

Nothing in this module may hold message bodies, markup, URLs, signature
tokens, raw event references, account identifiers, or database row ids.
Only abstracted classifications and derived analysis sentences are allowed.
"""

from __future__ import annotations

from dataclasses import dataclass


SENDER_CLASSES = (
    "registered_official_sender",
    "synthetic_lookalike_sender",
    "unregistered_synthetic_sender",
)

DESTINATION_CLASSES = (
    "official_owned",
    "synthetic_unowned",
    "internal_capture",
)

SUBMISSION_SINKS = ("none", "internal_capture")

RED_OUTCOMES = ("success", "partial", "failure")

CONTAINMENT_RESULTS = ("contained", "partial", "none", "not_required")

CREDENTIAL_EXPOSURES = ("none", "synthetic_credentials_submitted")

SUBMISSION_TARGETS = ("official_owned", "synthetic_unowned", "internal_capture")

TAKEOVER_RESULTS = ("takeover_success", "prevented_by_prior_defense", "none")

OFFICIAL_RECORD_STATES = ("present", "absent")


@dataclass(frozen=True)
class SafeSignalFinding:
    """One Blue risk signal with its abstracted value and contributed score."""

    signal: str
    value: str
    score: int


@dataclass(frozen=True)
class SafeAttemptReport:
    """One synthetic forged attempt, described without reusable attack content."""

    attempt_no: int
    difficulty: str
    strictness: str
    tactic_id: str
    tactic_name: str
    tactic_research_framing: str
    secondary_probe: str | None
    hypothesis: str
    target_profile: str
    scenario_family: str
    sender_class: str
    destination_class: str
    submission_sink: str
    official_event_record: str
    risk_total: int
    band: str
    pre_delivery_action: str
    delivery_status: str
    scoring_signals: tuple[SafeSignalFinding, ...]
    decisive_signals: tuple[SafeSignalFinding, ...]
    neutral_signals: tuple[str, ...]
    user_states: tuple[str, ...]
    user_verified: bool
    user_reported: bool
    user_clicked: bool
    user_submitted: bool
    warning_shown: bool
    warning_escape: bool
    credential_exposure: str
    takeover_result: str
    submission_target: str
    account_status_at_submit: str
    session_state_at_submit: str
    post_action_response: str
    containment_result: str
    detection_latency_steps: int | None
    containment_latency_steps: int | None
    red_outcome: str
    outcome_reason: str
    detection_explanation: str
    user_explanation: str
    containment_assessment: str
    research_note: str


@dataclass(frozen=True)
class SafeMatchSummary:
    """Whole-match counters shown at the top of the report."""

    seed: int
    difficulty_mix: str
    strictness: str
    red_score: float
    blue_score: float
    forged_attempts: int
    quarantined: int
    warned: int
    allowed: int
    harm_click: int
    harm_submit: int
    warning_escape: int
    official_submission: int
    forged_submission: int
    credential_exposure: int
    takeover_success: int
    exposure_prevented_by_prior_lock: int
    containment_success: int
    overreaction: int
    false_positive: int
    friction: int
    false_negative: int
    user_saved: int
    safety_events: int


@dataclass(frozen=True)
class SafeRedReport:
    """The complete sanitized artifact. The only accepted delivery payload."""

    summary: SafeMatchSummary
    attempts: tuple[SafeAttemptReport, ...]
    conclusions: tuple[str, ...]
