from __future__ import annotations

from .evaluate_quality import SCENARIOS, build_report


def test_quality_report_has_no_must_preserve_regressions():
    report = build_report()
    assert report["scenario_count"] == len(SCENARIOS)
    assert report["runs_real_pipeline"] is True
    assert report["all_must_preserve_fields_pass"] is True, [row for row in report["scenarios"] if not row["passed"]]
    assert {row["scenario"] for row in report["scenarios"]} == set(SCENARIOS)


def test_every_scenario_briefing_stays_small():
    """A briefing that grows without bound defeats the point of a handoff."""
    for row in build_report()["scenarios"]:
        assert row["briefing_tokens"] <= 2_500, row["scenario"]
