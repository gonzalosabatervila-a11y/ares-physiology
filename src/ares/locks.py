"""Lockfile portable entre hilos y procesos (fcntl en Mac/Linux, msvcrt en Windows).

Lo usa la renovación del token de WHOOP: el refresh token es de un solo uso y una segunda
renovación simultánea, venga de `ares serve` o de un comando del CLI, invalidaría el par.
El fichero de bloqueo no se borra al terminar: lo que se bloquea es el descriptor abierto,
no la existencia del fichero, y borrarlo abriría una carrera entre procesos.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

if sys.platform == "win32":
    import msvcrt

    def _try_lock(fh: IO[bytes]) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(fh: IO[bytes]) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(fh: IO[bytes]) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fh: IO[bytes]) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


class LockTimeout(RuntimeError):
    """Otro hilo o proceso tiene el bloqueo y no lo ha soltado a tiempo."""


@contextmanager
def file_lock(path: Path, timeout_s: float = 60.0, poll_s: float = 0.05) -> Iterator[None]:
    """Bloqueo exclusivo sobre `path`. Espera como mucho `timeout_s` y si no, LockTimeout."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as fh:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                _try_lock(fh)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise LockTimeout(
                        f"No se pudo tomar {path.name} en {timeout_s:.0f} s: "
                        "otro proceso de ARES lo tiene (¿una renovación o ares whoop-auth?)"
                    ) from None
                time.sleep(poll_s)
        try:
            yield
        finally:
            _unlock(fh)
