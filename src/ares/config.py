"""Configuración no secreta (.env) y secretos (almacén del sistema vía keyring)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import keyring
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
KEYRING_SERVICE = "ares"
KNOWN_SECRETS = (
    "intervals_api_key",
    "tredict_token",
    "polar_client_id",
    "polar_client_secret",
    "polar_access_token",
    "polar_refresh_token",
    "polar_token_expiry",
    "ingest_token",
)


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    tz: str
    rules_version: str
    filter_version: str
    device_id: str
    intervals_athlete_id: str
    backfill_max_days: int
    migrations_dir: Path
    polar_redirect_uri: str
    app_bind: str = "127.0.0.1:8443"
    wellness_source: str = "loop"  # loop | intervals

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ares.duckdb"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"


def _clean(value: str) -> str:
    """Quita comentarios en línea y espacios de un valor del .env."""
    return value.split("#", 1)[0].strip()


def load_settings(env_file: Path | None = None) -> Settings:
    load_dotenv(env_file or REPO_ROOT / ".env", override=False)
    env = os.environ
    data_dir = Path(_clean(env.get("ARES_DATA_DIR", "~/ares-data"))).expanduser()
    migrations = Path(_clean(env.get("ARES_MIGRATIONS_DIR", str(REPO_ROOT / "migrations"))))
    return Settings(
        data_dir=data_dir,
        tz=_clean(env.get("ARES_TZ", "Europe/Madrid")),
        rules_version=_clean(env.get("ARES_RULES_VERSION", "1.2")),
        filter_version=_clean(env.get("ARES_FILTER_VERSION", "0.3")),
        device_id=_clean(env.get("ARES_DEVICE_ID", "polar-loop-1")),
        intervals_athlete_id=_clean(env.get("INTERVALS_ATHLETE_ID", "0")),
        backfill_max_days=int(_clean(env.get("BACKFILL_MAX_DAYS", "30"))),
        migrations_dir=migrations.expanduser(),
        polar_redirect_uri=_clean(env.get("POLAR_REDIRECT_URI", "http://localhost:8765/callback")),
        app_bind=_clean(env.get("APP_BIND", "127.0.0.1:8443")),
        wellness_source=(
            "intervals"
            if _clean(env.get("WELLNESS_SOURCE", "loop")).lower() == "intervals"
            else "loop"
        ),
    )


class KeyringUnavailable(RuntimeError):
    """No hay Llavero/Credenciales de Windows disponible en este sistema."""


def get_secret(name: str) -> str | None:
    try:
        return keyring.get_password(KEYRING_SERVICE, name)
    except keyring.errors.NoKeyringError as exc:
        raise KeyringUnavailable(
            "No hay un almacén de secretos disponible (Llavero / Credenciales de Windows). "
            "Ejecuta: ares doctor"
        ) from exc


def set_secret(name: str, value: str) -> None:
    if name not in KNOWN_SECRETS:
        raise ValueError(f"Secreto desconocido: {name}. Válidos: {', '.join(KNOWN_SECRETS)}")
    keyring.set_password(KEYRING_SERVICE, name, value)


def keyring_backend_name() -> str:
    backend = keyring.get_keyring()
    return f"{type(backend).__module__}.{type(backend).__name__}"
