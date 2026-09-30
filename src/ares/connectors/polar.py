"""Conector de Polar AccessLink v4: guarda en la capa bruta lo que devuelve tu Loop.

Estructura verificada con respuestas reales (29-30/09/2026). Convenciones de la API:
`from` inclusivo y `to` exclusivo; con `features` solo se admite un día; los PPI cuentan
desde la medianoche local del día del documento (en ms) y marcan el INICIO de cada
intervalo. Por eso se guardan los desplazamientos tal cual y la conversión a UTC se hace al
procesar, con la zona del sueño (que sí trae su offset explícito).

Los PPI ocupan unos 5 MB al día: van a `raw_polar_ppi` (normalizados y sin pérdida de
campos) y a `raw_payload` solo un resumen. Guardar el documento entero en cada sincronización
horaria lo duplicaría decenas de veces.
"""

from __future__ import annotations

import csv
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import duckdb

from .base import ConnectorError, HttpClient, mark_status, store_raw

BASE_URL = "https://www.polaraccesslink.com/v4/data"
SOURCE = "polar"
CHUNK = 500  # filas por INSERT de PPI


@dataclass(frozen=True)
class Endpoint:
    name: str  # valor de raw_payload.endpoint (las vistas raw_polar_* usan estos nombres)
    path: str
    features: tuple[str, ...] = ()


ENDPOINTS: tuple[Endpoint, ...] = (
    Endpoint("sleeps", "/sleeps", ("sleep-result", "sleep-evaluation", "sleep-score")),
    Endpoint("nightly-recharge-results", "/nightly-recharge-results", ("samples",)),
    Endpoint("ppi-samples", "/ppi-samples", ("samples",)),
    Endpoint("continuous-samples", "/continuous-samples", ("heart-rate-samples",)),
    Endpoint("activity", "/activity/list", ("samples",)),
    Endpoint("sleep-wake-vectors", "/sleep-wake-vectors"),
)


@dataclass
class SyncResult:
    fetched: int  # llamadas que respondieron bien
    inserted: int  # documentos nuevos en raw_payload
    ppi_rows: int = 0  # filas nuevas de PPI
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def unchanged(self) -> int:
        return self.fetched - self.inserted


def has_data(body: Any) -> bool:
    """¿Hay algo más que listas vacías? Un día sin sueño devuelve `nightSleeps: []`."""
    if not isinstance(body, dict):
        return bool(body)
    return any(isinstance(v, list) and v for v in body.values())


