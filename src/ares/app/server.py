"""Servidor local de la app ARES (FastAPI). Solo lee; escucha en 127.0.0.1.

En producción vivirá dentro de `ares serve` (único propietario de DuckDB) y se
publicará solo en la tailnet con Tailscale Serve. Aquí, para desarrollo, `ares app`
lo levanta aparte con la base abierta en solo lectura.
"""

from __future__ import annotations

import mimetypes
from collections.abc import Callable
from pathlib import Path

import duckdb
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..config import Settings
from . import data, physiology, training_catalog, planning

STATIC = Path(__file__).parent / "static"
mimetypes.add_type("application/manifest+json", ".webmanifest")  # según el sistema no viene


def create_app(
    get_conn: Callable[[], duckdb.DuckDBPyConnection],
    settings: Settings, *,
    auto_sync: bool = False,
) -> FastAPI:
    app = FastAPI(title="ARES", docs_url=None, redoc_url=None, openapi_url=None)

    def cursor() -> duckdb.DuckDBPyConnection:
        return get_conn().cursor()  # un cursor por petición: seguro entre hilos

    @app.get("/api/home")
    def api_home() -> dict:
        # La tarjeta nativa usa WHOOP directo; las señales heredadas de intervals.icu
        # mantienen su procedencia explícita hasta su migración al motor nocturno.
        result = data.home(
            cursor(),
            device=settings.intervals_wellness_device,
            device_id=settings.device_id,
        )
        weekly = planning.plan(tz=settings.tz, weight_kg=settings.nutrition_weight_kg)
        return {
            **result,
            "sync_mode": "automatic" if auto_sync else "read_only",
            "plan_preview": {
                "available": weekly["available"],
                "week": weekly.get("week"),
                "start": weekly.get("start"),
                "end": weekly.get("end"),
                "today": weekly.get("today"),
                "today_session": next(
                    (s for s in weekly.get("days", []) if s["date"] == weekly["today"]), None
                ),
                "source_version": weekly.get("source_version"),
            },
        }

    @app.get("/api/plan")
    def api_plan(week: str | None = None) -> dict:
        if week is not None and week not in {f"S{i}" for i in range(32, 41)}:
            raise HTTPException(status_code=422, detail="Semana fuera del plan disponible")
        result = planning.plan(week=week, tz=settings.tz,
                               weight_kg=settings.nutrition_weight_kg)
        if not result["available"]:
            return result
        # Registrar una actividad NO valida automáticamente que coincida
        # con el entrenamiento prescrito. Solo exposición comparativa.
        observed = {}
        for item in training_catalog.catalog(
            cursor(), settings.device_id, tz=settings.tz,
            category="running", limit=50,
        )["sessions"]:
            day = item["date"]
            if day not in {s["date"] for s in result["days"]}:
                continue
            b = observed.setdefault(day, {"count": 0, "minutes": 0.0,
                                          "km": 0.0, "source": "Tredict",
                                          "verified_match": False})
            b["count"] += 1
            if item.get("duration_s") is not None and 0 < item["duration_s"] < 86400:
                b["minutes"] += item["duration_s"] / 60
            if item.get("distance_m") is not None and 0 < item["distance_m"] < 200000:
                b["km"] += item["distance_m"] / 1000
        for day, item in observed.items():
            item["minutes"] = round(item["minutes"])
            item["km"] = round(item["km"], 2)
        return {**result, "observed_runs": observed}

    @app.get("/api/progreso")
    def api_progreso() -> dict:
        return data.progreso(cursor())

    @app.get("/api/fisiologia")
    def api_fisiologia(days: int = 90) -> dict:
        if days not in (28, 90, 365):
            raise HTTPException(status_code=422, detail="days debe ser 28, 90 o 365")
        return physiology.report(cursor(), settings.device_id, days=days)

    @app.get("/api/senal/{key}")
    def api_senal(key: str, days: int = 28) -> dict:
        if key not in data.SPECS:
            raise HTTPException(status_code=404, detail="señal desconocida")
        if days not in data.PERIODS:
            raise HTTPException(status_code=422, detail=f"days debe ser uno de {data.PERIODS}")
        return data.signal_detail(cursor(), key, days, device=settings.intervals_wellness_device)

    @app.get("/api/entrenos")
    def api_entrenos(category: str = "running", limit: int = 20) -> dict:
        if category not in ("running", "other") or not 1 <= limit <= 50:
            raise HTTPException(status_code=422, detail="Categoría o límite no admitidos")
        out = training_catalog.catalog(
            cursor(), settings.device_id, tz=settings.tz,
            category=category, limit=limit,
        )
        cur = cursor()
        last = cur.execute(
            """SELECT source, endpoint, max(day) AS latest_day FROM raw_payload
               WHERE (source='whoop' AND endpoint='workout')
                  OR (source='tredict' AND endpoint IN ('activity', 'activity_detail'))
               GROUP BY source, endpoint"""
        ).fetchall()
        return {
            **out,
            "last_record_dates": {
                f"{src}/{endpoint}": date.isoformat() if date else None
                for src, endpoint, date in last
            },
            "sync_mode": "automatic" if auto_sync else "read_only",
        }

    @app.get("/api/entreno/{activity_id}")
    def api_entreno(activity_id: str) -> dict:
        workout = training_catalog.detail(
            cursor(), activity_id, device_id=settings.device_id, tz=settings.tz
        )
        if workout is None:
            raise HTTPException(status_code=404, detail="Entrenamiento no encontrado")
        return workout

    @app.get("/api/lab")
    def api_lab() -> dict:
        return data.lab(cursor(), settings)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
