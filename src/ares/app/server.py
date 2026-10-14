"""Servidor local de ARES. Lecturas; ARES LAB escribe solo en ares serve.

En producción vivirá dentro de `ares serve` (único propietario de DuckDB) y se
publicará solo en la tailnet con Tailscale Serve. Aquí, para desarrollo, `ares app`
lo levanta aparte con la base abierta en solo lectura.
"""

from __future__ import annotations

import mimetypes
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

import duckdb
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..config import Settings
from . import data, physiology, training_catalog, planning, plan_execution, lab_events

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

    def current_plan(week: str | None = None) -> dict:
        options = dict(
            week=week, tz=settings.tz, weight_kg=settings.nutrition_weight_kg,
        )
        override = settings.data_dir / "training_plan.json"
        try:
            return planning.plan(**options, source_file=override)
        except (ValueError, OSError):
            # Una copia local dañada no debe inutilizar WHOOP, Tredict
            # ni la pantalla de inicio: volvemos a la versión incluida.
            if not override.is_file():
                raise
            fallback = planning.plan(**options)
            fallback["snapshot_warning"] = (
                "El plan local actualizado no es válido. Se muestra la copia "
                "de referencia incluida en ARES; revisa el Excel importado."
            )
            return fallback

    @app.get("/api/home")
    def api_home() -> dict:
        # La tarjeta nativa usa WHOOP directo; las señales heredadas de intervals.icu
        # mantienen su procedencia explícita hasta su migración al motor nocturno.
        result = data.home(
            cursor(),
            device=settings.intervals_wellness_device,
            device_id=settings.device_id,
        )
        weekly = current_plan()
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
        result = current_plan(week)
        if not result["available"]:
            return result
        compared = plan_execution.execution(
            cursor(), result["days"], device_id=settings.device_id,
            tz=settings.tz, today=planning.date.fromisoformat(result["today"]),
        )
        # Contrato histórico conservado para los clientes que usaban observed_runs.
        # La información detallada, calidad y contexto WHOOP van en 'execution'.
        observed = {
            day: {
                "count": item["count"], "minutes": item["observed_minutes"],
                "km": item["observed_km"], "source": "Tredict",
                "verified_match": False,
            }
            for day, item in compared["days"].items() if item["count"] > 0
        }
        cur = cursor()
        last_tredict = cur.execute(
            """SELECT max(last_ok) FROM source_status
               WHERE source='tredict' AND endpoint='activity'"""
        ).fetchone()
        checked_at = last_tredict[0].isoformat() if last_tredict and last_tredict[0] else None
        return {
            **result, "observed_runs": observed, "execution": compared,
            "tredict_last_sync": checked_at,
        }

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

    def lab_write_guard(request: Request) -> None:
        """Writes only in single-owner server, via same-origin from localhost/tailnet.

        A web page on a foreign origin cannot silently POST to local ARES.
        ARES must not be exposed on a public URL; tailnet access control
        provides device/user authentication in remote mode.
        """
        if not auto_sync:
            raise HTTPException(403, "ARES app está en modo lectura; usa ares serve")
        # Comparar también PUERTO: distinto puerto en el mismo hostname
        # sigue siendo otro origen web. La URL de Tailscale HTTPS es aparte.
        forwarded = urlsplit("//" + request.headers.get("host", ""))
        host_header = (forwarded.hostname or "").lower()
        if host_header not in {"localhost", "127.0.0.1"} and not host_header.endswith(".ts.net"):
            raise HTTPException(403, "Host no permitido para guardar datos privados")
        origin = request.headers.get("origin")
        if not origin:
            raise HTTPException(403, "Origin obligatorio")
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"}:
            raise HTTPException(403, "Origin no coincide con la aplicación ARES")
        direct = parsed.hostname == host_header
        if direct:
            origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
            host_port = forwarded.port or (443 if parsed.scheme == "https" else 80)
            if origin_port != host_port:
                raise HTTPException(403, "Puerto del Origin distinto del servidor ARES")
        # Algunos reverse proxies locales reescriben Host a 127.0.0.1.
        # Solo admitir esto en HTTPS tailnet y con proxy en loopback.
        client_ip = request.client.host if request.client else None
        tailnet_proxy = (
            parsed.scheme == "https"
            and (parsed.hostname or "").endswith(".ts.net")
            and host_header in {"localhost", "127.0.0.1"}
            and client_ip in {"127.0.0.1", "::1"}
        )
        if not direct and not tailnet_proxy:
            raise HTTPException(403, "Origin no coincide con la aplicación ARES")
        if parsed.scheme == "http" and host_header not in {"localhost", "127.0.0.1"}:
            raise HTTPException(403, "ARES remoto exige HTTPS de Tailscale Serve")
        if request.headers.get("x-ares-lab") != "1":
            raise HTTPException(403, "Cabecera de protección ARES LAB ausente")

    @app.get("/api/lab/events")
    def api_lab_events() -> dict:
        result = lab_events.overview(cursor(), settings.device_id, settings.tz)
        return {**result, "write_enabled": auto_sync}

    @app.post("/api/lab/events", status_code=201)
    def api_lab_create(request: Request, payload: lab_events.NewEvent) -> dict:
        lab_write_guard(request)
        try:
            return lab_events.create(cursor(), settings.device_id, settings.tz, payload)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.patch("/api/lab/events/{event_id}")
    def api_lab_edit(
        event_id: str, request: Request, payload: lab_events.EditEvent,
    ) -> dict:
        lab_write_guard(request)
        try:
            return lab_events.edit(cursor(), settings.device_id, settings.tz, event_id, payload)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.delete("/api/lab/events/{event_id}")
    def api_lab_delete(event_id: str, request: Request) -> dict:
        lab_write_guard(request)
        try:
            return lab_events.remove(cursor(), settings.device_id, settings.tz, event_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/lab")
    def api_lab() -> dict:
        return data.lab(cursor(), settings)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
