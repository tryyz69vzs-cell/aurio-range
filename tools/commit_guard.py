"""Refuse a Phase B commit that touches anything except allowed state files.

Run from CI after evolution. Exits non-zero when a forbidden path changed, so
the workflow stops before committing code, policy, renderer, or workflows.

Untracked directories are expanded to individual files. On a first run the
whole `evolution_state/` and `reports/` trees are new, and plain
`git status --porcelain` collapses them to `?? evolution_state/`. Deciding on a
directory entry would either block a legitimate first run or wave through
whatever else happens to be inside it, so every file is checked on its own.
"""

from __future__ import annotations

import subprocess
import sys


ALLOWED_STATE_PREFIX = "evolution_state/"
ALLOWED_REPORT_PREFIX = "reports/"
ALLOWED_STATE_SUFFIXES = (".json",)
ALLOWED_REPORT_SUFFIXES = (".json", ".md", ".csv", ".zip")
ALLOWED_EXACT_PATHS = ("reports/latest.txt",)

# Retained for callers that only need a quick prefix check.
ALLOWED_PREFIXES = (ALLOWED_STATE_PREFIX, ALLOWED_REPORT_PREFIX)
ALLOWED_SUFFIXES = ALLOWED_REPORT_SUFFIXES


def is_allowed(path: str) -> bool:
    """True only for state JSON, report artefacts, and the latest pointer."""
    entry = str(path).strip()
    if not entry or entry.endswith("/"):
        return False
    if entry.startswith("/") or ".." in entry.split("/"):
        return False
    if entry in ALLOWED_EXACT_PATHS:
        return True
    if entry.startswith(ALLOWED_STATE_PREFIX):
        return entry.endswith(ALLOWED_STATE_SUFFIXES)
    if entry.startswith(ALLOWED_REPORT_PREFIX):
        return entry.endswith(ALLOWED_REPORT_SUFFIXES)
    return False


def _unquote(entry: str) -> str:
    """Undo git's C-style quoting used for unusual file names."""
    entry = entry.strip()
    if len(entry) >= 2 and entry.startswith('"') and entry.endswith('"'):
        body = entry[1:-1]
        try:
            return (
                body.encode("utf-8")
                .decode("unicode_escape")
                .encode("latin-1")
                .decode("utf-8")
            )
        except (UnicodeDecodeError, UnicodeEncodeError):
            return body
    return entry


def changed_paths() -> list[str]:
    """Every changed path, with untracked directories expanded to files."""
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=True,
    )
    paths: list[str] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        entry = line[3:]
        if not entry.strip():
            continue
        if " -> " in entry:
            # A rename touches the old and the new location; check both sides.
            before, after = entry.split(" -> ", 1)
            for side in (before, after):
                cleaned = _unquote(side)
                if cleaned:
                    paths.append(cleaned)
            continue
        cleaned = _unquote(entry)
        if cleaned:
            paths.append(cleaned)
    return paths


def main() -> int:
    paths = changed_paths()
    forbidden = [path for path in paths if not is_allowed(path)]
    if forbidden:
        print("자동 커밋이 금지된 경로가 변경되었습니다:")
        for path in sorted(forbidden):
            print(f"  - {path}")
        return 1
    print(f"허용된 상태 파일과 보고서만 변경되었습니다. ({len(paths)}개 파일)")
    for path in sorted(paths):
        print(f"  + {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
