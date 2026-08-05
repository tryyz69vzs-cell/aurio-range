"""Run matches for a strategy and aggregate independent raw indicators.

Training seeds and hidden evaluation seeds are derived from disjoint integer
ranges, so an evaluation seed can never appear in a training run.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from engine.match import run_match
from evolution.action_space import validate_strategy
from evolution.models import RawMetrics, Strategy


TRAINING_SEED_BASE = 100_000
EVALUATION_SEED_BASE = 900_000


def training_seeds(base_seed: int, count: int) -> tuple[int, ...]:
    return tuple(TRAINING_SEED_BASE + (base_seed % 9973) + i * 17 for i in range(count))


def evaluation_seeds(base_seed: int, count: int) -> tuple[int, ...]:
    return tuple(
        EVALUATION_SEED_BASE + (base_seed % 9973) + i * 29 for i in range(count)
    )


def seeds_are_disjoint(training: Sequence[int], evaluation: Sequence[int]) -> bool:
    return not (set(training) & set(evaluation))


def _profile_for(strategy: Strategy, profiles: Sequence[str]) -> list[str]:
    target = str(strategy.fields["target_profile"])
    return [target] if target in profiles else list(profiles)


def evaluate_strategy(
    strategy: Strategy,
    seeds: Sequence[int],
    profiles: Sequence[str],
    difficulty: str,
    strictness: str,
) -> tuple[RawMetrics, int, int]:
    """Execute the strategy; return (metrics, matches_used, safety_discards)."""
    validate_strategy(strategy.fields)
    all_profiles = list(profiles)
    totals = {
        "attempts": 0, "pre_delivery_escape": 0, "warn_reached": 0,
        "warning_escape": 0, "user_click": 0, "user_submit": 0,
        "credential_exposure": 0, "takeover_success": 0,
        "official_event_signal_neutralized": 0, "blue_failure_discovery": 0,
    }
    per_seed: list[float] = []
    per_profile: dict[str, float] = {}
    difficulties: set[str] = set()
    signal_totals: dict[str, int] = {}
    behaviour = {"verify": 0, "report": 0, "click": 0, "submit": 0}
    matches = 0
    safety_discards = 0

    for seed in seeds:
        result = run_match(
            difficulty, strictness, all_profiles, int(seed),
            strategy=strategy.fields,
        )
        matches += 1
        safety_discards += len(result["safety_events"])
        messages = {int(m["id"]): m for m in result["messages"]}
        seed_score = 0.0
        for row in result["judge_evaluations"]:
            if str(row["ground_truth"]) != "forged":
                continue
            message = messages[int(row["message_id"])]
            profile = str(message["profile"])
            action = str(message["pre_delivery_action"])
            difficulties.add(str(row["true_difficulty"]))
            totals["attempts"] += 1
            gained = 0.0
            if action != "quarantine":
                totals["pre_delivery_escape"] += 1
                gained += 1.0
            if action == "warn":
                totals["warn_reached"] += 1
                gained += 0.5
            if row["warning_escape"]:
                totals["warning_escape"] += 1
                gained += 1.5
            if row["user_harm_click"]:
                totals["user_click"] += 1
                behaviour["click"] += 1
                gained += 1.0
            if row["user_harm_submit"]:
                totals["user_submit"] += 1
                behaviour["submit"] += 1
                gained += 2.0
            if row["credential_exposure"]:
                totals["credential_exposure"] += 1
                gained += 2.5
            if row["takeover_success"]:
                totals["takeover_success"] += 1
                gained += 3.0
            if row["false_negative"]:
                totals["blue_failure_discovery"] += 1
                gained += 1.0
            signals = message["signals"]
            if int(signals["official_event_record"]["score"]) == 0:
                totals["official_event_signal_neutralized"] += 1
            for name, payload in signals.items():
                score = int(payload["score"])
                if score > 0:
                    signal_totals[name] = signal_totals.get(name, 0) + score
            per_profile[profile] = per_profile.get(profile, 0.0) + gained
            seed_score += gained
        for row in result["user_actions"]:
            if str(row["action"]) == "USER_VERIFY":
                behaviour["verify"] += 1
            elif str(row["action"]) == "USER_REPORT":
                behaviour["report"] += 1
        per_seed.append(seed_score)

    top_signals = tuple(
        name for name, _ in sorted(
            signal_totals.items(), key=lambda kv: (-kv[1], kv[0])
        )[:3]
    )
    summary = (
        f"검증 {behaviour['verify']}회, 신고 {behaviour['report']}회, "
        f"클릭 {behaviour['click']}회, 제출 {behaviour['submit']}회"
    )
    metrics = RawMetrics(
        matches=matches,
        attempts=totals["attempts"],
        pre_delivery_escape=totals["pre_delivery_escape"],
        warn_reached=totals["warn_reached"],
        warning_escape=totals["warning_escape"],
        user_click=totals["user_click"],
        user_submit=totals["user_submit"],
        credential_exposure=totals["credential_exposure"],
        takeover_success=totals["takeover_success"],
        official_event_signal_neutralized=totals[
            "official_event_signal_neutralized"
        ],
        blue_failure_discovery=totals["blue_failure_discovery"],
        profiles_covered=len(per_profile),
        difficulties_covered=len(difficulties),
        per_seed_scores=tuple(per_seed),
        per_profile_scores=dict(per_profile),
        top_blue_signals=top_signals,
        user_behavior_summary=summary,
    )
    return metrics, matches, safety_discards
