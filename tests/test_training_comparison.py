"""Tests de comparaciones exploratorias de entrenamiento. Solo datos sintéticos."""
from ares.app.training_comparison import compare


def run(id, date, *, distance=10000, heart_rate=145, pace=300, sport="running"):
    return {
        "id": id, "date": date, "distance_m": distance,
        "avg_hr": heart_rate, "pace_s_km": pace, "sport": sport,
    }


def test_similar_distance_and_heartrate_uses_speed_change():
    previous = run("old", "2026-09-05", distance=10100, heart_rate=145, pace=305)
    recent = run("new", "2026-10-13", distance=10000, heart_rate=148, pace=290)
    result = compare([previous, recent])
    assert len(result) == 1
    assert result[0]["new_id"] == "new" and result[0]["old_id"] == "old"
    assert abs(result[0]["speed_change_pct"] - 5.17) < .02
    assert result[0]["kind"] == "EXP"


def test_non_comparable_distances_or_pulse_not_matched():
    old = run("old", "2026-09-05")
    far = run("far", "2026-10-13", distance=12000)
    high_hr = run("hard", "2026-10-12", heart_rate=160)
    assert compare([old, far, high_hr]) == []


def test_cross_sport_and_missing_inputs_are_never_compared():
    old = run("old", "2026-09-05")
    strength = run("strength", "2026-10-13", sport="misc")
    no_hr = run("missing", "2026-10-11", heart_rate=None)
    assert compare([old, strength, no_hr]) == []


def test_same_date_is_not_independent_benchmark():
    assert compare([
        run("run-a", "2026-10-13"),
        run("run-b", "2026-10-13"),
    ]) == []


def test_comparison_limit_non_overlapping_pairs():
    sessions = [
        run("d", "2026-10-13"), run("c", "2026-10-12"),
        run("b", "2026-10-11"), run("a", "2026-10-10"),
    ]
    out = compare(sessions, limit=2)
    assert len(out) == 2
    ids = [i for pair in out for i in (pair["new_id"], pair["old_id"])]
    assert len(set(ids)) == 4
