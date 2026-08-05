"""Commit guard against a real temporary Git repository.

These tests create an actual repository so the guard is exercised through real
`git status` output, including the first-run case where whole directories are
untracked and git would otherwise collapse them to a single entry.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import tools.commit_guard as guard

ROOT = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )


def _new_repo(tmp_path: Path) -> Path:
    """A self-contained repo that ignores any global or system git config."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", ".")
    _git(repo, "config", "user.name", "aurio-test")
    _git(repo, "config", "user.email", "aurio-test@users.noreply.test")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "app.py").write_text("print('seed')\n", encoding="utf-8")
    (repo / "safety").mkdir()
    (repo / "safety" / "constitution.py").write_text("POLICY = 1\n", encoding="utf-8")
    _git(repo, "add", "app.py", "safety/constitution.py")
    _git(repo, "commit", "-qm", "init")
    return repo


def _write_allowed_outputs(repo: Path) -> None:
    """Exactly what tools/run_evolution.py produces on a first run."""
    state = repo / "evolution_state"
    state.mkdir()
    for name in (
        "state.json", "population.json", "hall_of_fame.json",
        "lineage.json", "evaluation_seeds.json",
    ):
        (state / name).write_text("{}", encoding="utf-8")
    reports = repo / "reports"
    reports.mkdir()
    (reports / "aurio-report-20260731-20260804-000000.zip").write_bytes(b"PK\x03\x04")
    (reports / "latest.txt").write_text(
        "aurio-report-20260731-20260804-000000.zip", encoding="utf-8"
    )


