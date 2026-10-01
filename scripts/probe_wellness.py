"""Qué campos de bienestar trae intervals.icu y con qué rangos. Solo lectura: no escribe nada y
solo imprime nombres de campo, recuentos y mínimos/máximos, nunca una fecha con su valor.

    uv run python scripts/probe_wellness.py [--days 30]
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from typing import Any

import httpx

from ares.config import get_secret, load_settings


def summarize(rows: list[dict[str, Any]]) -> list[tuple[str, int, float | None, float | None]]:
    """(campo, días con valor, mínimo, máximo) por campo, de más a menos presente."""
    present: dict[str, int] = {}
    numeric: dict[str, list[float]] = {}
    for row in rows:
        for key, value in row.items():
            if key == "id" or value in (None, "", [], {}):
                continue
            present[key] = present.get(key, 0) + 1
            if isinstance(value, int | float) and not isinstance(value, bool):
                numeric.setdefault(key, []).append(float(value))
    out = []
    for key, n in present.items():
        vals = numeric.get(key)
        out.append((key, n, min(vals) if vals else None, max(vals) if vals else None))
    return sorted(out, key=lambda t: (-t[1], t[0]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()
    settings = load_settings()
    key = get_secret("intervals_api_key")
    if not key:
        print("Falta la clave de intervals.icu en este equipo (ares secret set intervals_api_key).")
        return 1
    today = date.today()
    r = httpx.get(
        f"https://intervals.icu/api/v1/athlete/{settings.intervals_athlete_id}/wellness",
        params={
            "oldest": (today - timedelta(days=args.days)).isoformat(),
            "newest": today.isoformat(),
        },
        auth=("API_KEY", key),
        timeout=30,
    )
    if r.status_code != 200:
        print(f"intervals.icu respondió HTTP {r.status_code}: {r.text[:120]}")
        return 1
    rows = r.json()
    print(f"Bienestar de los últimos {args.days} días: {len(rows)} registros\n")
    for name, n, lo, hi in summarize(rows):
        rango = f"min {lo:g} · max {hi:g}" if lo is not None else "texto/otro"
        print(f"  {name:<26} {n:>3} días   {rango}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
