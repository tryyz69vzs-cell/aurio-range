"""Aggregate 120-seed behavior distribution and full result reproducibility."""

from __future__ import annotations

from collections import defaultdict

from engine.match import run_match


def test_profile_distributions_over_120_fixed_seeds():
    totals = {
        profile: defaultdict(int)
        for profile in ("cautious", "average", "careless")
    }
    for seed in range(1000, 1120):
        result = run_match(
            "mixed",
            "permissive",
            ["cautious", "average", "careless"],
            seed,
        )
        for row in result["profile_metrics"]:
            profile_total = totals[row["profile"]]
            for key in (
                "click_count",
                "submit_count",
                "report_count",
                "verify_count",
                "message_count",
                "warning_escape_count",
                "warned_count",
            ):
                profile_total[key] += row[key]

    def rate(profile, numerator, denominator="message_count"):
        base = totals[profile][denominator]
        return totals[profile][numerator] / base if base else 0.0

    click = {p: rate(p, "click_count") for p in totals}
    submit = {p: rate(p, "submit_count", "click_count") for p in totals}
    report = {p: rate(p, "report_count") for p in totals}
    verify = {p: rate(p, "verify_count") for p in totals}
    escape = {
        p: rate(p, "warning_escape_count", "warned_count") for p in totals
    }

    assert click["careless"] - click["average"] >= 0.10
    assert click["average"] - click["cautious"] >= 0.10
    assert submit["careless"] - submit["average"] >= 0.10
    assert submit["average"] - submit["cautious"] >= 0.10
    assert report["cautious"] == max(report.values())
    assert verify["cautious"] == max(verify.values())
    assert escape["careless"] - escape["cautious"] >= 0.10


def test_same_seed_is_fully_reproducible():
    first = run_match(
        "mixed", "permissive", ["cautious", "average", "careless"], 1088
    )
    second = run_match(
        "mixed", "permissive", ["cautious", "average", "careless"], 1088
    )
    assert first == second
