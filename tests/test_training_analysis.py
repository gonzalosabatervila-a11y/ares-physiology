"""Regressions for conservative ARES Training Intelligence; synthetic sensor data."""
from __future__ import annotations

from ares.app.training_analysis import (
    decoupling_proxy, lap_consistency, series_quality
)


def steady(*, tick=10, duration=3600, gap=0.10):
    points = int(duration / tick)
    mid = (600 + (duration - 300)) / 2
    return {
        "heartrate": [130 if i*tick < mid else round(130*(1+gap), 2)
                      for i in range(points)],
        "speed": [3.0 for _ in range(points)],
        "cadence": [176 for _ in range(points)],
    }


def test_steady_run_descriptive_hr_speed_drift():
    s = steady()
    report = decoupling_proxy(s, 10, 3600)
    assert report["available"] is True
    assert 9.9 <= report["value_pct"] <= 10.1
    assert report["quality"]["paired_coverage_pct"] == 100
    assert report["first"]["hr"] == 130
    assert report["second"]["hr"] == 143


def test_intervals_speed_variability_blocks_decoupling():
    s = steady()
    s["speed"] = [2.5 if i % 2 else 4.2 for i in range(len(s["speed"]))]
    r = decoupling_proxy(s, 10, 3600)
    assert r["available"] is False
    assert "Variación de velocidad" in r["reason"]


def test_different_mean_speeds_blocks_decoupling():
    s = steady()
    for i in range(len(s["speed"])):
        s["speed"][i] = 3.0 if i < 195 else 3.4
    r = decoupling_proxy(s, 10, 3600)
    assert r["available"] is False
    assert "no comparable" in r["reason"]


def test_missing_samples_and_short_duration_cannot_become_a_result():
    s = steady()
    s["heartrate"] = [None if i % 2 == 0 else 138 for i in range(360)]
    r = decoupling_proxy(s, 10, 3600)
    assert r["available"] is False
    assert r["quality"]["paired_coverage_pct"] == 50
    assert decoupling_proxy(steady(duration=900), 10, 900)["available"] is False


def test_quality_never_interprets_null_as_zero():
    s = {"heartrate": [None, 140, 142, None],
         "speed": [3.1, None, 3.2, None]}
    result = series_quality(s, 15, 60)
    assert result["expected_samples"] == 4
    assert result["hr_coverage_pct"] == 50
    assert result["paired_coverage_pct"] == 25
    assert result["usable_for_drift"] is False


def test_lap_variability_only_comparable_distances():
    laps = [
        {"distance_m": 1000, "duration_s": 270},
        {"distance_m": 1005, "duration_s": 275},
        {"distance_m": 995, "duration_s": 283},
        {"distance_m": 1000, "duration_s": 272},
        {"distance_m": 2100, "duration_s": 700},
    ]
    result = lap_consistency(laps)
    assert result["available"] is True
    assert result["count"] == 4
    assert 1 <= result["pace_cv_pct"] <= 3
    assert 270 < result["mean_pace_s_km"] < 285


def test_lap_variability_not_inferred_from_mixed_distances_or_other_sport():
    laps = [
        {"distance_m": 1000, "duration_s": 300},
        {"distance_m": 2000, "duration_s": 540},
        {"distance_m": 500, "duration_s": 140},
    ]
    assert lap_consistency(laps)["available"] is False
    assert lap_consistency(laps, sport="cycling")["available"] is False
    assert decoupling_proxy(steady(), 10, 3600, sport="cycling")["available"] is False
