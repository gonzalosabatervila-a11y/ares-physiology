"""El servicio: la app vive dentro, las sincronizaciones no se pisan y, si otro proceso tiene
la base, el mensaje dice qué hacer en vez de soltar un traceback de DuckDB."""

from __future__ import annotations

import dataclasses
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
import structlog

from ares import db, serve
from ares.scheduler import AresScheduler


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_la_app_responde_desde_dentro_del_servicio(conn, settings):
    port = free_port()
    cfg = dataclasses.replace(settings, app_bind=f"127.0.0.1:{port}")
    handle = serve.start_app(conn, cfg, structlog.get_logger("t"))
    try:
        assert handle is not None
        r = httpx.get(f"http://127.0.0.1:{port}/api/home", timeout=5)
        assert r.status_code == 200 and r.json()["estado"]["mode"] == "sombra"
        assert httpx.get(f"http://127.0.0.1:{port}/", timeout=5).status_code == 200
    finally:
        serve.stop_app(handle)


def test_si_el_puerto_esta_ocupado_la_app_no_tumba_el_servicio(conn, settings):
    with socket.socket() as ocupado:
        ocupado.bind(("127.0.0.1", 0))
        ocupado.listen(1)
        cfg = dataclasses.replace(settings, app_bind=f"127.0.0.1:{ocupado.getsockname()[1]}")
        assert serve.start_app(conn, cfg, structlog.get_logger("t")) is None


def test_una_pasada_de_serve_deja_la_base_migrada_y_no_llama_a_la_red(tmp_path, monkeypatch):
    monkeypatch.setenv("ARES_DATA_DIR", str(tmp_path))
    assert serve.run(run_once=True) == 0
    c = db.connect(tmp_path / "ares.duckdb")
    assert db.current_version(c) == 5
    c.close()


def test_dos_sincronizaciones_a_la_vez_no_se_pisan(conn, settings, monkeypatch):
    """Dentro del proceso, una sola sincronización a la vez (el token de WHOOP, además, va bajo
    un lockfile entre procesos)."""
    dentro, soltar, corridas = threading.Event(), threading.Event(), []

    def lenta(cur, cfg, logger, job="manual"):
        corridas.append(1)
        dentro.set()
        soltar.wait(5)

    monkeypatch.setattr("ares.scheduler.runner.run_all", lenta)
    sch = AresScheduler(conn, settings, structlog.get_logger("t"))
    t = threading.Thread(target=sch._tick, args=("day",))
    t.start()
    assert dentro.wait(5)
    sch._tick("morning")  # llega con la primera aún en marcha: se omite
    soltar.set()
    t.join(5)
    assert corridas == [1]
    sch._tick("day")  # y cuando ya no hay ninguna en marcha, se ejecuta
    assert corridas == [1, 1]


def test_base_ocupada_por_otro_proceso_da_un_mensaje_claro(tmp_path: Path):
    path = tmp_path / "ares.duckdb"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import duckdb, sys, time\n"
            "c = duckdb.connect(sys.argv[1])\n"  # se guarda: si no, se cierra al instante
            "print('abierta', flush=True)\n"
            "time.sleep(30)",
            str(path),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout.readline().strip() == "abierta"
        with pytest.raises(db.DatabaseBusy, match="nssm stop ARESPhysiology"):
            db.connect(path)
        with pytest.raises(db.DatabaseBusy):
            db.connect_read_only(path)
    finally:
        proc.kill()
        proc.wait()
    time.sleep(0.2)
    db.connect(path).close()  # liberada, vuelve a abrirse


def test_app_bind_se_lee_del_entorno_y_tiene_valor_por_defecto(tmp_path, monkeypatch):
    from ares.config import load_settings

    monkeypatch.setenv("ARES_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("APP_BIND", raising=False)
    assert load_settings(env_file=tmp_path / "no-existe.env").app_bind == "127.0.0.1:8443"
    monkeypatch.setenv("APP_BIND", "127.0.0.1:9911")
    assert load_settings(env_file=tmp_path / "no-existe.env").app_bind == "127.0.0.1:9911"


@pytest.mark.parametrize(
    "mensaje",
    [
        # Linux/macOS
        'IO Error: Could not set lock on file "x.duckdb": '
        "Conflicting lock is held in python (PID 1)",
        # Windows en inglés
        'IO Error: Cannot open file "x.duckdb": The process cannot access the file because it is '
        "being used by another process.\n\nFile is already open in python.exe (PID 7560)",
        # Windows en español (el caso real del HP, 30/09/2026)
        'IO Error: Cannot open file "x.duckdb": El proceso no tiene acceso al archivo porque está '
        "siendo utilizado por otro proceso.\n\nFile is already open in python.exe (PID 7560)",
    ],
)
def test_el_aviso_de_base_ocupada_no_depende_del_idioma_del_sistema(monkeypatch, tmp_path, mensaje):
    import duckdb

    def ocupada(*_a, **_k):
        raise duckdb.IOException(mensaje)

    monkeypatch.setattr("ares.db.duckdb.connect", ocupada)
    with pytest.raises(db.DatabaseBusy, match="nssm stop ARESPhysiology"):
        db.connect(tmp_path / "x.duckdb")
    (tmp_path / "x.duckdb").touch()  # connect_read_only exige que el fichero exista
    with pytest.raises(db.DatabaseBusy):
        db.connect_read_only(tmp_path / "x.duckdb")


def test_otros_errores_de_io_no_se_disfrazan_de_base_ocupada(monkeypatch, tmp_path):
    import duckdb

    def sin_espacio(*_a, **_k):
        raise duckdb.IOException("IO Error: No space left on device")

    monkeypatch.setattr("ares.db.duckdb.connect", sin_espacio)
    with pytest.raises(duckdb.IOException, match="No space left"):
        db.connect(tmp_path / "x.duckdb")
