"""Gestor del token de Polar: renueva antes de caducar, guarda el par nuevo y
conserva el refresh token si Polar no envía uno."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from ares.connectors import polar_tokens

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def store(**overrides: str) -> dict[str, str]:
    base = {
        "polar_client_id": "cid",
        "polar_client_secret": "csec",
        "polar_access_token": "acc-old",
        "polar_refresh_token": "ref-old",
        "polar_token_expiry": (NOW + timedelta(hours=3)).isoformat(),
    }
    base.update(overrides)
    return base


def http_returning(body: dict, status: int = 200) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def call(secrets: dict[str, str], http: httpx.Client | None = None) -> str:
    return polar_tokens.get_access_token(
        http=http,
        secret_getter=secrets.get,
        secret_setter=secrets.__setitem__,
        now=NOW,
    )


def test_token_vigente_no_renueva():
    http, seen = http_returning({})
    assert call(store(), http) == "acc-old"
    assert seen == []


def test_token_por_caducar_renueva_y_guarda_el_par_nuevo():
    secrets = store(polar_token_expiry=(NOW + timedelta(minutes=2)).isoformat())
    http, seen = http_returning(
        {"access_token": "acc-new", "refresh_token": "ref-new", "expires_in": 43199}
    )
    assert call(secrets, http) == "acc-new"
    assert len(seen) == 1
    assert secrets["polar_access_token"] == "acc-new"
    assert secrets["polar_refresh_token"] == "ref-new"
    assert "refresh_token=ref-old" in seen[0].content.decode()


def test_si_polar_no_envia_refresh_token_se_conserva_el_anterior():
    secrets = store(polar_token_expiry=(NOW - timedelta(minutes=1)).isoformat())
    http, _ = http_returning({"access_token": "acc-new", "expires_in": 3600})
    call(secrets, http)
    assert secrets["polar_refresh_token"] == "ref-old"


def test_expiry_sin_zona_se_interpreta_como_utc():
    secrets = store(polar_token_expiry=(NOW + timedelta(hours=2)).replace(tzinfo=None).isoformat())
    http, seen = http_returning({})
    assert call(secrets, http) == "acc-old"
    assert seen == []


def test_faltan_credenciales_del_cliente():
    with pytest.raises(polar_tokens.TokenError, match="credenciales del cliente"):
        call(store(polar_client_secret=""))


def test_sin_autorizacion_pide_polar_auth():
    with pytest.raises(polar_tokens.TokenError, match="polar-auth"):
        call(store(polar_access_token=""))
