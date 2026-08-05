"""Frozen data types for Adaptive Red."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from evolution.action_space import validate_strategy


@dataclass(frozen=True)
class Strategy:
    """An allowlisted, validated strategy. Immutable once constructed."""

    fields: Mapping[str, Any]
    strategy_id: str
    parent_strategy_id: str | None = None
    root_strategy_id: str | None = None
    generation: int = 0
    origin_pattern: str = "seed"
    changed_fields: tuple[str, ...] = ()
    previous_values: Mapping[str, Any] = field(default_factory=dict)
    new_values: Mapping[str, Any] = field(default_factory=dict)
    mutation_reason: str = "초기 population"

    def __post_init__(self) -> None:
        validate_strategy(self.fields)
        object.__setattr__(self, "fields", dict(self.fields))
        if self.root_strategy_id is None:
            object.__setattr__(self, "root_strategy_id", self.strategy_id)

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            {k: self.fields[k] for k in sorted(self.fields)},
            ensure_ascii=False, sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "parent_strategy_id": self.parent_strategy_id,
            "root_strategy_id": self.root_strategy_id,
            "generation": self.generation,
            "origin_pattern": self.origin_pattern,
            "changed_fields": list(self.changed_fields),
            "previous_values": dict(self.previous_values),
            "new_values": dict(self.new_values),
            "mutation_reason": self.mutation_reason,
            "fingerprint": self.fingerprint,
            "fields": dict(self.fields),
        }


@dataclass(frozen=True)
class RawMetrics:
    """Aggregated Red outcome counters across the matches for one strategy."""

    matches: int = 0
    attempts: int = 0
    pre_delivery_escape: int = 0
    warn_reached: int = 0
    warning_escape: int = 0
    user_click: int = 0
    user_submit: int = 0
    credential_exposure: int = 0
    takeover_success: int = 0
    official_event_signal_neutralized: int = 0
    blue_failure_discovery: int = 0
    profiles_covered: int = 0
    difficulties_covered: int = 0
    per_seed_scores: tuple[float, ...] = ()
    per_profile_scores: Mapping[str, float] = field(default_factory=dict)
    top_blue_signals: tuple[str, ...] = ()
    user_behavior_summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "matches": self.matches,
            "attempts": self.attempts,
            "pre_delivery_escape": self.pre_delivery_escape,
            "warn_reached": self.warn_reached,
            "warning_escape": self.warning_escape,
            "user_click": self.user_click,
            "user_submit": self.user_submit,
            "credential_exposure": self.credential_exposure,
            "takeover_success": self.takeover_success,
            "official_event_signal_neutralized":
                self.official_event_signal_neutralized,
            "blue_failure_discovery": self.blue_failure_discovery,
            "profiles_covered": self.profiles_covered,
            "difficulties_covered": self.difficulties_covered,
            "per_seed_scores": list(self.per_seed_scores),
            "per_profile_scores": dict(self.per_profile_scores),
            "top_blue_signals": list(self.top_blue_signals),
            "user_behavior_summary": self.user_behavior_summary,
        }


@dataclass(frozen=True)
class FitnessBreakdown:
    """Every component score alongside the final number."""

    total: float
    components: Mapping[str, float]
    penalties: Mapping[str, float]

    @property
    def component_total(self) -> float:
        """Raw performance without penalties, used for like-for-like gates."""
        return sum(self.components.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": round(self.total, 6),
            "components": {k: round(v, 6) for k, v in self.components.items()},
            "penalties": {k: round(v, 6) for k, v in self.penalties.items()},
        }


@dataclass(frozen=True)
class Candidate:
    """A strategy plus its training and hidden-evaluation results."""

    strategy: Strategy
    training_metrics: RawMetrics
    training_fitness: FitnessBreakdown
    evaluation_metrics: RawMetrics | None = None
    evaluation_fitness: FitnessBreakdown | None = None
    safety_ok: bool = True
    safety_detail: str = "통과"
    keep_or_drop: str = "pending"
    drop_reason: str = ""
    promoted: bool = False

    @property
    def training_score(self) -> float:
        return self.training_fitness.total

    @property
    def evaluation_score(self) -> float:
        return 0.0 if self.evaluation_fitness is None else self.evaluation_fitness.total

    @property
    def training_performance(self) -> float:
        return self.training_fitness.component_total

    @property
    def evaluation_performance(self) -> float:
        """Hidden-seed performance without the generalization penalty.

        The reported evaluation score already subtracts an overfit penalty, so
        comparing it against raw training fitness would count that penalty
        twice and make promotion unreachable.
        """
        return (
            0.0 if self.evaluation_fitness is None
            else self.evaluation_fitness.component_total
        )


@dataclass(frozen=True)
class EvolutionConfig:
    """User-facing knobs with hard caps applied by the controller."""

    enabled: bool = True
    generations: int = 3
    population_size: int = 8
    training_seed_count: int = 2
    evaluation_seed_count: int = 2
    profiles: tuple[str, ...] = ("cautious", "average", "careless")
    difficulty: str = "mixed"
    strictness: str = "balanced"
    max_matches: int = 240
    max_seconds: float = 90.0
    min_novelty: float = 0.05
    min_reproducibility: float = 0.5
    base_seed: int = 20260731


MAX_GENERATIONS = 10
MAX_POPULATION = 30
MAX_MATCHES = 2000
MAX_SECONDS = 900.0


def clamp_config(config: EvolutionConfig) -> EvolutionConfig:
    """Enforce absolute caps regardless of what the caller asked for."""
    return EvolutionConfig(
        enabled=config.enabled,
        generations=max(1, min(int(config.generations), MAX_GENERATIONS)),
        population_size=max(2, min(int(config.population_size), MAX_POPULATION)),
        training_seed_count=max(1, min(int(config.training_seed_count), 6)),
        evaluation_seed_count=max(1, min(int(config.evaluation_seed_count), 6)),
        profiles=tuple(config.profiles) or ("careless",),
        difficulty=config.difficulty,
        strictness=config.strictness,
        max_matches=max(1, min(int(config.max_matches), MAX_MATCHES)),
        max_seconds=max(1.0, min(float(config.max_seconds), MAX_SECONDS)),
        min_novelty=float(config.min_novelty),
        min_reproducibility=float(config.min_reproducibility),
        base_seed=int(config.base_seed),
    )
