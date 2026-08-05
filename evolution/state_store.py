"""JSON persistence for Phase B (GitHub Actions) continuous evolution.

Only these five files are ever written, and only inside the state directory.
No code, policy, registry, renderer, template, workflow, or test is touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

STATE_DIR_NAME = "evolution_state"
STATE_FILES = (
    "state.json",
    "population.json",
    "hall_of_fame.json",
    "lineage.json",
    "evaluation_seeds.json",
)


class StateStore:
    """Reads and writes the five allowed evolution state files."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def path(self, name: str) -> Path:
        if name not in STATE_FILES:
            raise ValueError(f"허용되지 않은 상태 파일: {name}")
        return self.root / name

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def read(self, name: str, default: Any) -> Any:
        target = self.path(name)
        if not target.exists():
            return default
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return default

    def write(self, name: str, payload: Any) -> None:
        self.ensure()
        self.path(name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def save_run(self, outcome: Mapping[str, Any]) -> None:
        """Persist one completed evolution run across the five files."""
        state = self.read("state.json", {"runs": 0, "generation": 0})
        state["runs"] = int(state.get("runs", 0)) + 1
        state["generation"] = int(state.get("generation", 0)) + int(
            outcome.get("generations_completed", 0)
        )
        state["last_best_strategy_id"] = outcome.get("best_strategy_id")
        state["last_best_evaluation_fitness"] = outcome.get(
            "best_evaluation_fitness"
        )
        state["last_run_at"] = outcome.get("generated_at")
        state["stop_reason"] = outcome.get("stop_reason")
        self.write("state.json", state)
        self.write("population.json", outcome.get("population", []))
        hall = self.read("hall_of_fame.json", [])
        known = {entry.get("strategy_id") for entry in hall}
        for entry in outcome.get("hall_of_fame", []):
            if entry.get("strategy_id") not in known:
                hall.append(entry)
        hall.sort(key=lambda e: -float(e.get("evaluation_fitness", 0.0)))
        self.write("hall_of_fame.json", hall[:50])
        # Lineage is a family tree: one node per strategy. A carried strategy
        # re-evaluated in a later run updates its node instead of appending a
        # duplicate id.
        lineage = self.read("lineage.json", [])
        if not isinstance(lineage, list):
            lineage = []
        merged: dict[str, Any] = {}
        order: list[str] = []
        for node in list(lineage) + list(outcome.get("lineage", [])):
            if not isinstance(node, dict):
                continue
            key = str(node.get("strategy_id", ""))
            if not key:
                continue
            if key not in merged:
                order.append(key)
            merged[key] = node
        self.write("lineage.json", [merged[key] for key in order][-2000:])
        self.write(
            "evaluation_seeds.json",
            {
                "evaluation_seeds": outcome.get("evaluation_seeds", []),
                "note": "숨김 평가 전용 시드입니다. 훈련에 사용하지 않습니다.",
            },
        )
