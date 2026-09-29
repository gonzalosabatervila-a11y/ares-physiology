"""Tiempo: todo se guarda en UTC; `local_sleep_date` se deriva siempre en Europe/Madrid
a partir del final del sueño, nunca truncando el UTC (Implementation Plan v0.2 FINAL, §6.1).

Se conserva el offset o zona original de la fuente cuando la trae, en un campo aparte
(`source_tz` en daily_metrics); esta función solo calcula la fecha fisiológica del día.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")


def to_utc(dt: datetime) -> datetime:
    """Normaliza un datetime (con o sin zona) a UTC. Sin zona, se asume que ya es UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def local_sleep_date(sleep_end_utc: datetime, tz: ZoneInfo = MADRID) -> date:
    """La jornada fisiológica a la que pertenece una noche: la fecha local en `tz`
    en el momento en que termina el sueño. Cruzar medianoche o un cambio de hora
    no cambia el resultado, porque se calcula sobre el instante final, no truncando UTC.
    """
    return to_utc(sleep_end_utc).astimezone(tz).date()


def is_dst_transition_night(
    sleep_start_utc: datetime, sleep_end_utc: datetime, tz: ZoneInfo = MADRID
) -> bool:
    """True si el offset de `tz` cambia entre el inicio y el final del sueño
    (p. ej. la noche del 24 al 25 de octubre). Útil para marcar la noche en logs/tests."""
    start = to_utc(sleep_start_utc).astimezone(tz)
    end = to_utc(sleep_end_utc).astimezone(tz)
    return start.utcoffset() != end.utcoffset()
