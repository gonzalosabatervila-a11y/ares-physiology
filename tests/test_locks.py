"""Lockfile portable: excluye a otros hilos y a otros procesos, y se suelta al salir."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

import pytest

from ares.config import REPO_ROOT
from ares.locks import LockTimeout, file_lock


def test_se_toma_y_se_suelta(tmp_path):
    path = tmp_path / "sub" / "x.lock"
    with file_lock(path, timeout_s=1):
        assert path.exists()
    with file_lock(path, timeout_s=1):  # se puede volver a tomar
        pass


def test_otro_hilo_espera_y_si_no_llega_falla(tmp_path):
    path = tmp_path / "x.lock"
    dentro = threading.Event()
    soltar = threading.Event()

    def retener() -> None:
        with file_lock(path, timeout_s=1):
            dentro.set()
            soltar.wait(5)

    t = threading.Thread(target=retener)
    t.start()
    assert dentro.wait(5)
    with pytest.raises(LockTimeout):
        with file_lock(path, timeout_s=0.2):
            pass
    soltar.set()
    t.join()
    with file_lock(path, timeout_s=1):
        pass


def test_otro_proceso_queda_excluido(tmp_path):
    path = tmp_path / "x.lock"
    listo = tmp_path / "listo"
    script = (
        "import sys, time, pathlib\n"
        "from ares.locks import file_lock\n"
        "with file_lock(pathlib.Path(sys.argv[1]), timeout_s=5):\n"
        "    pathlib.Path(sys.argv[2]).touch()\n"
        "    time.sleep(1.5)\n"
    )
    hijo = subprocess.Popen(
        [sys.executable, "-c", script, str(path), str(listo)],
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
    )
    try:
        deadline = time.monotonic() + 10
        while not listo.exists():
            assert time.monotonic() < deadline, "el proceso hijo no llegó a tomar el bloqueo"
            time.sleep(0.02)
        with pytest.raises(LockTimeout):
            with file_lock(path, timeout_s=0.2):
                pass
        with file_lock(path, timeout_s=10):  # cuando el hijo termina, se puede tomar
            pass
    finally:
        hijo.wait(10)
    assert hijo.returncode == 0
