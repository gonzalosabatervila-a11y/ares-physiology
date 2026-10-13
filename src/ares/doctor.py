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
from .connectors import whoop_tokens
from .connectors.intervals import BASE_URL as INTERVALS_URL
from .connectors.tredict import BASE_URL as TREDICT_URL
from .connectors.whoop import BASE_URL as WHOOP_URL


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

    client = http or httpx.Client(timeout=15.0)

    def secret_check(name: str) -> bool:
        try:
            return bool(secret_getter(name))
        except Exception:
            return False

    has_intervals_key = secret_check("intervals_api_key")
    checks.append(
        Check(
            "Secreto intervals_api_key",
            has_intervals_key,
            "presente (valor no mostrado)"
            if has_intervals_key
            else "falta: ares secret set intervals_api_key",
        )
    )
    if offline:
        checks.append(Check("Red · intervals.icu", True, "omitida (--offline)"))
    elif not has_intervals_key:
        checks.append(Check("Red · intervals.icu", False, "sin clave, no se puede probar"))
    else:
        today = date.today().isoformat()
        try:
            r = client.get(
                f"{INTERVALS_URL}/athlete/{settings.intervals_athlete_id}/wellness",
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

    has_tredict_token = secret_check("tredict_token")
    checks.append(
        Check(
            "Secreto tredict_token",
            has_tredict_token,
            "presente (valor no mostrado)"
            if has_tredict_token
            else "falta: ares secret set tredict_token",
        )
    )
    if offline:
        checks.append(Check("Red · Tredict", True, "omitida (--offline)"))
    elif not has_tredict_token:
        checks.append(Check("Red · Tredict", False, "sin token, no se puede probar"))
    else:
        try:
            r = client.get(
                f"{TREDICT_URL}/activityList",
                params={"pageSize": 50},
                headers={
                    "Authorization": f"Bearer {secret_getter('tredict_token') or ''}",
                    "Accept": "application/json;charset=UTF-8",
                },
            )
            checks.append(
                Check(
                    "Red · Tredict",
                    r.status_code == 200,
                    f"HTTP {r.status_code}"
                    + (" (token rechazado)" if r.status_code in (401, 403) else ""),
                )
            )
        except Exception as exc:
            checks.append(Check("Red · Tredict", False, f"sin conexión: {exc}"))

    checks.extend(_whoop_checks(settings, offline, secret_check, secret_getter, client))
    return checks


def _whoop_checks(
    settings: Settings,
    offline: bool,
    secret_check: Callable[[str], bool],
    secret_getter: Callable[[str], str | None],
    client: httpx.Client,
) -> list[Check]:
    """Cliente y autorización de WHOOP (solo presencia, nunca valores) y una llamada mínima.
    La llamada puede renovar el token: lo hace bajo el mismo bloqueo que el servicio."""
    has_client = secret_check("whoop_client_id") and secret_check("whoop_client_secret")
    has_tokens = all(
        secret_check(n) for n in ("whoop_access_token", "whoop_refresh_token", "whoop_token_expiry")
    )
    out = [
        Check(
            "Cliente WHOOP",
            has_client,
            "presente (valores no mostrados)" if has_client else "falta: ares whoop-auth",
        ),
        Check(
            "Autorización WHOOP",
            has_tokens,
            "presente (valores no mostrados)" if has_tokens else "falta: ares whoop-auth",
        ),
    ]
    if offline:
        out.append(Check("Red · WHOOP", True, "omitida (--offline)"))
        return out
    if not (has_client and has_tokens):
        out.append(Check("Red · WHOOP", False, "sin autorización, no se puede probar"))
        return out

    def send(token: str) -> httpx.Response:
        return client.get(
            f"{WHOOP_URL}/v2/cycle",
            params={"limit": "1"},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )

    try:
        r = whoop_tokens.call_with_token(
            send, settings.data_dir, http=client, secret_getter=secret_getter
        )
        detail = f"HTTP {r.status_code}" + (" (permiso denegado)" if r.status_code == 403 else "")
        out.append(Check("Red · WHOOP", r.status_code == 200, detail))
    except whoop_tokens.TokenError as exc:
        out.append(Check("Red · WHOOP", False, str(exc)))
    except Exception as exc:
        out.append(Check("Red · WHOOP", False, f"sin conexión: {exc}"))
    return out


def render(checks: list[Check]) -> str:
    width = max(len(c.name) for c in checks)
    lines = [f"{'OK' if c.ok else 'FALLO':<5}  {c.name.ljust(width)}  {c.detail}" for c in checks]
    total_ok = sum(c.ok for c in checks)
    lines.append(f"\n{total_ok}/{len(checks)} comprobaciones correctas")
    return "\n".join(lines)
