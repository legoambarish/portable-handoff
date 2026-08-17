from __future__ import annotations

from .evaluate_quality import SCENARIOS, build_report


def test_ten_scenario_quality_report_has_no_must_preserve_regressions():
    report = build_report()
    assert report["scenario_count"] == 10
    assert report["all_must_preserve_fields_pass"] is True
    assert {row["scenario"] for row in report["scenarios"]} == set(SCENARIOS)
