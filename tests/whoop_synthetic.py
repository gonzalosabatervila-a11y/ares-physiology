"""Registros sintéticos de la API v2 de WHOOP, con la forma del OpenAPI oficial (02/10/2026).

No son datos reales: las respuestas reales anonimizadas viven fuera de Git, en
~/ares-data/fixtures-private/ (scripts/record_whoop_fixtures.py). Aquí solo hay valores
inventados, con identificadores falsos, para probar contrato, noches y migraciones.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from ares.connectors.base import HttpClient

USER_ID = 10129
H = 3_600_000  # una hora en milisegundos


def ts(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def sleep_id(n: int) -> str:
    return str(uuid.UUID(int=n))


def sleep(
    n: int,
    cycle_id: int,
    start: datetime,
    end: datetime,
    *,
    tz: str = "+02:00",
    nap: bool = False,
    state: str = "SCORED",
    light_h: float = 3.5,
    sws_h: float = 1.5,
    rem_h: float = 2.0,
    resp: float | None = 14.6,
    updated: datetime | None = None,
) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "id": sleep_id(n),
        "cycle_id": cycle_id,
        "v1_id": None,
        "user_id": USER_ID,
        "created_at": ts(end + timedelta(minutes=5)),
        "updated_at": ts(updated or end + timedelta(minutes=10)),
        "start": ts(start),
        "end": ts(end),
        "timezone_offset": tz,
        "nap": nap,
        "score_state": state,
    }
    if state == "SCORED":
        awake = int(0.4 * H)
        rec["score"] = {
            "stage_summary": {
                "total_in_bed_time_milli": int((light_h + sws_h + rem_h) * H) + awake,
                "total_awake_time_milli": awake,
                "total_no_data_time_milli": 0,
                "total_light_sleep_time_milli": int(light_h * H),
                "total_slow_wave_sleep_time_milli": int(sws_h * H),
                "total_rem_sleep_time_milli": int(rem_h * H),
                "sleep_cycle_count": 4,
                "disturbance_count": 9,
            },
            "sleep_needed": {
                "baseline_milli": 27_000_000,
                "need_from_sleep_debt_milli": 600_000,
                "need_from_recent_strain_milli": 300_000,
                "need_from_recent_nap_milli": 0,
            },
            "respiratory_rate": resp,
            "sleep_performance_percentage": 88.0,
            "sleep_consistency_percentage": 79.0,
            "sleep_efficiency_percentage": 93.5,
        }
    return rec


def recovery(
    cycle_id: int,
    sleep_n: int,
    created: datetime,
    *,
    state: str = "SCORED",
    rmssd: float = 58.2,
    rhr: float = 47.0,
    calibrating: bool = False,
    score: float = 71.0,
    spo2: float | None = 96.4,
    skin: float | None = 33.7,
    updated: datetime | None = None,
) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "cycle_id": cycle_id,
        "sleep_id": sleep_id(sleep_n),
        "user_id": USER_ID,
        "created_at": ts(created),
        "updated_at": ts(updated or created + timedelta(minutes=2)),
        "score_state": state,
    }
    if state == "SCORED":
        rec["score"] = {
            "user_calibrating": calibrating,
            "recovery_score": score,
            "resting_heart_rate": rhr,
            "hrv_rmssd_milli": rmssd,
            "spo2_percentage": spo2,
            "skin_temp_celsius": skin,
        }
    return rec


def cycle(
    cycle_id: int,
    start: datetime,
    end: datetime | None,
    *,
    tz: str = "+02:00",
    steps: int | None = 8234,
    state: str = "SCORED",
) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "id": cycle_id,
        "user_id": USER_ID,
        "created_at": ts(start + timedelta(minutes=1)),
        "updated_at": ts((end or start) + timedelta(minutes=1)),
        "start": ts(start),
        "timezone_offset": tz,
        "score_state": state,
        "step_count": steps,
    }
    if end is not None:
        rec["end"] = ts(end)
    if state == "SCORED":
        rec["score"] = {
            "strain": 9.81,
            "kilojoule": 9120.5,
            "average_heart_rate": 64,
            "max_heart_rate": 151,
        }
    return rec


def workout(n: int, start: datetime, end: datetime, *, tz: str = "+02:00") -> dict[str, Any]:
    return {
        "id": str(uuid.UUID(int=10_000 + n)),
        "user_id": USER_ID,
        "created_at": ts(end),
        "updated_at": ts(end),
        "start": ts(start),
        "end": ts(end),
        "timezone_offset": tz,
        "sport_name": "running",
        "score_state": "SCORED",
        "score": {
            "strain": 11.2,
            "average_heart_rate": 142,
            "max_heart_rate": 171,
            "kilojoule": 2410.0,
            "percent_recorded": 100.0,
            "distance_meter": 10_020.0,
            "altitude_gain_meter": 46.0,
            "altitude_change_meter": 1.0,
            "zone_durations": {
                "zone_zero_milli": 0,
                "zone_one_milli": 300_000,
                "zone_two_milli": 2_700_000,
                "zone_three_milli": 600_000,
                "zone_four_milli": 0,
                "zone_five_milli": 0,
            },
        },
    }


def night(
    n: int,
    day_end: str,
    *,
    hours: float = 7.0,
    end_time: str = "05:30",
    steps: int | None = 8234,
    tz: str = "+02:00",
    open_cycle: bool = False,
    **recovery_kw: Any,
) -> dict[str, list[dict[str, Any]]]:
    """Una noche completa (ciclo, sueño y recuperación) que termina `day_end` a `end_time`
    UTC. Los ciclos de WHOOP empiezan al dormirse; el número `n` hace de identificador."""
    end = utc(f"{day_end}T{end_time}")
    start = end - timedelta(hours=hours + 0.4)
    k = hours / 7.0
    cycle_end = None if open_cycle else start + timedelta(hours=24)
    return {
        "cycle": [cycle(n, start, cycle_end, tz=tz, steps=steps)],
        "sleep": [sleep(n, n, start, end, tz=tz, light_h=3.5 * k, sws_h=1.5 * k, rem_h=2.0 * k)],
        "recovery": [recovery(n, n, end + timedelta(minutes=8), **recovery_kw)],
        "workout": [],
    }


def merge(*parts: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {"recovery": [], "sleep": [], "cycle": [], "workout": []}
    for p in parts:
        for k, v in p.items():
            out[k].extend(v)
    return out


PATH_TO_ENDPOINT = {
    "/developer/v2/recovery": "recovery",
    "/developer/v2/activity/sleep": "sleep",
    "/developer/v2/cycle": "cycle",
    "/developer/v2/activity/workout": "workout",
}


def api(
    data: dict[str, list[dict[str, Any]]],
    *,
    page_size: int = 25,
    seen: list[httpx.Request] | None = None,
    status: Callable[[httpx.Request], int | None] | None = None,
) -> HttpClient:
    """API simulada: pagina cada colección con next_token como hace WHOOP. `status` permite
    forzar un código (p. ej. 401) para una petición concreta."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        forced = status(request) if status else None
        if forced:
            return httpx.Response(forced, json={})
        endpoint = PATH_TO_ENDPOINT[urlparse(str(request.url)).path]
        q = parse_qs(urlparse(str(request.url)).query)
        offset = int(q.get("nextToken", ["0"])[0].removeprefix("tok"))
        limit = min(int(q.get("limit", ["10"])[0]), 25)
        limit = min(limit, page_size)
        records = data.get(endpoint, [])
        page = records[offset : offset + limit]
        body: dict[str, Any] = {"records": page}
        if offset + limit < len(records):
            body["next_token"] = f"tok{offset + limit}"
        return httpx.Response(200, json=body)

    return HttpClient(httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)


def authorize_store(set_secret: Callable[[str, str], None], expiry: datetime | None = None) -> None:
    """Deja el almacén (aislado en conftest) con un cliente y un token válidos."""
    set_secret("whoop_client_id", "cid")
    set_secret("whoop_client_secret", "csec")
    set_secret("whoop_access_token", "acc-0")
    set_secret("whoop_refresh_token", "ref-0")
    set_secret("whoop_token_expiry", (expiry or datetime.now(UTC) + timedelta(hours=1)).isoformat())
