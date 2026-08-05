"""Convert an evolution outcome into the sanitized report summary type."""

from __future__ import annotations

from typing import Any, Mapping

from reporting.models import SafeEvolutionSummary, SafeStrategyLineage


def build_evolution_summary(
    outcome: Mapping[str, Any] | None,
) -> SafeEvolutionSummary | None:
    """None when evolution was not used; otherwise a frozen report summary."""
    if not outcome or not outcome.get("enabled"):
        return None
    nodes = []
    for row in outcome.get("lineage", []):
        nodes.append(
            SafeStrategyLineage(
                generation=int(row.get("generation", 0)),
                strategy_id=str(row.get("strategy_id", "")),
                parent_strategy_id=row.get("parent_strategy_id"),
                changed_fields=tuple(row.get("changed_fields", ())),
                change_reason=str(
                    row.get("narrative") or row.get("mutation_reason") or ""
                ),
                training_fitness=float(row.get("training_fitness", 0.0)),
                evaluation_fitness=float(row.get("evaluation_fitness", 0.0)),
                delta_from_parent=float(row.get("delta_from_parent", 0.0)),
                top_detected_blue_signals=tuple(
                    row.get("top_detected_blue_signals", ())
                ),
                user_behavior_summary=str(row.get("user_behavior_summary", "")),
                keep_or_drop=str(row.get("keep_or_drop", "pending")),
            )
        )
    return SafeEvolutionSummary(
        enabled=True,
        generations=int(outcome.get("generations_completed", 0)),
        population_size=int(outcome.get("population_size", 0)),
        best_strategy_id=str(outcome.get("best_strategy_id") or "—"),
        best_training_fitness=float(outcome.get("best_training_fitness", 0.0)),
        best_evaluation_fitness=float(outcome.get("best_evaluation_fitness", 0.0)),
        training_seeds=tuple(int(s) for s in outcome.get("training_seeds", ())),
        evaluation_seed_count=len(outcome.get("evaluation_seeds", ())),
        lineage=tuple(nodes),
    )
