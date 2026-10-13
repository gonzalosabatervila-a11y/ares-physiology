"""Graba fixtures reales y anonimizadas de WHOOP a partir de la capa bruta. Solo lectura de la
base; escribe FUERA del repositorio (por defecto ~/ares-data/fixtures-private/) y se niega a
escribir dentro de él: las respuestas reales nunca van a Git (fe de erratas v0.3).

    uv run python scripts/record_whoop_fixtures.py [--db RUTA] [--out CARPETA]

Anonimiza los identificadores (user_id a 0; ciclos, sueños y entrenos renumerados de forma
coherente entre colecciones; v1_id fuera) y conserva horas, offsets y valores, que es lo que
los tests de contrato y de tiempo necesitan. Toma la última versión de cada registro.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

import duckdb

from ares.config import REPO_ROOT, load_settings

ENDPOINTS = ("recovery", "sleep", "cycle", "workout")
KEYS = {"recovery": "cycle_id", "sleep": "id", "cycle": "id", "workout": "id"}


class Anonymizer:
    def __init__(self) -> None:
        self.cycles: dict[int, int] = {}
        self.uuids: dict[str, str] = {}

    def cycle(self, real: int) -> int:
        return self.cycles.setdefault(real, 1000 + len(self.cycles))

    def uid(self, real: str) -> str:
        return self.uuids.setdefault(real, str(uuid.UUID(int=len(self.uuids) + 1)))

    def record(self, endpoint: str, rec: dict[str, Any]) -> dict[str, Any]:
        out = dict(rec)
        out["user_id"] = 0
        out.pop("v1_id", None)
        if endpoint == "cycle":
            out["id"] = self.cycle(rec["id"])
        if endpoint in ("sleep", "workout"):
            out["id"] = self.uid(rec["id"])
        if "cycle_id" in rec:
            out["cycle_id"] = self.cycle(rec["cycle_id"])
        if "sleep_id" in rec:
            out["sleep_id"] = self.uid(rec["sleep_id"])
        return out


def latest(conn: duckdb.DuckDBPyConnection, endpoint: str) -> list[dict[str, Any]]:
    best: dict[Any, dict[str, Any]] = {}
    for (body,) in conn.execute(
        f"SELECT body FROM raw_whoop_{endpoint} ORDER BY fetched_at"
    ).fetchall():
        rec = json.loads(body)
        k = rec.get(KEYS[endpoint])
        if k not in best or rec.get("updated_at", "") >= best[k].get("updated_at", ""):
            best[k] = rec
    return sorted(best.values(), key=lambda r: r.get("start") or r.get("created_at") or "")


def main(argv: list[str] | None = None) -> int:
    settings = load_settings()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", type=Path, default=settings.db_path)
    p.add_argument("--out", type=Path, default=settings.data_dir / "fixtures-private")
    args = p.parse_args(argv)

    out = args.out.expanduser().resolve()
    if out == REPO_ROOT or REPO_ROOT in out.parents:
        print(
            f"Me niego a escribir dentro del repositorio ({out}): las fixtures reales no van a Git."
        )
        return 1
    conn = duckdb.connect(str(args.db), read_only=True)
    try:
        anon = Anonymizer()
        # Primero los ciclos y los sueños, para que la numeración siga su orden temporal.
        data = {e: [anon.record(e, r) for r in latest(conn, e)] for e in ("cycle", "sleep")}
        data |= {e: [anon.record(e, r) for r in latest(conn, e)] for e in ("recovery", "workout")}
    finally:
        conn.close()
    out.mkdir(parents=True, exist_ok=True)
    for endpoint in ENDPOINTS:
        (out / f"whoop_{endpoint}.json").write_text(
            json.dumps({"records": data[endpoint]}, ensure_ascii=False, indent=1), "utf-8"
        )
    counts = {e: len(data[e]) for e in ENDPOINTS}
    print(f"Fixtures anonimizadas en {out}: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