def _run_guard(repo: Path) -> tuple[int, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    completed = subprocess.run(
        [sys.executable, "-m", "tools.commit_guard"],
        cwd=repo, env=env, capture_output=True, text=True,
    )
    return completed.returncode, completed.stdout


def _paths_in(repo: Path) -> list[str]:
    cwd = Path.cwd()
    try:
        os.chdir(repo)
        return guard.changed_paths()
    finally:
        os.chdir(cwd)


def test_first_run_reports_individual_files_not_directories(tmp_path):
    """Regression: a brand-new tree used to surface as `?? reports/`."""
    repo = _new_repo(tmp_path)
    _write_allowed_outputs(repo)
    paths = _paths_in(repo)
    assert "reports/" not in paths
    assert "evolution_state/" not in paths
    assert "evolution_state/state.json" in paths
    assert "evolution_state/population.json" in paths
    assert "reports/latest.txt" in paths
    assert any(p.endswith(".zip") for p in paths)
    assert all(not p.endswith("/") for p in paths)


def test_first_run_passes_the_guard(tmp_path):
    repo = _new_repo(tmp_path)
    _write_allowed_outputs(repo)
    code, output = _run_guard(repo)
    assert code == 0, output
    assert "허용된 상태 파일과 보고서만" in output
    assert "reports/latest.txt" in output


@pytest.mark.parametrize(
    "relative",
    [
        "reports/evil.txt",
        "reports/evil.py",
        "reports/nested/evil.txt",
        "evolution_state/evil.txt",
        "evolution_state/evil.py",
        "evolution_state/nested/state.json.bak",
    ],
)
def test_forbidden_new_files_are_rejected(tmp_path, relative):
    repo = _new_repo(tmp_path)
    _write_allowed_outputs(repo)
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x", encoding="utf-8")
    code, output = _run_guard(repo)
    assert code == 1
    assert relative in output


@pytest.mark.parametrize(
    "relative", ["app.py", "safety/constitution.py"]
)
def test_modifying_tracked_source_is_rejected(tmp_path, relative):
    repo = _new_repo(tmp_path)
    _write_allowed_outputs(repo)
    (repo / relative).write_text("# tampered\n", encoding="utf-8")
    code, output = _run_guard(repo)
    assert code == 1
    assert relative in output


def test_allowed_and_forbidden_together_still_fails(tmp_path):
    repo = _new_repo(tmp_path)
    _write_allowed_outputs(repo)
    (repo / "reports" / "evil.txt").write_text("x", encoding="utf-8")
    code, output = _run_guard(repo)
    assert code == 1
    assert "reports/evil.txt" in output
    # The allowed members must not be silently approved alongside it.
    assert "허용된 상태 파일과 보고서만" not in output


def test_paths_with_spaces_are_handled(tmp_path):
    repo = _new_repo(tmp_path)
    _write_allowed_outputs(repo)
    (repo / "reports" / "aurio report copy.zip").write_bytes(b"PK\x03\x04")
    paths = _paths_in(repo)
    assert "reports/aurio report copy.zip" in paths
    code, _ = _run_guard(repo)
    assert code == 0

    (repo / "reports" / "bad name.txt").write_text("x", encoding="utf-8")
    paths = _paths_in(repo)
    assert "reports/bad name.txt" in paths
    code, output = _run_guard(repo)
    assert code == 1
    assert "reports/bad name.txt" in output


def test_deleted_tracked_file_is_rejected(tmp_path):
    repo = _new_repo(tmp_path)
    _write_allowed_outputs(repo)
    (repo / "app.py").unlink()
    code, output = _run_guard(repo)
    assert code == 1
    assert "app.py" in output


def test_rename_reports_both_sides(tmp_path):
    repo = _new_repo(tmp_path)
    _git(repo, "mv", "app.py", "renamed_app.py")
    paths = _paths_in(repo)
    assert "app.py" in paths
    assert "renamed_app.py" in paths
    code, output = _run_guard(repo)
    assert code == 1
    assert "renamed_app.py" in output


def test_deleted_allowed_state_file_is_still_allowed(tmp_path):
    repo = _new_repo(tmp_path)
    _write_allowed_outputs(repo)
    _git(repo, "add", "evolution_state", "reports")
    _git(repo, "commit", "-qm", "state")
    (repo / "evolution_state" / "lineage.json").unlink()
    code, output = _run_guard(repo)
    assert code == 0, output


def test_clean_repository_passes(tmp_path):
    repo = _new_repo(tmp_path)
    code, output = _run_guard(repo)
    assert code == 0
    assert "0개 파일" in output


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("evolution_state/state.json", True),
        ("evolution_state/hall_of_fame.json", True),
        ("reports/aurio-report-1-2.zip", True),
        ("reports/summary.md", True),
        ("reports/metrics.csv", True),
        ("reports/report.json", True),
        ("reports/latest.txt", True),
        ("reports/evil.txt", False),
        ("evolution_state/latest.txt", False),
        ("evolution_state/evil.txt", False),
        ("reports/script.py", False),
        ("reports/", False),
        ("evolution_state/", False),
        ("app.py", False),
        ("safety/constitution.py", False),
        ("engine/judge.py", False),
        ("brandkit/templates/email.html", False),
        (".github/workflows/evolve.yml", False),
        ("tests/test_evolution.py", False),
        ("requirements.txt", False),
        ("../escape.json", False),
        ("/etc/passwd", False),
    ],
)
def test_allow_rules(path, expected):
    assert guard.is_allowed(path) is expected


def test_only_latest_txt_is_exempt_among_text_files():
    assert guard.ALLOWED_EXACT_PATHS == ("reports/latest.txt",)
    assert ".txt" not in guard.ALLOWED_REPORT_SUFFIXES
    assert ".txt" not in guard.ALLOWED_STATE_SUFFIXES


def test_workflow_does_not_swallow_git_add_failures():
    workflow = (ROOT / ".github" / "workflows" / "evolve.yml").read_text("utf-8")
    assert "git add evolution_state reports || true" not in workflow
    assert "git add evolution_state reports" in workflow
    assert "set -euo pipefail" in workflow
    assert "test -d evolution_state" in workflow
    assert "test -d reports" in workflow
    # Order: tests, evolution, guard, telegram, commit.
    order = [
        workflow.index("python -m pytest -q"),
        workflow.index("python -m tools.run_evolution"),
        workflow.index("python -m tools.commit_guard"),
        workflow.index("python -m tools.send_latest_report"),
        workflow.index("git add evolution_state reports"),
    ]
    assert order == sorted(order)
