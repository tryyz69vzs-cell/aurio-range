"""Phase B continuity: a later run must build on the earlier one."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from evolution.controller import run_evolution
from evolution.models import EvolutionConfig
from evolution.population import (
    restore_population,
    restore_strategy,
    seed_population,
)
from evolution.state_store import StateStore

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ("cautious", "average", "careless")


def _config(**overrides):
    base = dict(
        generations=2, population_size=4, training_seed_count=1,
        evaluation_seed_count=1, max_matches=60, max_seconds=90.0,
    )
    base.update(overrides)
    return EvolutionConfig(**base)


def _first_run():
    return run_evolution(_config())


def test_second_run_loads_the_saved_population(tmp_path):
    first = _first_run()
    store = StateStore(tmp_path / "evolution_state")
    store.save_run(first)

    saved_population = store.read("population.json", [])
    saved_fame = store.read("hall_of_fame.json", [])
    assert saved_population

    second = run_evolution(
        _config(),
        carried_population=saved_population,
        carried_hall_of_fame=saved_fame,
        generation_offset=int(store.read("state.json", {})["generation"]),
    )
    assert second["carried_count"] > 0
    assert second["carried_strategy_ids"]


def test_second_run_strategies_link_back_to_the_first():
    first = _first_run()
    previous_ids = {s["strategy_id"] for s in first["population"]}
    previous_roots = {s["root_strategy_id"] for s in first["population"]}
    previous_ids |= {n["strategy_id"] for n in first["lineage"]}
    previous_roots |= {n["root_strategy_id"] for n in first["lineage"]}

    second = run_evolution(
        _config(),
        carried_population=first["population"],
        carried_hall_of_fame=first["hall_of_fame"],
        generation_offset=first["generations_completed"],
    )
    linked = [
        node for node in second["lineage"]
        if node["strategy_id"] in previous_ids
        or node["root_strategy_id"] in previous_roots
        or (node["parent_strategy_id"] or "") in previous_ids
    ]
    assert linked, "두 번째 실행이 이전 계보와 연결되어야 합니다."


def test_generation_numbers_continue_across_runs():
    first = _first_run()
    offset = first["generations_completed"]
    second = run_evolution(
        _config(),
        carried_population=first["population"],
        carried_hall_of_fame=first["hall_of_fame"],
        generation_offset=offset,
    )
    assert second["generation_offset"] == offset
    assert max(n["generation"] for n in second["lineage"]) >= offset


def test_hall_of_fame_entries_are_carried_first():
    first = _first_run()
    fake_fame = [
        {
            "strategy_id": "hof-best",
            "generation": 5,
            "root_strategy_id": "hof-root",
            "evaluation_fitness": 99.0,
            "fields": dict(first["population"][0]["fields"]),
        }
    ]
    restored = restore_population(first["population"], fake_fame)
    assert restored[0].strategy_id == "hof-best"
    assert restored[0].root_strategy_id == "hof-root"


def test_disallowed_stored_fields_are_discarded():
    first = _first_run()
    payload = dict(first["population"][0])
    payload["fields"] = dict(payload["fields"])
    payload["fields"]["arbitrary_html"] = "<div>x</div>"
    assert restore_strategy(payload) is None

    payload2 = dict(first["population"][0])
    payload2["fields"] = dict(payload2["fields"])
    payload2["fields"]["urgency_level"] = "catastrophic"
    assert restore_strategy(payload2) is None

    payload3 = dict(first["population"][0])
    payload3["fields"] = dict(payload3["fields"])
    payload3["fields"].pop("target_profile")
    assert restore_strategy(payload3) is None


@pytest.mark.parametrize(
    "broken",
    ["not-a-dict", 42, None, {"strategy_id": "x"}, {"fields": "nope"},
     {"fields": {}, "strategy_id": ""}],
)
def test_corrupt_entries_never_restore(broken):
    assert restore_strategy(broken) is None


def test_corrupt_state_files_fall_back_to_a_fresh_population(tmp_path):
    state_dir = tmp_path / "evolution_state"
    state_dir.mkdir(parents=True)
    (state_dir / "population.json").write_text("{ this is not json", "utf-8")
    (state_dir / "hall_of_fame.json").write_text("also broken", "utf-8")
    store = StateStore(state_dir)
    assert store.read("population.json", []) == []
    assert store.read("hall_of_fame.json", []) == []

    outcome = run_evolution(
        _config(),
        carried_population=store.read("population.json", []),
        carried_hall_of_fame=store.read("hall_of_fame.json", []),
    )
    assert outcome["carried_count"] == 0
    assert outcome["population"]
    assert outcome["safety_violations"] == 0


def test_seed_population_fills_the_gap_and_keeps_survivors():
    import random

    first = _first_run()
    carried = restore_population(first["population"], [])
    filled = seed_population(8, PROFILES, random.Random(1), carried[:2])
    assert len(filled) == 8
    assert filled[0].strategy_id == carried[0].strategy_id
    assert len({s.fingerprint for s in filled}) == 8


def test_restored_strategies_still_pass_the_engine_safety_validator():
    from engine.match import run_match

    first = _first_run()
    for payload in first["population"][:2]:
        strategy = restore_strategy(payload)
        assert strategy is not None
        result = run_match(
            "mixed", "balanced", list(PROFILES), 20260731,
            strategy=strategy.fields,
        )
        assert result["safety_events"] == []


def test_cli_runs_twice_and_carries_state(tmp_path):
    """End-to-end Phase B: two consecutive CLI runs, second inherits state."""
    workdir = tmp_path / "phase_b"
    workdir.mkdir()
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": str(ROOT),
            "AURIO_GENERATIONS": "2",
            "AURIO_POPULATION": "4",
            "AURIO_TRAINING_SEEDS": "1",
            "AURIO_EVALUATION_SEEDS": "1",
            "AURIO_MAX_MATCHES": "60",
            "AURIO_MAX_SECONDS": "120",
        }
    )
    outputs = []
    for _ in range(2):
        completed = subprocess.run(
            [sys.executable, "-m", "tools.run_evolution"],
            cwd=workdir, env=env, capture_output=True, text=True,
        )
        assert completed.returncode == 0, completed.stderr
        outputs.append(completed.stdout)

    assert "이어받은 전략 0개" in outputs[0]
    assert "이어받은 전략 0개" not in outputs[1]

    state = json.loads((workdir / "evolution_state" / "state.json").read_text("utf-8"))
    assert state["runs"] == 2
    assert state["generation"] > 0
    lineage = json.loads(
        (workdir / "evolution_state" / "lineage.json").read_text("utf-8")
    )
    assert len(lineage) > 0
    assert max(n["generation"] for n in lineage) >= state["generation"] - 2


def _cli_env() -> dict:
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": str(ROOT),
            "AURIO_GENERATIONS": "2",
            "AURIO_POPULATION": "4",
            "AURIO_TRAINING_SEEDS": "1",
            "AURIO_EVALUATION_SEEDS": "1",
            "AURIO_MAX_MATCHES": "60",
            "AURIO_MAX_SECONDS": "180",
        }
    )
    return env


def _state_dir(workdir: Path) -> Path:
    return workdir / "evolution_state"


def _load(workdir: Path, name: str):
    return json.loads((_state_dir(workdir) / name).read_text("utf-8"))


def test_five_consecutive_runs_keep_generation_numbers_linear(tmp_path):
    """Regression: restored generations used to be offset again every run."""
    workdir = tmp_path / "phase_b_long"
    workdir.mkdir()
    env = _cli_env()
    observed = []
    for index in range(1, 6):
        completed = subprocess.run(
            [sys.executable, "-m", "tools.run_evolution"],
            cwd=workdir, env=env, capture_output=True, text=True,
        )
        assert completed.returncode == 0, completed.stderr
        state = _load(workdir, "state.json")
        lineage = _load(workdir, "lineage.json")
        population = _load(workdir, "population.json")
        observed.append(
            {
                "run": index,
                "state_generation": state["generation"],
                "lineage_max": max(n["generation"] for n in lineage),
                "population_generations": sorted(
                    {p["generation"] for p in population}
                ),
                "ids": [n["strategy_id"] for n in lineage],
            }
        )

    assert [row["state_generation"] for row in observed] == [2, 4, 6, 8, 10]
    assert [row["lineage_max"] for row in observed] == [1, 3, 5, 7, 9]
    for index, row in enumerate(observed):
        assert row["population_generations"] == [2 * index + 1]
        # No lineage node may reach the state generation counter.
        assert row["lineage_max"] < row["state_generation"]
        assert len(row["ids"]) == len(set(row["ids"])), "strategy_id 중복"


def test_long_run_preserves_parent_and_root_links(tmp_path):
    workdir = tmp_path / "phase_b_links"
    workdir.mkdir()
    env = _cli_env()
    for _ in range(3):
        completed = subprocess.run(
            [sys.executable, "-m", "tools.run_evolution"],
            cwd=workdir, env=env, capture_output=True, text=True,
        )
        assert completed.returncode == 0, completed.stderr

    lineage = _load(workdir, "lineage.json")
    known = {node["strategy_id"] for node in lineage}
    roots = {node["root_strategy_id"] for node in lineage}
    assert roots, "root 계보가 유지되어야 합니다."
    linked = [
        node for node in lineage
        if node["parent_strategy_id"] and node["parent_strategy_id"] in known
    ]
    assert linked, "부모-자식 연결이 이어져야 합니다."
    for node in lineage:
        assert node["root_strategy_id"]
        if node["parent_strategy_id"]:
            assert node["generation"] > 0

    # A later run must not restart identifiers at generation zero.
    late = [n for n in lineage if n["generation"] >= 4]
    assert late
    assert all(not n["strategy_id"].startswith("g0-") for n in late)


def test_restored_generations_are_absolute_not_re_offset():
    first = _first_run()
    saved = first["population"]
    original = {s["strategy_id"]: s["generation"] for s in saved}
    restored = restore_population(saved, [])
    assert restored
    for strategy in restored:
        assert strategy.generation == original[strategy.strategy_id]
    # Restoring twice must not drift either.
    again = restore_population([s.as_dict() for s in restored], [])
    for strategy in again:
        assert strategy.generation == original[strategy.strategy_id]


def test_filler_strategies_carry_the_current_absolute_generation():
    import random

    first = _first_run()
    carried = restore_population(first["population"], [])[:1]
    filled = seed_population(4, PROFILES, random.Random(2), carried, generation=4)
    assert filled[0].generation == carried[0].generation
    fillers = filled[1:]
    assert fillers
    for strategy in fillers:
        assert strategy.generation == 4
        assert strategy.strategy_id.startswith("g4-seed-")
        assert not strategy.strategy_id.startswith("g0-")
    assert len({s.strategy_id for s in filled}) == len(filled)


def test_filler_ids_are_deterministic_for_the_same_inputs():
    import random

    filled_a = seed_population(5, PROFILES, random.Random(9), (), generation=6)
    filled_b = seed_population(5, PROFILES, random.Random(9), (), generation=6)
    assert [s.strategy_id for s in filled_a] == [s.strategy_id for s in filled_b]
    assert all(s.generation == 6 for s in filled_a)


def test_hall_of_fame_entries_keep_the_full_lineage_record():
    outcome = run_evolution(_config(generations=3, population_size=6))
    entries = outcome["hall_of_fame"]
    if not entries:
        pytest.skip("이 설정에서는 승격된 전략이 없습니다.")
    for entry in entries:
        for key in (
            "strategy_id", "parent_strategy_id", "root_strategy_id",
            "generation", "origin_pattern", "changed_fields",
            "previous_values", "new_values", "mutation_reason", "fields",
            "training_fitness", "evaluation_fitness",
        ):
            assert key in entry, key
        restored = restore_strategy(entry)
        assert restored is not None
        assert restored.root_strategy_id == entry["root_strategy_id"]
        assert restored.generation == entry["generation"]


def test_hall_of_fame_restore_does_not_reset_root_to_self():
    fame = [
        {
            "strategy_id": "g5-01-child",
            "parent_strategy_id": "g4-00-parent",
            "root_strategy_id": "g0-seed-00-origin",
            "generation": 5,
            "origin_pattern": "event_shadowing",
            "changed_fields": ["urgency_level"],
            "previous_values": {"urgency_level": "low"},
            "new_values": {"urgency_level": "high"},
            "mutation_reason": "테스트",
            "evaluation_fitness": 5.0,
            "training_fitness": 4.0,
            "fields": dict(_first_run()["population"][0]["fields"]),
        }
    ]
    restored = restore_population([], fame)
    assert len(restored) == 1
    assert restored[0].root_strategy_id == "g0-seed-00-origin"
    assert restored[0].parent_strategy_id == "g4-00-parent"
    assert restored[0].generation == 5


def test_lineage_is_deduplicated_when_a_strategy_is_re_evaluated(tmp_path):
    store = StateStore(tmp_path / "evolution_state")
    node = {
        "strategy_id": "g1-00-abc", "generation": 1,
        "root_strategy_id": "g0-seed-00-x", "parent_strategy_id": None,
        "evaluation_fitness": 1.0,
    }
    store.save_run({"lineage": [node], "population": [], "hall_of_fame": []})
    updated = dict(node)
    updated["evaluation_fitness"] = 7.5
    store.save_run({"lineage": [updated], "population": [], "hall_of_fame": []})
    lineage = store.read("lineage.json", [])
    assert len(lineage) == 1
    assert lineage[0]["evaluation_fitness"] == 7.5
