"""History-locked Tredict HR zones, all fixtures synthetic."""
from ares.app.training_zones import heart_rate_zones


def activity(values=(200, 1000, 600), duration=1800):
    return {
        "summary": {"duration": duration, "zonesDistribution": {
            "heartrate": list(values)
        }},
        "currentZones": {"heartrate": [
            {"name": "Z1", "from": -1, "to": 132},
            {"name": "Z2", "from": 133, "to": 152},
            {"name": "Z3", "from": 153, "to": -1},
        ]},
    }


def test_zone_times_and_percentages_from_historical_thresholds():
    r = heart_rate_zones(activity())
    assert r["available"] is True
    assert [z["seconds"] for z in r["zones"]] == [200, 1000, 600]
    assert r["coverage_pct"] == 100.0
    assert round(sum(z["percent_recorded"] for z in r["zones"])) == 100
    assert (r["zones"][1]["min_hr"], r["zones"][1]["max_hr"]) == (133, 152)


def test_missing_mismatched_or_invalid_distribution_is_not_shown():
    assert not heart_rate_zones({})["available"]
    assert not heart_rate_zones(activity(values=(300, 400)))["available"]
    assert not heart_rate_zones(activity(values=(300, -1, 1501)))["available"]
    assert not heart_rate_zones(activity(values=(1000, 1000, 1000)))["available"]


def test_partial_coverage_reported_not_promoted_to_complete():
    r = heart_rate_zones(activity(values=(60, 120, 180)))
    assert r["available"] is True
    assert r["coverage_pct"] == 20.0
