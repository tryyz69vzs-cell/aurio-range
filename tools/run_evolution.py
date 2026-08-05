"""Phase B entry point: evolve, build a report bundle, persist allowed state."""

from __future__ import annotations

import os
from pathlib import Path

from engine.match import run_match
from evolution.controller import run_evolution
from evolution.models import EvolutionConfig
from evolution.reporting import build_evolution_summary
from evolution.state_store import STATE_DIR_NAME, StateStore
from reporting.bundle import build_bundle
from reporting.red_report import build_red_report
from safety.guard import arena_gate


REPORT_DIR = Path("reports")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def main() -> int:
    arena_gate()
    config = EvolutionConfig(
        generations=_int("AURIO_GENERATIONS", 3),
        population_size=_int("AURIO_POPULATION", 8),
        training_seed_count=_int("AURIO_TRAINING_SEEDS", 2),
        evaluation_seed_count=_int("AURIO_EVALUATION_SEEDS", 2),
        max_matches=_int("AURIO_MAX_MATCHES", 240),
        max_seconds=float(_int("AURIO_MAX_SECONDS", 600)),
        base_seed=_int("AURIO_SEED", 20260731),
    )
    store = StateStore(STATE_DIR_NAME)
    previous_state = store.read("state.json", {})
    carried_population = store.read("population.json", [])
    carried_hall = store.read("hall_of_fame.json", [])
    try:
        generation_offset = int(previous_state.get("generation", 0) or 0)
    except (TypeError, ValueError, AttributeError):
        generation_offset = 0

    outcome = run_evolution(
        config,
        carried_population=carried_population,
        carried_hall_of_fame=carried_hall,
        generation_offset=generation_offset,
    )
    print(
        f"이전 상태에서 이어받은 전략 {outcome['carried_count']}개 "
        f"(generation offset {generation_offset})"
    )
    if outcome["safety_violations"] > 0:
        print("safety violation이 발생해 상태를 저장하지 않습니다.")
        return 1

    strategy = outcome.get("best_strategy_fields")
    result = run_match(
        "mixed", "balanced", ["cautious", "average", "careless"],
        config.base_seed, strategy=strategy,
    )
    if result["safety_events"]:
        print("경기에서 안전 이벤트가 발생해 상태를 저장하지 않습니다.")
        return 1

    report = build_red_report(result, build_evolution_summary(outcome))
    filename, payload = build_bundle(result, report)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / filename).write_bytes(payload)
    (REPORT_DIR / "latest.txt").write_text(filename, encoding="utf-8")

    store.save_run(outcome)
    print(
        f"세대 {outcome['generations_completed']}, 경기 {outcome['matches_used']}, "
        f"최고 전략 {outcome['best_strategy_id']}, 보고서 {filename}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
