"""Seeded multi-step User state machine for three synthetic behavior profiles."""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum
from typing import Callable


class UserState(str, Enum):
    RECEIVED = "RECEIVED"
    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT_VERIFIED"
    REPORTED = "REPORTED"
    IGNORED = "IGNORED"
    CLICKED = "CLICKED"
    SUBMITTED = "SUBMITTED"
    ABORTED = "ABORTED"


@dataclass(frozen=True)
class UserTransition:
    action: str
    from_state: UserState
    to_state: UserState


@dataclass(frozen=True)
class UserJourney:
    transitions: tuple[UserTransition, ...]
    final_state: UserState
    verified: bool
    warning_acknowledged: bool
    warning_ignored: bool


PROFILE_RULES = {
    "cautious": {
        "verify": 0.85,
        "click": 0.10,
        "urgency": -0.05,
        "missing_event_multiplier": 0.05,
        "warning_compliance": 0.95,
        "report": 0.75,
        "submit": 0.20,
    },
    "average": {
        "verify": 0.35,
        "click": 0.40,
        "urgency": 0.08,
        "missing_event_multiplier": 0.15,
        "warning_compliance": 0.65,
        "report": 0.25,
        "submit": 0.50,
    },
    "careless": {
        "verify": 0.05,
        "click": 0.75,
        "urgency": 0.15,
        "missing_event_multiplier": 0.40,
        "warning_compliance": 0.25,
        "report": 0.05,
        "submit": 0.85,
    },
}


def _transition(
    output: list[UserTransition],
    action: str,
    source: UserState,
    target: UserState,
) -> UserState:
    output.append(UserTransition(action, source, target))
    return target


def run_state_machine(
    profile: str,
    urgency_level: str,
    warned: bool,
    official_event_lookup: Callable[[], bool],
    rng: random.Random,
) -> UserJourney:
    """Generate a complete journey; the event lookup runs only after verification."""
    if profile not in PROFILE_RULES:
        raise ValueError(f"알 수 없는 프로필: {profile}")
    rule = PROFILE_RULES[profile]
    state = UserState.RECEIVED
    transitions: list[UserTransition] = []
    warning_acknowledged = False
    warning_ignored = False

    if warned:
        warning_acknowledged = rng.random() < rule["warning_compliance"]
        warning_ignored = not warning_acknowledged
        transitions.append(
            UserTransition(
                "WARN_ACKNOWLEDGED" if warning_acknowledged else "WARN_IGNORED",
                state,
                state,
            )
        )

    verified = rng.random() < rule["verify"]
    event_exists = False
    if verified:
        state = _transition(transitions, "USER_VERIFY", state, UserState.VERIFIED)
        event_exists = bool(official_event_lookup())
    else:
        state = _transition(
            transitions, "USER_NOT_VERIFIED", state, UserState.NOT_VERIFIED
        )

    if warning_acknowledged:
        if verified and rng.random() < rule["report"]:
            state = _transition(transitions, "USER_REPORT", state, UserState.REPORTED)
        else:
            state = _transition(transitions, "USER_ABORT", state, UserState.ABORTED)
        return UserJourney(
            tuple(transitions), state, verified,
            warning_acknowledged, warning_ignored,
        )

    suspicious = verified and not event_exists
    if suspicious and rng.random() < rule["report"]:
        state = _transition(transitions, "USER_REPORT", state, UserState.REPORTED)
        return UserJourney(
            tuple(transitions), state, verified,
            warning_acknowledged, warning_ignored,
        )

    click_probability = rule["click"]
    if urgency_level == "high":
        click_probability = max(0.0, min(1.0, click_probability + rule["urgency"]))
    if suspicious:
        click_probability *= rule["missing_event_multiplier"]

    if rng.random() >= click_probability:
        state = _transition(transitions, "USER_IGNORE", state, UserState.IGNORED)
        return UserJourney(
            tuple(transitions), state, verified,
            warning_acknowledged, warning_ignored,
        )

    state = _transition(transitions, "USER_CLICK", state, UserState.CLICKED)
    if rng.random() < rule["submit"]:
        state = _transition(transitions, "USER_SUBMIT", state, UserState.SUBMITTED)
    else:
        state = _transition(transitions, "USER_ABORT", state, UserState.ABORTED)
    return UserJourney(
        tuple(transitions), state, verified,
        warning_acknowledged, warning_ignored,
    )
