"""Exploratory comparisons of similar-distance runs at similar average HR.

Purely descriptive: not a race prediction, sensor accuracy claim, or causal
estimate of running economy. Different weather, course, fatigue and stop
patterns can dominate the comparison.
"""
from __future__ import annotations

from datetime import date
from typing import Any


def _eligible(s: dict[str, Any]) -> bool:
    if s.get("sport") != "running":
        return False
    d, hr, pace = s.get("distance_m"), s.get("avg_hr"), s.get("pace_s_km")
    return (
        isinstance(d, (int, float)) and 3000 <= d <= 50000
        and isinstance(hr, (int, float)) and 90 <= hr <= 195
        and isinstance(pace, (int, float)) and 170 <= pace <= 750
        and isinstance(s.get("date"), str)
    )


def compare(sessions: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, Any]]:
    """Up to three most-recent non-overlapping comparison pairs."""
    selected = [s for s in sessions if _eligible(s)]
    selected.sort(key=lambda x: x["date"], reverse=True)
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for i, current in enumerate(selected):
        if current["id"] in seen:
            continue
        options = [
            old for old in selected[i + 1:]
            if old["id"] not in seen
            and old["date"] < current["date"]
            and abs(old["distance_m"] / current["distance_m"] - 1) <= .10
            and abs(old["avg_hr"] - current["avg_hr"]) <= 5
        ]
        if not options:
            continue
        # Choose closest distance then similar HR; not "best" performance.
        old = min(options, key=lambda x: (
            abs(x["distance_m"] / current["distance_m"] - 1),
            abs(x["avg_hr"] - current["avg_hr"]),
            -date.fromisoformat(x["date"]).toordinal(),
        ))
        seen.update([current["id"], old["id"]])
        # Positive means faster at similar mean HR; only a descriptive proxy.
        pct = (old["pace_s_km"] / current["pace_s_km"] - 1) * 100
        results.append({
            "new_id": current["id"],
            "old_id": old["id"],
            "new_date": current["date"],
            "old_date": old["date"],
            "new_pace_s_km": current["pace_s_km"],
            "old_pace_s_km": old["pace_s_km"],
            "new_avg_hr": current["avg_hr"],
            "old_avg_hr": old["avg_hr"],
            "new_distance_km": round(current["distance_m"] / 1000, 2),
            "old_distance_km": round(old["distance_m"] / 1000, 2),
            "speed_change_pct": round(pct, 2),
            "kind": "EXP",
            "method": (
                "Dos carreras de 3-50 km, distancia ±10 % y FC media ±5 lpm. "
                "Variación relativa de velocidad media; condiciones no controladas."
            ),
        })
        if len(results) >= limit:
            break
    return results
