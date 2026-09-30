"""Qué datos reales traen tus cuentas. Solo lectura, no guarda nada y no imprime valores:
solo nombres de campo, recuentos y las constantes de tiempo del modelo de forma y fatiga.

    uv run python scripts/probe_datos.py            # con las llamadas a intervals.icu y Tredict
    uv run python scripts/probe_datos.py --offline  # solo lo que ya está en la base
"""

from __future__ import annotations

import argparse
import json
import textwrap
from collections import Counter
from datetime import date, timedelta

import httpx

from ares import db
from ares.app.modelcheck import estimate_time_constant, flat_keys
from ares.config import get_secret, load_settings


def report(title: str, items: list[dict]) -> None:
    c: Counter[str] = Counter()
    for it in items:
        c.update(flat_keys(it))
    print(f"\n{title}: {len(items)} registros")
    if not items:
        return
    txt = "  ".join(f"{k}:{n}" for k, n in sorted(c.items(), key=lambda x: (-x[1], x[0])))
    print(textwrap.fill(txt, width=100, initial_indent="  ", subsequent_indent="  "))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    s = load_settings()
    conn = db.connect_read_only(s.db_path)
    rows = []
    for day, body in conn.execute(
        """SELECT day, body FROM raw_payload WHERE source='intervals' AND endpoint='wellness'
           QUALIFY row_number() OVER (PARTITION BY day ORDER BY fetched_at DESC) = 1
           ORDER BY day"""
    ).fetchall():
        rec = json.loads(body) if isinstance(body, str) else body
        rows.append({"date": day.isoformat(), **rec})

    print("== Constantes de tiempo de forma y fatiga, estimadas con TUS datos")
    for load_key, value_key, nominal in (("ctlLoad", "ctl", 42), ("atlLoad", "atl", 7)):
        tau, n = estimate_time_constant(rows, load_key, value_key)
        if tau is None:
            print(f"  {value_key}: sin datos suficientes ({n} días utilizables)")
        else:
            print(f"  {value_key}: constante ≈ {tau:.1f} días (n={n}; por defecto: {nominal})")
    if args.offline:
        return

    key, tok = get_secret("intervals_api_key"), get_secret("tredict_token")
    today = date.today()
    if key:
        r = httpx.get(
            f"https://intervals.icu/api/v1/athlete/{s.intervals_athlete_id}/activities",
            params={
                "oldest": (today - timedelta(days=60)).isoformat(),
                "newest": today.isoformat(),
            },
            auth=("API_KEY", key),
            timeout=30,
        )
        print(f"\nintervals.icu · actividades (60 d): HTTP {r.status_code}")
        if r.status_code == 200:
            report("intervals.icu/activities", r.json())
        else:
            print("  ", r.text[:150].replace("\n", " "))
    if tok:
        r = httpx.get(
            "https://www.tredict.com/api/oauth/v2/activityList",
            params={"pageSize": 50, "extendedSummary": 1},
            headers={"Authorization": f"Bearer {tok}"},
            timeout=30,
        )
        print(f"\nTredict · lista con resumen ampliado: HTTP {r.status_code}")
        if r.status_code == 200:
            report(
                "tredict/activityList (extendedSummary=1)",
                r.json().get("_embedded", {}).get("activityList", []),
            )
        else:
            print("  ", r.text[:150].replace("\n", " "))


if __name__ == "__main__":
    main()
