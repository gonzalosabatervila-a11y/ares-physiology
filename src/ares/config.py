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
    "whoop_client_id",
    "whoop_client_secret",
    "whoop_access_token",
    "whoop_refresh_token",
    "whoop_token_expiry",
    "ingest_token",
)
PHYSIOLOGY_PROVIDERS = ("whoop",)  # adaptadores disponibles (contrato Physiology Provider)


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    tz: str
    rules_version: str
    device_id: str
    intervals_athlete_id: str
    backfill_max_days: int
    migrations_dir: Path
    app_bind: str = "127.0.0.1:8443"
    physiology_provider: str = "whoop"  # proveedor activo (adaptador), no la unidad
    intervals_wellness_device: str = "COROS"  # etiqueta declarada; no validada por API
    algo_version: str = "whoop-1"
    whoop_redirect_uri: str = "http://localhost:8765/callback"
    whoop_history_days: int = 90  # carga histórica inicial: mínimo objetivo
    nutrition_weight_kg: float | None = None  # opcional, solo .env local; sin peso personal en Git

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ares.duckdb"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"


def _clean(value: str) -> str:
    """Quita comentarios en línea y espacios de un valor del .env."""
    return value.split("#", 1)[0].strip()


def _provider(raw: str | None) -> str:
    name = _clean(raw or "whoop").lower()
    if name not in PHYSIOLOGY_PROVIDERS:
        raise ValueError(
            f"PHYSIOLOGY_PROVIDER={name!r} no existe. Válidos: {', '.join(PHYSIOLOGY_PROVIDERS)}"
        )
    return name


def _positive_int(raw: str, name: str) -> int:
    value = int(_clean(raw))
    if value <= 0:
        raise ValueError(f"{name} debe ser un entero positivo, no {value}")
    return value


def _optional_nutrition_weight(raw: str | None) -> float | None:
    if raw is None or not _clean(raw):
        return None
    value = float(_clean(raw))
    if not 35.0 <= value <= 250.0:
        raise ValueError("ARES_NUTRITION_WEIGHT_KG debe estar entre 35 y 250")
    return value


def load_settings(env_file: Path | None = None) -> Settings:
    load_dotenv(env_file or REPO_ROOT / ".env", override=False)
    env = os.environ
    data_dir = Path(_clean(env.get("ARES_DATA_DIR", "~/ares-data"))).expanduser()
    migrations = Path(_clean(env.get("ARES_MIGRATIONS_DIR", str(REPO_ROOT / "migrations"))))
    return Settings(
        data_dir=data_dir,
        tz=_clean(env.get("ARES_TZ", "Europe/Madrid")),
        rules_version=_clean(env.get("ARES_RULES_VERSION", "1.2")),
        device_id=_clean(env.get("ARES_DEVICE_ID", "pulsera-principal")),
        intervals_athlete_id=_clean(env.get("INTERVALS_ATHLETE_ID", "0")),
        backfill_max_days=int(_clean(env.get("BACKFILL_MAX_DAYS", "30"))),
        migrations_dir=migrations.expanduser(),
        app_bind=_clean(env.get("APP_BIND", "127.0.0.1:8443")),
        physiology_provider=_provider(env.get("PHYSIOLOGY_PROVIDER")),
        intervals_wellness_device=_clean(env.get("INTERVALS_WELLNESS_DEVICE", "COROS")),
        algo_version=_clean(env.get("ARES_ALGO_VERSION", "whoop-1")),
        whoop_redirect_uri=_clean(env.get("WHOOP_REDIRECT_URI", "http://localhost:8765/callback")),
        whoop_history_days=_positive_int(env.get("WHOOP_HISTORY_DAYS", "90"), "WHOOP_HISTORY_DAYS"),
        nutrition_weight_kg=_optional_nutrition_weight(env.get("ARES_NUTRITION_WEIGHT_KG")),
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
