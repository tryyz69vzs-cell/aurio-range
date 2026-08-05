"""The evolution loop with hard caps on generations, matches, and wall time."""

from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from typing import Any, Callable

from evolution.evaluator import (
    evaluate_strategy,
    evaluation_seeds,
    training_seeds,
)
from evolution.fitness import compute_fitness, profile_balance, reproducibility
from evolution.lineage import build_node, narrate
from evolution.models import (
    Candidate,
    EvolutionConfig,
    Strategy,
    clamp_config,
)
from evolution.mutation import mutate
from evolution.population import restore_population, seed_population
from evolution.selection import (
    deduplicate,
    novelty,
    promotion_decision,
    select_parents,
    similarity,
)


class MatchBudget:
    """Stops the run cleanly at the configured match or time ceiling."""

    def __init__(self, max_matches: int, max_seconds: float):
        self.max_matches = int(max_matches)
        self.max_seconds = float(max_seconds)
        self.used = 0
        self.started = time.monotonic()
        self.stop_reason = ""

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def remaining(self) -> int:
        return max(0, self.max_matches - self.used)

    def exhausted(self) -> bool:
        if self.used >= self.max_matches:
            self.stop_reason = "최대 경기 수 상한에 도달했습니다."
            return True
        if self.elapsed >= self.max_seconds:
            self.stop_reason = "최대 실행 시간 상한에 도달했습니다."
            return True
        return False

    def spend(self, count: int) -> None:
        self.used += int(count)


