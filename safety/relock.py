"""Human-only command-line utility that regenerates the approved safety lock."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from safety.constitution import LOCKED_FILES


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    values = {}
    for relative in LOCKED_FILES:
        values[relative] = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
    (ROOT / "safety" / "SAFETY.lock").write_text(
        json.dumps(values, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"SAFETY.lock regenerated for {len(values)} approved files.")


if __name__ == "__main__":
    main()