def fetch_day(http: HttpClient, token: str, ep: Endpoint, day: date) -> Any:
    params: dict[str, Any] = {"from": day.isoformat(), "to": (day + timedelta(days=1)).isoformat()}
    if ep.features:
        params["features"] = list(ep.features)  # clave repetida: es lo que acepta Polar
    resp = http.get(
        BASE_URL + ep.path,
        params=params,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    return resp.json()


def _ppi_entries(doc: Any, day: date) -> list[dict[str, Any]]:
    if not isinstance(doc, dict):
        return []
    return [e for e in doc.get("dailyPpiSamples", []) if e.get("date") == day.isoformat()]


def _insert_ppi(conn: duckdb.DuckDBPyConnection, uuid: str, day: date, samples: list[dict]) -> int:
    """Inserta solo los intervalos que aún no están, en un único bloque. Devuelve cuántos."""
    have = {
        r[0]
        for r in conn.execute(
            "SELECT offset_ms FROM raw_polar_ppi WHERE device_id = ? AND day = ?", [uuid, day]
        ).fetchall()
    }
    fresh: list[dict] = []
    for s in samples:
        off = int(s["offsetMillis"])
        if off not in have:
            have.add(off)  # también evita duplicados dentro del propio documento
            fresh.append(s)
    if not fresh:
        return 0
    # Un fichero temporal y read_csv: pasar decenas de miles de valores de Python como parámetros
    # tardaba ~26 s por día de PPI; así son 0,35 s.
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    try:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            for s in fresh:
                w.writerow(
                    [
                        int(s["offsetMillis"]),
                        int(s["ppInterval"]),
                        int(s.get("errorEstimateMillis", 0)),
                        int(bool(s.get("skinContact"))),
                        int(bool(s.get("movement"))),
                        int(bool(s.get("offline"))),
                    ]
                )
        quoted = path.replace("'", "''")
        conn.execute(
            f"""INSERT INTO raw_polar_ppi
                SELECT ?, ?, o, p, e, c::BOOLEAN, m::BOOLEAN, f::BOOLEAN, NULL
                FROM read_csv('{quoted}', header=false,
                  columns={{'o':'BIGINT','p':'INTEGER','e':'INTEGER',
                            'c':'INTEGER','m':'INTEGER','f':'INTEGER'}})
                ON CONFLICT DO NOTHING""",
            [uuid, day],
        )
    finally:
        os.unlink(path)
    return len(fresh)


def store_ppi(conn: duckdb.DuckDBPyConnection, doc: Any, day: date) -> tuple[int, bool]:
    """(filas nuevas, ¿documento-resumen nuevo?). Solo añade: una pulsación ya guardada no se
    reescribe aunque Polar la corrija después."""
    new_rows, summaries = 0, []
    for entry in _ppi_entries(doc, day):
        for dev in entry.get("ppiSamplesPerDevice") or []:
            uuid = (dev.get("recordingDevice") or {}).get("uuid") or "desconocido"
            samples = dev.get("ppiSamples") or []
            if not samples:
                continue
            new_rows += _insert_ppi(conn, uuid, day, samples)
            summaries.append(
                {
                    "uuid": uuid,
                    "n_samples": len(samples),
                    "first_offset_ms": samples[0].get("offsetMillis"),
                    "last_offset_ms": samples[-1].get("offsetMillis"),
                    "trigger_changes": dev.get("recordingTriggerTypeChanges") or [],
                }
            )
    if not summaries:
        return 0, False
    body = {
        "date": day.isoformat(),
        "modified": _ppi_entries(doc, day)[0].get("modified"),
        "devices": summaries,
        "nota": "las muestras están en raw_polar_ppi",
    }
    return new_rows, store_raw(conn, source=SOURCE, endpoint="ppi-samples", day=day, body=body)


def sync_polar(
    conn: duckdb.DuckDBPyConnection,
    http: HttpClient,
    token: str,
    days: int,
    today: date | None = None,
) -> SyncResult:
    """Descarga los últimos `days` días (hoy incluido) de todos los endpoints de Polar."""
    last = today or date.today()
    res = SyncResult(fetched=0, inserted=0)
    ok_by_ep: dict[str, bool] = {ep.name: True for ep in ENDPOINTS}
    for k in range(days - 1, -1, -1):
        day = last - timedelta(days=k)
        for ep in ENDPOINTS:
            try:
                doc = fetch_day(http, token, ep, day)
            except ConnectorError as exc:
                ok_by_ep[ep.name] = False
                res.errors[ep.name] = str(exc)
                continue
            res.fetched += 1
            if ep.name == "ppi-samples":
                rows, is_new = store_ppi(conn, doc, day)
                res.ppi_rows += rows
                res.inserted += int(is_new)
            elif has_data(doc) and store_raw(
                conn, source=SOURCE, endpoint=ep.name, day=day, body=doc
            ):
                res.inserted += 1
    for ep in ENDPOINTS:
        mark_status(
            conn,
            source=SOURCE,
            endpoint=ep.name,
            ok=ok_by_ep[ep.name],
            error=res.errors.get(ep.name),
        )
    if res.fetched == 0 and res.errors:
        raise ConnectorError(
            "Polar: ninguna llamada respondió — " + next(iter(res.errors.values()))
        )
    return res
