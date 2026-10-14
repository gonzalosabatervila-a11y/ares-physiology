"""ARES LAB · eventos humanos inmutables en su fuente, editables con auditoría.

Solo las operaciones explícitas del usuario escriben. Nunca toca raw_payload ni
recalcula WHOOP. El análisis sobre intervalos de cena y sueño es descriptivo,
no causal. Sin servicio de IA, sin telemetría, sin terceros.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import duckdb
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EVENT_TYPES = {"coffee", "dinner_end", "bedtime"}
MAX_NOTE = 280


class NewEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: str
    occurred_at: datetime
    caffeine_mg: float | None = Field(default=None, ge=0, le=500, allow_inf_nan=False)
    amount_basis: str | None = None
    note: str | None = Field(default=None, max_length=MAX_NOTE)
    client_event_key: UUID

    @field_validator("event_type")
    @classmethod
    def known_type(cls, value: str) -> str:
        if value not in EVENT_TYPES:
            raise ValueError("Tipo de acontecimiento no admitido")
        return value

    @field_validator("occurred_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("La fecha debe incluir zona u offset UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def consistent(self) -> "NewEvent":
        if self.event_type == "coffee":
            if self.caffeine_mg is None or self.amount_basis not in {"estimated", "label", "measured"}:
                raise ValueError("Café necesita miligramos y procedencia de la estimación")
        elif self.caffeine_mg is not None or self.amount_basis is not None:
            raise ValueError("Los eventos de cena y cama no contienen cafeína")
        return self


class EditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    occurred_at: datetime | None = None
    caffeine_mg: float | None = Field(default=None, ge=0, le=500, allow_inf_nan=False)
    amount_basis: str | None = None
    note: str | None = Field(default=None, max_length=MAX_NOTE)

    @field_validator("occurred_at")
    @classmethod
    def aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Hora sin zona horaria")
        return value.astimezone(UTC)


def _check_time(instant: datetime) -> None:
    current = datetime.now(UTC)
    if instant > current + timedelta(hours=24) or instant < current - timedelta(days=365*20):
        raise ValueError("Fecha fuera de un intervalo aceptado por ARES")


def _row(item: tuple[Any, ...], tz: str) -> dict[str, Any]:
    keys = ("id", "event_type", "occurred_at", "caffeine_mg",
            "amount_basis", "note", "created_at", "updated_at")
    d = dict(zip(keys, item))
    local = d["occurred_at"].astimezone(ZoneInfo(tz))
    for key in ("occurred_at", "created_at", "updated_at"):
        d[key] = d[key].isoformat()
    d["local_date"] = local.date().isoformat()
    d["local_time"] = local.strftime("%H:%M")
    d["source"] = "MANUAL · ARES LAB"
    return d


COLUMNS = ("event_id, event_type, occurred_at, caffeine_mg, amount_basis, "
           "note, created_at, updated_at")

def _audit(conn: duckdb.DuckDBPyConnection, event_id: str, action: str,
           previous: dict | None, current: dict | None) -> None:
    conn.execute(
        """INSERT INTO lab_event_revisions
           (revision_id, event_id, action, previous_snapshot, current_snapshot)
           VALUES (?, ?, ?, ?, ?)""",
        [str(uuid4()), event_id, action,
         json.dumps(previous, ensure_ascii=False) if previous else None,
         json.dumps(current, ensure_ascii=False) if current else None],
    )



def create(
    conn: duckdb.DuckDBPyConnection, device_id: str, tz: str, payload: NewEvent,
) -> dict[str, Any]:
    _check_time(payload.occurred_at)
    key = str(payload.client_event_key)
    existing = conn.execute(
        f"SELECT {COLUMNS}, device_id, deleted_at FROM lab_events WHERE client_event_key = ?",
        [key],
    ).fetchone()
    if existing:
        if existing[-2] != device_id or existing[-1] is not None:
            raise ValueError("Clave de idempotencia ya utilizada")
        # Solo se reutiliza el resultado original; jamás se crean eventos duplicados.
        return {**_row(existing[:8], tz), "already_saved": True}
    event_id = str(uuid4())
    conn.execute("BEGIN TRANSACTION")
    try:
        conn.execute(
            """INSERT INTO lab_events
               (event_id, device_id, event_type, occurred_at, timezone,
                caffeine_mg, amount_basis, note, source, client_event_key)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'manual', ?)""",
            [event_id, device_id, payload.event_type, payload.occurred_at, tz,
             payload.caffeine_mg, payload.amount_basis, payload.note, key],
        )
        created = get(conn, device_id, tz, event_id)
        _audit(conn, event_id, "create", None, created)
        conn.execute("COMMIT")
        return created
    except Exception:
        conn.execute("ROLLBACK")
        raise


def get(
    conn: duckdb.DuckDBPyConnection, device_id: str, tz: str, event_id: str
) -> dict[str, Any]:
    try:
        canonical = str(UUID(event_id))
    except (ValueError, TypeError) as exc:
        raise LookupError("ID desconocido") from exc
    result = conn.execute(
        f"SELECT {COLUMNS} FROM lab_events WHERE device_id=? AND event_id=? "
        "AND deleted_at IS NULL", [device_id, canonical],
    ).fetchone()
    if result is None:
        raise LookupError("Acontecimiento no encontrado")
    return _row(result, tz)


def edit(
    conn: duckdb.DuckDBPyConnection, device_id: str, tz: str,
    event_id: str, payload: EditEvent,
) -> dict[str, Any]:
    orig = get(conn, device_id, tz, event_id)
    supplied = payload.model_fields_set
    if not supplied or not supplied <= {"occurred_at","caffeine_mg","amount_basis","note"}:
        raise ValueError("Indica al menos un campo editable")
    when = payload.occurred_at if "occurred_at" in supplied else datetime.fromisoformat(orig["occurred_at"])
    if when is None:
        raise ValueError("No puedes borrar la fecha")
    _check_time(when)
    caffeine = payload.caffeine_mg if "caffeine_mg" in supplied else orig["caffeine_mg"]
    basis = payload.amount_basis if "amount_basis" in supplied else orig["amount_basis"]
    if orig["event_type"] == "coffee":
        if caffeine is None or basis not in {"estimated", "label", "measured"}:
            raise ValueError("El café requiere una dosis estimada y su procedencia")
    elif caffeine is not None or basis is not None:
        raise ValueError("Este evento no admite cafeína")
    note = payload.note if "note" in supplied else orig["note"]
    conn.execute("BEGIN TRANSACTION")
    try:
        conn.execute(
            """UPDATE lab_events SET occurred_at=?, timezone=?, caffeine_mg=?,
               amount_basis=?, note=?, updated_at=current_timestamp
               WHERE event_id=? AND device_id=? AND deleted_at IS NULL""",
            [when, tz, caffeine, basis, note, event_id, device_id],
        )
        updated = get(conn, device_id, tz, event_id)
        _audit(conn, event_id, "edit", orig, updated)
        conn.execute("COMMIT")
        return updated
    except Exception:
        conn.execute("ROLLBACK")
        raise


def remove(conn: duckdb.DuckDBPyConnection, device_id: str, tz: str, event_id: str) -> dict:
    obj = get(conn, device_id, tz, event_id)
    conn.execute("BEGIN TRANSACTION")
    try:
        conn.execute(
            """UPDATE lab_events SET deleted_at=current_timestamp,
               updated_at=current_timestamp
               WHERE device_id=? AND event_id=? AND deleted_at IS NULL""",
            [device_id, event_id],
        )
        _audit(conn, event_id, "delete", obj, None)
        conn.execute("COMMIT")
        return {"deleted": True, "id": obj["id"]}
    except Exception:
        conn.execute("ROLLBACK")
        raise


def history(
    conn: duckdb.DuckDBPyConnection, device_id: str, tz: str,
    *, days: int = 30, limit: int = 200,
) -> list[dict]:
    if days < 1 or days > 365 or limit < 1 or limit > 500:
        raise ValueError("Rango de historial no admitido")
    since = datetime.now(UTC) - timedelta(days=days)
    rows = conn.execute(
        f"SELECT {COLUMNS} FROM lab_events WHERE device_id=? "
        "AND deleted_at IS NULL AND occurred_at >= ? "
        "ORDER BY occurred_at DESC LIMIT ?",
        [device_id, since, limit],
    ).fetchall()
    return [_row(rec, tz) for rec in rows]


BUCKETS = (("<2 h", 0, 120), ("2–3 h", 120, 180),
           ("3–4 h", 180, 240), (">=4 h", 240, 720))


def dinner_sleep_analysis(conn: duckdb.DuckDBPyConnection, device_id: str, tz: str) -> dict:
    """Una sola cena (la más reciente ANTERIOR a sueño) por noche WHOOP válida.

    Hasta 180 noches; excluye siestas, sesiones no puntuadas y solapamientos.
    N >= 5 por grupo para mostrar medias descriptivas; jamás inferencia causal.
    """
    nights = conn.execute(
        """SELECT local_sleep_date, sleep_start, sleep_min, rmssd_ms, rhr
           FROM daily_metrics WHERE device_id=?
           AND quality IN ('high','fair') AND score_state='SCORED'
           AND calibrating=false AND coalesce(night_check,'ok')='ok'
           AND sleep_start IS NOT NULL
           ORDER BY sleep_start DESC LIMIT 180""",
        [device_id],
    ).fetchall()
    earliest = min((n[1] for n in nights), default=None)
    dinners = conn.execute(
        """SELECT occurred_at FROM lab_events
           WHERE device_id=? AND event_type='dinner_end' AND deleted_at IS NULL
           AND occurred_at >= ? ORDER BY occurred_at ASC""",
        [device_id, earliest - timedelta(hours=12)],
    ).fetchall() if earliest else []
    dinners_ts = [d[0] for d in dinners]
    grouped = {label: [] for label, _, _ in BUCKETS}
    # Las ventanas para noches distintas no se solapan normalmente.
    paired = []
    for day, sleep_start, sleep_min, hrv, rhr in reversed(nights):
        candidate = next(
            (d for d in reversed(dinners_ts)
             if d <= sleep_start and timedelta(0) <= sleep_start - d <= timedelta(hours=12)),
            None,
        )
        if candidate is None:
            continue
        minutes = round((sleep_start-candidate).total_seconds()/60, 1)
        label = next((name for name, lo, hi in BUCKETS
                      if lo <= minutes < hi), None)
        if label is None:
            continue
        item = {"date": day.isoformat(), "interval_minutes": minutes,
                "sleep_min": sleep_min, "hrv_ms": hrv, "rhr": rhr}
        grouped[label].append(item)
        paired.append(item)
    def avg(vals: list[float]) -> float | None:
        return round(sum(vals)/len(vals), 1) if vals else None
    result = []
    for label, _, _ in BUCKETS:
        entries = grouped[label]
        ready = len(entries) >= 5
        hrv = [float(z["hrv_ms"]) for z in entries if z["hrv_ms"] is not None]
        rest = [float(z["rhr"]) for z in entries if z["rhr"] is not None]
        sleep = [float(z["sleep_min"]) for z in entries if z["sleep_min"] is not None]
        result.append({
            "label": label, "n": len(entries),
            "n_hrv": len(hrv), "n_rhr": len(rest), "n_sleep": len(sleep),
            "hrv_mean_ms": avg(hrv) if len(hrv) >= 5 else None,
            "rhr_mean": avg(rest) if len(rest) >= 5 else None,
            "sleep_mean_min": avg(sleep) if len(sleep) >= 5 else None,
            "status": "exploratory" if ready else "insufficient",
        })
    return {
        "total_valid_nights": len(nights),
        "paired_nights": len(paired),
        "bands": result,
        "ready_for_comparison": len(paired) >= 20 and any(
            sum(b[field] >= 5 for b in result) >= 2
            for field in ("n_hrv", "n_rhr", "n_sleep")
        ),
        "method": (
            "Última cena registrada dentro de las 12 h previas al inicio del "
            "sueño WHOOP en cada noche puntuable. WHOOP aproxima inicio del "
            "sueño, no necesariamente hora de acostarse. Grupos con menos de "
            "5 noches no muestran medias; no se ha ajustado por entrenamiento, "
            "alcohol, estrés, hora de acostarse ni otros confundidores. "
            "Los resultados NO establecen causalidad."
        ),
        "source": "Cena · registro manual; sueño/HRV/RHR · WHOOP directo",
    }


def timeline(
    conn: duckdb.DuckDBPyConnection, device_id: str, tz: str, *,
    days: int = 7,
) -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    rows = conn.execute(
        f"SELECT {COLUMNS} FROM lab_events WHERE device_id=? AND deleted_at IS NULL "
        "AND occurred_at >= ? ORDER BY occurred_at DESC LIMIT 160",
        [device_id, cutoff],
    ).fetchall()
    items = []
    for row in rows:
        evt = _row(row, tz)
        items.append({"type": evt["event_type"], "source": "manual",
                      "at": evt["occurred_at"], "label": {
                          "coffee": "Café", "dinner_end": "Cena terminada",
                          "bedtime": "Me acuesto",
                      }[evt["event_type"]], "event": evt})
    nights = conn.execute(
        """SELECT sleep_start, sleep_end, rmssd_ms, rhr, sleep_min
           FROM daily_metrics WHERE device_id=?
           AND quality IN ('high','fair') AND score_state='SCORED'
           AND calibrating=false AND coalesce(night_check,'ok')='ok'
           AND sleep_end >= ? ORDER BY sleep_end DESC LIMIT 10""",
        [device_id, cutoff],
    ).fetchall()
    for start,end,hrv,rhr,sleep in nights:
        if start:
            items.append({"type":"sleep", "source":"WHOOP",
                          "at":start.isoformat(), "label":"Sueño · inicio WHOOP",
                          "values":{"sleep_min":sleep,"hrv_ms":hrv,"rhr":rhr}})
    return sorted(items, key=lambda item: item["at"], reverse=True)[:180]


def daily_overview(events: list[dict], tz: str) -> dict:
    """Observación inmediata con eventos manuales; no atribuir causalidad."""
    now = datetime.now(ZoneInfo(tz)).date().isoformat()
    coffees = [e for e in events if e["event_type"]=="coffee"
               and e["local_date"]==now]
    dinners = [e for e in events if e["event_type"]=="dinner_end"]
    bedtimes = [e for e in events if e["event_type"]=="bedtime"]
    pairs=[]
    for bed in bedtimes:
        at = datetime.fromisoformat(bed["occurred_at"])
        chosen = next((
            dinner for dinner in dinners
            if datetime.fromisoformat(dinner["occurred_at"]) <= at and
            timedelta(0) <= at-datetime.fromisoformat(dinner["occurred_at"])
            <= timedelta(hours=12)
        ), None)
        if chosen:
            mins = round((at-datetime.fromisoformat(chosen["occurred_at"])).total_seconds()/60)
            pairs.append({"dinner_at":chosen["occurred_at"],"bedtime_at":bed["occurred_at"],
                          "gap_minutes":mins})
    return {
        "coffee_entries_today":len(coffees),
        "caffeine_logged_mg_today":round(sum(float(e["caffeine_mg"]) for e in coffees)),
        "last_coffee_at":coffees[0]["occurred_at"] if coffees else None,
        "last_dinner_bedtime_gap_min":pairs[0]["gap_minutes"] if pairs else None,
        "manual_pairs_30d":len(pairs),
        "mean_dinner_bedtime_gap_min":round(sum(p["gap_minutes"] for p in pairs)/len(pairs))
                                    if pairs else None,
        "method":(
            "Última cena registrada antes de cada evento «Me acuesto» "
            "(máximo 12 horas). Registro manual, distinto del inicio de "
            "sueño que WHOOP estima. Las dosis de cafeína son entradas "
            "registradas y pueden ser estimadas o incompletas."
        ),
    }


def overview(conn: duckdb.DuckDBPyConnection, device_id: str, tz: str) -> dict:
    events = history(conn, device_id, tz, days=30, limit=500)
    return {
        "events": events,
        "count_30d": len(events),
        "daily": daily_overview(events, tz),
        "dinner_sleep": dinner_sleep_analysis(conn, device_id, tz),
        "timeline": timeline(conn, device_id, tz),
        "quick_presets": [
            {"type":"coffee","mg":100,"basis":"estimated","label":"Café · 100 mg estimados"},
            {"type":"dinner_end","label":"Terminé de cenar"},
            {"type":"bedtime","label":"Me acuesto"},
        ],
        "time_zone":tz,
        "scope": "Manual ARES LAB + noches WHOOP válidas; sin enviar datos a IA externa",
    }