def run_evolution(
    config: EvolutionConfig,
    progress: Callable[[dict[str, Any]], None] | None = None,
    carried_population: Any = None,
    carried_hall_of_fame: Any = None,
    generation_offset: int = 0,
) -> dict[str, Any]:
    """Run the full loop and return a JSON-serialisable outcome.

    When a previous run's population or hall of fame is supplied, the survivors
    are revalidated against the current action space and seeded into the first
    generation so lineage continues across runs instead of restarting.
    """
    config = clamp_config(config)
    rng = random.Random(config.base_seed)
    train = training_seeds(config.base_seed, config.training_seed_count)
    hidden = evaluation_seeds(config.base_seed, config.evaluation_seed_count)
    budget = MatchBudget(config.max_matches, config.max_seconds)

    carried = restore_population(carried_population, carried_hall_of_fame)
    carried_ids = {s.strategy_id for s in carried}
    carried_roots = {s.root_strategy_id for s in carried}
    population = seed_population(
        config.population_size, config.profiles, rng, carried,
        generation=generation_offset,
    )
    population, _ = deduplicate(population)
    seen_fingerprints = {s.fingerprint for s in population}

    lineage: list[dict[str, Any]] = []
    hall_of_fame: list[dict[str, Any]] = []
    by_id: dict[str, Candidate] = {}
    generations_completed = 0
    safety_violations = 0
    duplicates_dropped = 0
    evaluated = 0

    def assess(strategy: Strategy, pool: list[Strategy]) -> Candidate | None:
        nonlocal evaluated, safety_violations
        if budget.exhausted():
            return None
        metrics, used, discards = evaluate_strategy(
            strategy, train, config.profiles, config.difficulty, config.strictness
        )
        budget.spend(used)
        evaluated += 1
        safe = discards == 0
        if not safe:
            safety_violations += 1
        novelty_score = novelty(strategy, pool)
        training = compute_fitness(
            metrics, novelty=novelty_score, safety_ok=safe,
            lineage_diversity=min(1.0, len(seen_fingerprints) / 30.0),
        )
        candidate = Candidate(
            strategy=strategy,
            training_metrics=metrics,
            training_fitness=training,
            safety_ok=safe,
            safety_detail="통과" if safe else f"안전 검증기 폐기 {discards}건",
        )
        return candidate

    current: list[Strategy] = population
    base_generation = generation_offset
    for generation in range(config.generations):
        if budget.exhausted():
            break
        candidates: list[Candidate] = []
        for strategy in current:
            candidate = assess(strategy, current)
            if candidate is None:
                break
            candidates.append(candidate)
        if not candidates:
            break

        parents = select_parents(candidates, max(2, len(candidates) // 2))
        promoted_this_gen = 0
        for candidate in parents:
            if budget.exhausted():
                break
            if not candidate.safety_ok:
                continue
            metrics, used, discards = evaluate_strategy(
                candidate.strategy, hidden, config.profiles,
                config.difficulty, config.strictness,
            )
            budget.spend(used)
            eval_safe = discards == 0
            delta = 0.0
            if candidate.training_score != 0:
                delta = (
                    compute_fitness(metrics, novelty=0.0, safety_ok=eval_safe).total
                    - candidate.training_score
                ) / max(1.0, abs(candidate.training_score))
            evaluation = compute_fitness(
                metrics,
                novelty=novelty(candidate.strategy, current),
                safety_ok=eval_safe,
                evaluation_delta=delta,
            )
            parent_candidate = by_id.get(candidate.strategy.parent_strategy_id or "")
            scored = Candidate(
                strategy=candidate.strategy,
                training_metrics=candidate.training_metrics,
                training_fitness=candidate.training_fitness,
                evaluation_metrics=metrics,
                evaluation_fitness=evaluation,
                safety_ok=candidate.safety_ok and eval_safe,
                safety_detail=candidate.safety_detail,
            )
            novelty_score = novelty(scored.strategy, [c.strategy for c in by_id.values()])
            promote, reason = promotion_decision(
                scored,
                parent_candidate,
                min_novelty=config.min_novelty,
                min_reproducibility=config.min_reproducibility,
                novelty_score=novelty_score,
                reproducibility_score=reproducibility(scored.training_metrics),
                profile_balance_score=profile_balance(scored.training_metrics),
            )
            final = Candidate(
                strategy=scored.strategy,
                training_metrics=scored.training_metrics,
                training_fitness=scored.training_fitness,
                evaluation_metrics=scored.evaluation_metrics,
                evaluation_fitness=scored.evaluation_fitness,
                safety_ok=scored.safety_ok,
                safety_detail=scored.safety_detail,
                keep_or_drop="keep" if promote else "drop",
                drop_reason="" if promote else reason,
                promoted=promote,
            )
            by_id[final.strategy.strategy_id] = final
            lineage.append(
                build_node(final, parent_candidate, novelty_score,
                           narrate(final, parent_candidate))
            )
            if promote:
                promoted_this_gen += 1
                entry = final.strategy.as_dict()
                entry["evaluation_fitness"] = round(final.evaluation_score, 6)
                entry["training_fitness"] = round(final.training_score, 6)
                hall_of_fame.append(entry)

        generations_completed += 1
        if progress is not None:
            progress(
                {
                    "generation": generation + 1,
                    "evaluated": evaluated,
                    "matches_used": budget.used,
                    "matches_remaining": budget.remaining(),
                    "promoted": promoted_this_gen,
                    "safety_violations": safety_violations,
                    "duplicates_dropped": duplicates_dropped,
                }
            )
        if generation + 1 >= config.generations or budget.exhausted():
            break

        children: list[Strategy] = []
        for index, parent in enumerate(parents):
            for offset in range(2):
                child = mutate(
                    parent.strategy,
                    base_generation + generation + 1,
                    index * 2 + offset,
                    rng,
                )
                if child.fingerprint in seen_fingerprints:
                    duplicates_dropped += 1
                    continue
                if any(
                    similarity(child, other) >= 0.99 for other in children
                ):
                    duplicates_dropped += 1
                    continue
                seen_fingerprints.add(child.fingerprint)
                children.append(child)
                if len(children) >= config.population_size:
                    break
            if len(children) >= config.population_size:
                break
        if not children:
            budget.stop_reason = "새로운 후보를 만들지 못했습니다."
            break
        current = children

    ranked = sorted(by_id.values(), key=lambda c: -c.evaluation_score)
    best = ranked[0] if ranked else None
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "enabled": True,
        "generations_requested": config.generations,
        "generations_completed": generations_completed,
        "population_size": config.population_size,
        "training_seeds": list(train),
        "evaluation_seeds": list(hidden),
        "matches_used": budget.used,
        "matches_allowed": config.max_matches,
        "elapsed_seconds": round(budget.elapsed, 3),
        "evaluated_candidates": evaluated,
        "safety_violations": safety_violations,
        "duplicates_dropped": duplicates_dropped,
        "stop_reason": budget.stop_reason or "정상 종료",
        "generation_offset": generation_offset,
        "carried_strategy_ids": sorted(carried_ids),
        "carried_root_strategy_ids": sorted(r for r in carried_roots if r),
        "carried_count": len(carried),
        "best_strategy_id": None if best is None else best.strategy.strategy_id,
        "best_strategy_fields": None if best is None else dict(best.strategy.fields),
        "best_training_fitness": 0.0 if best is None else round(best.training_score, 6),
        "best_evaluation_fitness": (
            0.0 if best is None else round(best.evaluation_score, 6)
        ),
        "population": [s.as_dict() for s in current],
        "hall_of_fame": hall_of_fame,
        "lineage": lineage,
    }
