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
from . import data

STATIC = Path(__file__).parent / "static"
mimetypes.add_type("application/manifest+json", ".webmanifest")  # según el sistema no viene


def create_app(
    get_conn: Callable[[], duckdb.DuckDBPyConnection],
    settings: Settings,
    sync_now: Callable[[], None] | None = None,
) -> FastAPI:
    app = FastAPI(title="ARES", docs_url=None, redoc_url=None, openapi_url=None)

    def cursor() -> duckdb.DuckDBPyConnection:
        return get_conn().cursor()  # un cursor por petición: seguro entre hilos

    @app.get("/api/home")
    def api_home() -> dict:
        return data.home(cursor(), source=settings.wellness_source)

    @app.get("/api/progreso")
    def api_progreso() -> dict:
        return data.progreso(cursor())

    @app.get("/api/senal/{key}")
    def api_senal(key: str, days: int = 28) -> dict:
        if key not in data.SPECS:
            raise HTTPException(status_code=404, detail="señal desconocida")
        if days not in data.PERIODS:
            raise HTTPException(status_code=422, detail=f"days debe ser uno de {data.PERIODS}")
        return data.signal_detail(cursor(), key, days)

    @app.get("/api/lab")
    def api_lab() -> dict:
        return data.lab(cursor(), settings)

    @app.post("/api/sync")
    def api_sync() -> dict:
        if sync_now is None:
            raise HTTPException(status_code=503, detail="sincronización manual no disponible")
        sync_now()
        return {"ok": True}

    @app.middleware("http")
    async def no_cache_static(request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
