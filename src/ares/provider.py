"""Contrato Physiology Provider (Especificación v0.3, «Contrato de la interfaz»).

Cada adaptador entrega noches normalizadas; el motor (metrics/nightly.py) no sabe qué
dispositivo las produjo. Los campos obligatorios del contrato pueden llegar vacíos cuando el
proveedor no los da (noche sin puntuar, calibración...): entonces la noche queda excluida,
nunca se inventa el valor.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

import duckdb
from pydantic import BaseModel, ConfigDict, field_validator

SCORED = "SCORED"


class NormalizedNight(BaseModel):
    model_config = ConfigDict(frozen=True)

    local_sleep_date: date  # sleep_end en ARES_TZ, nunca truncando el UTC
    sleep_start: datetime  # UTC
    sleep_end: datetime  # UTC
    source_tz: str | None  # offset original del proveedor: procedencia y validación
    sleep_min: int | None  # sueño efectivo; siestas excluidas
    rmssd_ms: float | None  # valor nocturno del proveedor (MED)
    rhr: float | None
    resp_rate: float | None = None
    spo2: float | None = None
    skin_temp: float | None = None
    provider_recovery: float | None = None  # segunda opinión, nunca decide
    score_state: str  # SCORED | PENDING_SCORE | UNSCORABLE (el peor de recuperación y sueño)
    calibrating: bool | None
    device_id: str
    adapter_version: str
    # Trazabilidad propia del proveedor (fe de erratas v0.3, columnas aprobadas)
    steps_provider_cycle: int | None = None  # segunda fuente de pasos; nunca se suma
    provider_sleep_id: str | None = None
    provider_cycle_id: int | None = None
    night_check: str = "ok"
    is_nap: bool = False

    @field_validator("sleep_start", "sleep_end")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("los instantes del contrato deben llevar zona (UTC)")
        return v

    @property
    def scored(self) -> bool:
        return self.score_state == SCORED


class PhysiologyProvider(Protocol):
    """Lo único que el motor necesita de un proveedor: sus noches, desde la capa bruta."""

    name: str
    adapter_version: str

    def nights(self, conn: duckdb.DuckDBPyConnection, device_id: str) -> list[NormalizedNight]:
        """Todas las noches del dispositivo reconstruidas desde la capa bruta, como mucho una
        por `local_sleep_date`."""
        ...
