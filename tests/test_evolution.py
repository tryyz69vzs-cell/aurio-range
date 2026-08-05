"""Adaptive Red: action-space confinement, caps, reproducibility, promotion."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from engine.match import run_match
from evolution.action_space import (
    ACTION_SPACE,
    ActionSpaceViolation,
    validate_strategy,
)
from evolution.controller import MatchBudget, run_evolution
from evolution.evaluator import (
    evaluate_strategy,
    evaluation_seeds,
    seeds_are_disjoint,
    training_seeds,
)
from evolution.fitness import compute_fitness, profile_balance, reproducibility
from evolution.models import (
    MAX_GENERATIONS,
    MAX_POPULATION,
    Candidate,
    EvolutionConfig,
    RawMetrics,
    Strategy,
    clamp_config,
)
from evolution.mutation import mutate
from evolution.population import initial_population
from evolution.selection import deduplicate, novelty, promotion_decision
from evolution.state_store import STATE_FILES, StateStore

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ("cautious", "average", "careless")


def _small_config(**overrides):
    base = dict(
        generations=2, population_size=4, training_seed_count=1,
        evaluation_seed_count=1, max_matches=60, max_seconds=60.0,
    )
    base.update(overrides)
    return EvolutionConfig(**base)


def _population(size=6, seed=7):
    return initial_population(size, PROFILES, random.Random(seed))


def test_every_action_space_value_is_a_closed_enum():
    for name, values in ACTION_SPACE.items():
        assert isinstance(values, tuple) and values, name
        for value in values:
            assert isinstance(value, (str, int, bool)), name
            if isinstance(value, str):
                assert "<" not in value and "://" not in value
                assert " " not in value


def test_strategy_rejects_fields_outside_the_allowlist():
    fields = dict(_population()[0].fields)
    fields["arbitrary_html"] = "<div>x</div>"
    with pytest.raises(ActionSpaceViolation):
        validate_strategy(fields)


@pytest.mark.parametrize(
    "payload",
    [
        {"urgency_level": "<script>"},
        {"subject_theme": "https://evil.test"},
        {"template_family": "custom_free_text"},
        {"sender_auth_level": "ANYTHING"},
    ],
)
def test_strategy_rejects_free_values(payload):
    fields = dict(_population()[0].fields)
    fields.update(payload)
    with pytest.raises(ActionSpaceViolation):
        validate_strategy(fields)


def test_mutation_changes_only_allowlisted_fields():
    rng = random.Random(3)
    population = _population()
    for parent in population:
        child = mutate(parent, 1, 0, rng)
        assert set(child.fields) == set(parent.fields)
        for name in child.changed_fields:
            assert name in ACTION_SPACE
            assert child.fields[name] in ACTION_SPACE[name]
        differing = {
            name for name in parent.fields
            if parent.fields[name] != child.fields[name]
        }
        # changed_fields must describe the real difference (coherence fix-ups
        # may add at most one extra field).
        assert set(child.changed_fields) <= differing
        assert len(differing) <= len(child.changed_fields) + 1
        validate_strategy(child.fields)


def test_mutation_changes_at_most_two_fields():
    rng = random.Random(11)
    parent = _population()[0]
    for index in range(30):
        child = mutate(parent, 1, index, rng)
        assert 1 <= len(child.changed_fields) <= 2


def test_training_and_hidden_evaluation_seeds_never_overlap():
    for base in (1, 20260731, 999983):
        train = training_seeds(base, 6)
        hidden = evaluation_seeds(base, 6)
        assert seeds_are_disjoint(train, hidden)
        assert len(set(train)) == 6 and len(set(hidden)) == 6


def test_caps_are_enforced_regardless_of_request():
    clamped = clamp_config(
        EvolutionConfig(
            generations=999, population_size=999,
            max_matches=10**9, max_seconds=10**9,
        )
    )
    assert clamped.generations == MAX_GENERATIONS
    assert clamped.population_size == MAX_POPULATION
    assert clamped.max_matches <= 2000
    assert clamped.max_seconds <= 900.0


def test_match_budget_stops_at_the_ceiling():
    budget = MatchBudget(max_matches=3, max_seconds=999)
    budget.spend(3)
    assert budget.exhausted() is True
    assert budget.stop_reason


def test_evolution_respects_the_match_budget():
    outcome = run_evolution(_small_config(max_matches=6))
    assert outcome["matches_used"] <= 6
    assert outcome["stop_reason"]


def test_evolution_is_reproducible_for_the_same_seed_and_config():
    first = run_evolution(_small_config())
    second = run_evolution(_small_config())
    assert first["best_strategy_id"] == second["best_strategy_id"]
    assert first["best_training_fitness"] == second["best_training_fitness"]
    assert first["best_evaluation_fitness"] == second["best_evaluation_fitness"]
    assert [n["strategy_id"] for n in first["lineage"]] == [
        n["strategy_id"] for n in second["lineage"]
    ]


def test_lineage_parent_child_links_are_valid():
    outcome = run_evolution(_small_config(generations=3, population_size=4))
    known = {node["strategy_id"] for node in outcome["lineage"]}
    for node in outcome["lineage"]:
        parent = node["parent_strategy_id"]
        if parent is not None:
            assert node["generation"] > 0
            assert parent != node["strategy_id"]
        else:
            assert node["generation"] == 0
        assert node["root_strategy_id"]
        assert node["keep_or_drop"] in {"keep", "drop"}
        if node["keep_or_drop"] == "drop":
            assert node["drop_reason"]
        assert node["narrative"]
    assert known


def test_duplicate_strategies_are_removed():
    population = _population(6)
    unique, duplicates = deduplicate(list(population) + list(population))
    assert len(unique) == len(population)
    assert len(duplicates) == len(population)


def test_overfitted_candidate_is_not_promoted():
    metrics = RawMetrics(
        matches=1, attempts=3, user_click=3,
        per_seed_scores=(3.0,), per_profile_scores={"careless": 3.0},
    )
    fitness = compute_fitness(metrics, novelty=1.0)
    weak = compute_fitness(RawMetrics(matches=1, attempts=3), novelty=1.0)
    candidate = Candidate(
        strategy=_population()[0],
        training_metrics=metrics,
        training_fitness=fitness,
        evaluation_metrics=RawMetrics(matches=1, attempts=3),
        evaluation_fitness=weak,
    )
    promote, reason = promotion_decision(
        candidate, None, min_novelty=0.0, min_reproducibility=0.0,
        novelty_score=1.0, reproducibility_score=1.0, profile_balance_score=1.0,
    )
    assert promote is False
    assert "과적합" in reason


def test_safety_failure_can_never_be_promoted():
    candidate = Candidate(
        strategy=_population()[0],
        training_metrics=RawMetrics(),
        training_fitness=compute_fitness(RawMetrics(), novelty=1.0),
        safety_ok=False,
        safety_detail="폐기 3건",
    )
    promote, reason = promotion_decision(
        candidate, None, min_novelty=0.0, min_reproducibility=0.0,
        novelty_score=1.0, reproducibility_score=1.0, profile_balance_score=1.0,
    )
    assert promote is False
    assert "safety" in reason


def test_safety_violation_dominates_the_fitness_score():
    metrics = RawMetrics(matches=1, attempts=3, takeover_success=3)
    clean = compute_fitness(metrics, novelty=1.0, safety_ok=True)
    unsafe = compute_fitness(metrics, novelty=1.0, safety_ok=False)
    assert unsafe.total < clean.total - 30


def test_every_generated_strategy_passes_the_engine_safety_validator():
    outcome = run_evolution(_small_config())
    assert outcome["safety_violations"] == 0
    result = run_match(
        "mixed", "balanced", list(PROFILES), 20260731,
        strategy=outcome["best_strategy_fields"],
    )
    assert result["safety_events"] == []


def test_best_strategy_can_drive_a_normal_match():
    outcome = run_evolution(_small_config())
    result = run_match(
        "mixed", "balanced", list(PROFILES), 20260731,
        strategy=outcome["best_strategy_fields"],
    )
    assert result["messages"]
    assert result["judge_evaluations"]


def test_evolution_off_preserves_the_pinned_baseline():
    result = run_match("mixed", "balanced", list(PROFILES), 20260731)
    assert result["scores"]["red"] == 0
    assert result["scores"]["blue"] == 29


def test_fitness_uses_more_than_takeover_alone():
    only_takeover = RawMetrics(matches=1, attempts=2, takeover_success=2)
    broad = RawMetrics(
        matches=1, attempts=2, takeover_success=2, user_click=2,
        warning_escape=2, pre_delivery_escape=2,
    )
    assert compute_fitness(broad, novelty=0.5).total > compute_fitness(
        only_takeover, novelty=0.5
    ).total


def test_reproducibility_and_profile_balance_behave():
    steady = RawMetrics(per_seed_scores=(2.0, 2.0, 2.0))
    noisy = RawMetrics(per_seed_scores=(0.0, 6.0, 0.0))
    assert reproducibility(steady) > reproducibility(noisy)
    balanced = RawMetrics(per_profile_scores={"a": 1.0, "b": 1.0, "c": 1.0})
    skewed = RawMetrics(per_profile_scores={"a": 9.0, "b": 0.0, "c": 0.0})
    assert profile_balance(balanced) > profile_balance(skewed)


def test_evolution_cannot_touch_source_or_policy_files(tmp_path):
    before = {
        path: path.read_bytes()
        for path in list((ROOT / "safety").glob("*"))
        + list((ROOT / "engine").glob("*.py"))
        + list((ROOT / "brandkit").glob("*"))
        if path.is_file()
    }
    run_evolution(_small_config())
    for path, payload in before.items():
        assert path.read_bytes() == payload, path.name


def test_state_store_only_writes_the_five_allowed_files(tmp_path):
    store = StateStore(tmp_path / "evolution_state")
    outcome = run_evolution(_small_config())
    store.save_run(outcome)
    written = sorted(p.name for p in (tmp_path / "evolution_state").iterdir())
    assert written == sorted(STATE_FILES)
    with pytest.raises(ValueError):
        store.path("app.py")


def test_session_state_is_isolated_between_runs(tmp_path):
    first = StateStore(tmp_path / "a")
    second = StateStore(tmp_path / "b")
    first.write("state.json", {"runs": 1})
    assert second.read("state.json", {"runs": 0}) == {"runs": 0}
