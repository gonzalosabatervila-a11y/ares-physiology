"""`ares serve`: el único proceso propietario de DuckDB (Implementation Plan v0.2
FINAL, §1 y §7). Abre la conexión una vez, aplica migraciones, arranca el planificador
interno y la app local, y se queda vivo hasta recibir una señal de apagado.

La app (Inicio, Progreso, Lab) vive aquí dentro porque DuckDB solo deja abrir la base a un
proceso: con el servicio en marcha, ningún otro comando puede leerla. Escucha en 127.0.0.1;
para verla desde el iPhone o el Mac se publica con Tailscale Serve.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import signal
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType

import duckdb
import structlog
import uvicorn

from . import db, log
from .app.server import create_app
from .config import Settings, load_settings
from .scheduler import AresScheduler


def _install_signal_handlers(stop: list[bool]) -> None:
    def handler(signum: int, frame: FrameType | None) -> None:  # noqa: ARG001
        stop[0] = True

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
    if hasattr(signal, "SIGBREAK"):  # Windows: NSSM envía Ctrl+Break a los servicios de consola
        signal.signal(signal.SIGBREAK, handler)


def start_app(
    conn: duckdb.DuckDBPyConnection, settings: Settings, logger: structlog.stdlib.BoundLogger
) -> tuple[uvicorn.Server, threading.Thread] | None:
    """Levanta la app en un hilo. Si no puede (puerto ocupado), lo registra y devuelve None:
    la sincronización es más importante que la app y no debe caer por esto."""
    host, _, port = settings.app_bind.rpartition(":")
    config = uvicorn.Config(
        create_app(lambda: conn, settings, auto_sync=True), host=host, port=int(port), log_level="warning"
    )
    server = uvicorn.Server(config)

    def _run() -> None:
        try:
            server.run()
        except SystemExit:  # uvicorn sale así cuando no puede abrir el puerto
            pass

    thread = threading.Thread(target=_run, name="ares-app", daemon=True)
    thread.start()
    for _ in range(100):  # hasta 5 s para arrancar
        if server.started:
            logger.info("app_started", bind=settings.app_bind)
            return server, thread
        if not thread.is_alive():
            break
        time.sleep(0.05)
    logger.error("app_failed", bind=settings.app_bind, hint="¿puerto ocupado?")
    server.should_exit = True
    return None


def stop_app(handle: tuple[uvicorn.Server, threading.Thread] | None) -> None:
    if handle is None:
        return
    server, thread = handle
    server.should_exit = True
    thread.join(timeout=5)


def backup_before_migration(settings: Settings) -> Path | None:
    """Copia verificable antes de cualquier migración de una base existente.

    El proceso debe estar parado. Abrimos y cerramos conexión de solo lectura
    para verificar los SQL aplicados, luego copiamos el fichero cerrado,
    calculamos SHA256 y realizamos rename atómico. No respaldar cada arranque:
    solo cuando hay migraciones realmente pendientes.
    """
    original = settings.db_path
    if not original.is_file():
        return None  # base totalmente nueva
    ro = db.connect_read_only(original)  # falla si otro ARES tiene el lock
    try:
        pending = db.verify(ro, db.discover(settings.migrations_dir))
    finally:
        ro.close()
    if not pending:
        return None

    backup_dir = settings.data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    suffix = max(x.version for x in pending)
    dest = backup_dir / f"ares-pre-v{suffix}-{stamp}.duckdb"
    source_hash, target_hash = hashlib.sha256(), hashlib.sha256()
    fd, tmp_name = tempfile.mkstemp(
        prefix=".ares-pre-migration-", suffix=".tmp", dir=backup_dir
    )
    tmp = Path(tmp_name)
    try:
        with original.open("rb") as src, os.fdopen(fd, "wb") as out:
            while block := src.read(1024 * 1024):
                source_hash.update(block)
                out.write(block)
            out.flush()
            os.fsync(out.fileno())
        with tmp.open("rb") as check:
            while block := check.read(1024 * 1024):
                target_hash.update(block)
        if source_hash.digest() != target_hash.digest():
            raise RuntimeError("Checksum de backup distinto: se cancela la migración")
        os.replace(tmp, dest)
        shutil.copystat(original, dest)
        return dest
    finally:
        tmp.unlink(missing_ok=True)


def run(run_once: bool = False) -> int:
    settings = load_settings()
    logger = log.setup(settings.log_dir)
    logger.info("serve_starting", data_dir=str(settings.data_dir))

    backup = backup_before_migration(settings)
    if backup is not None:
        logger.info("pre_migration_backup_verified", path=str(backup))
    conn = db.connect(settings.db_path)
    try:
        applied = db.migrate(conn, settings.migrations_dir)
        if applied:
            logger.info("migrations_applied", versions=applied)

        scheduler = AresScheduler(conn, settings, logger)
        scheduler.run_now()  # primera pasada al arrancar, sin esperar al próximo tramo
        if run_once:
            return 0

        app = start_app(conn, settings, logger)
        scheduler.start()
        stop = [False]
        _install_signal_handlers(stop)
        logger.info(
            "serve_ready",
            next_runs={
                k: (v.isoformat() if v else None) for k, v in scheduler.next_run_times.items()
            },
        )
        try:
            while not stop[0]:
                time.sleep(1.0)
        finally:
            scheduler.shutdown()
            stop_app(app)
    finally:
        conn.close()
        logger.info("serve_stopped")
    return 0
