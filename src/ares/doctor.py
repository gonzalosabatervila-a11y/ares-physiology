"""ares doctor: comprobaciones de entorno, base de datos, secretos, configuración y red."""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

import httpx

from . import db
from .config import Settings, get_secret, keyring_backend_name
from .connectors.intervals import BASE_URL


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def run(
    settings: Settings,
    *,
    offline: bool = False,
    secret_getter: Callable[[str], str | None] = get_secret,
    http: httpx.Client | None = None,
) -> list[Check]:
    checks: list[Check] = []

    v = sys.version_info
    checks.append(Check("Python", v >= (3, 12), f"{v.major}.{v.minor}.{v.micro}"))

    try:
        ZoneInfo(settings.tz)
        checks.append(Check("Zona horaria", True, settings.tz))
    except Exception:
        checks.append(Check("Zona horaria", False, f"no válida: {settings.tz}"))

    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=settings.data_dir):
            pass
        checks.append(Check("Carpeta de datos", True, str(settings.data_dir)))
    except Exception as exc:
        checks.append(Check("Carpeta de datos", False, f"{settings.data_dir}: {exc}"))

    try:
        expected = db.discover(settings.migrations_dir)
        conn = db.connect(settings.db_path)
        try:
            pending = db.verify(conn, expected)
            ver = db.current_version(conn)
        finally:
            conn.close()
        if pending:
            checks.append(
                Check(
                    "Base de datos",
                    False,
                    f"versión {ver}; pendientes {[m.version for m in pending]} "
                    "(ejecuta: ares init-db)",
                )
            )
        else:
            checks.append(
                Check(
                    "Base de datos", True, f"{settings.db_path} · schema_version {ver} verificada"
                )
            )
    except Exception as exc:
        checks.append(Check("Base de datos", False, str(exc)))

    backend = keyring_backend_name()
    usable = "fail" not in backend.lower() and "null" not in backend.lower()
    checks.append(Check("Almacén de secretos", usable, backend))

    try:
        has_key = bool(secret_getter("intervals_api_key"))
    except Exception as exc:
        has_key = False
        backend = f"error: {exc}"
    checks.append(
        Check(
            "Secreto intervals_api_key",
            has_key,
            "presente (valor no mostrado)"
            if has_key
            else "falta: ares secret set intervals_api_key",
        )
    )

    if offline:
        checks.append(Check("Red · intervals.icu", True, "omitida (--offline)"))
    elif not has_key:
        checks.append(Check("Red · intervals.icu", False, "sin clave, no se puede probar"))
    else:
        client = http or httpx.Client(timeout=15.0)
        today = date.today().isoformat()
        try:
            r = client.get(
                f"{BASE_URL}/athlete/{settings.intervals_athlete_id}/wellness",
                params={"oldest": today, "newest": today},
                auth=("API_KEY", secret_getter("intervals_api_key") or ""),
            )
            checks.append(
                Check(
                    "Red · intervals.icu",
                    r.status_code == 200,
                    f"HTTP {r.status_code}"
                    + (" (clave rechazada)" if r.status_code in (401, 403) else ""),
                )
            )
        except Exception as exc:
            checks.append(Check("Red · intervals.icu", False, f"sin conexión: {exc}"))
    return checks


def render(checks: list[Check]) -> str:
    width = max(len(c.name) for c in checks)
    lines = [f"{'OK' if c.ok else 'FALLO':<5}  {c.name.ljust(width)}  {c.detail}" for c in checks]
    total_ok = sum(c.ok for c in checks)
    lines.append(f"\n{total_ok}/{len(checks)} comprobaciones correctas")
    return "\n".join(lines)
