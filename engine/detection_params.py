"""Tunable risk bands, signal weights, and latency-free score coefficients."""

from __future__ import annotations

from dataclasses import dataclass


SIGNAL_WEIGHTS = {
    "sender_registry": {"registered": 0, "unregistered": 25},
    "sender_auth": {"PASS": 0, "SOFTFAIL": 15, "FAIL": 25},
    "display_alignment": {"aligned": 0, "misaligned": 20},
    "signature_validity": {"VALID": 0, "INVALID": 25, "NONE": 15},
    "destination_ownership": {"registered": 0, "unregistered": 30},
    "official_event_record": {"exists": 0, "missing": 25},
    "ingress_channel": {"trusted": 0, "external": 20, "unknown": 15},
    "urgency_authority": {"present": 10, "absent": 0},
    "state_consistency": {"consistent": 0, "contradictory": 20},
}

BAND_THRESHOLDS = {
    "permissive": {"medium": 40, "high": 90},
    "balanced": {"medium": 30, "high": 70},
    "strict": {"medium": 20, "high": 55},
}

RED_BYPASS = {"easy": 1, "medium": 2, "hard": 3}
RED_CLICK = {"easy": 2, "medium": 3, "hard": 4}
RED_SUBMIT = {"easy": 3, "medium": 5, "hard": 7}

SCORE_COEFFICIENTS = {
    "red_compromise": 3,
    "red_warning_escape": 4,
    "red_safety_discard": -5,
    "blue_quarantine": 4,
    "blue_warn_abort": 3,
    "blue_warn_escape": 1,
    "blue_containment": 3,
    "blue_false_positive": -8,
    "blue_false_negative": -3,
    "blue_friction": -1,
}


@dataclass(frozen=True)
class DetectionParams:
    strictness: str
    weights: dict
    thresholds: dict


def get_params(strictness: str) -> DetectionParams:
    if strictness not in BAND_THRESHOLDS:
        raise ValueError(f"알 수 없는 엄격도: {strictness}")
    return DetectionParams(strictness, SIGNAL_WEIGHTS, BAND_THRESHOLDS[strictness])


def classify_risk(total: int, strictness: str) -> tuple[str, str]:
    limits = BAND_THRESHOLDS[strictness]
    if total >= limits["high"]:
        return "HIGH", "quarantine"
    if total >= limits["medium"]:
        return "MEDIUM", "warn"
    return "LOW", "allow"
