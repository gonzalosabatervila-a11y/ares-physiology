"""Política de reintentos del plan: 5xx y 429 se reintentan; 401 no."""

from __future__ import annotations

import httpx
import pytest

from ares.connectors.base import ConnectorError, HttpClient


def client_with(responses: list[int], sleeps: list[float]) -> tuple[HttpClient, list]:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        code = responses[len(calls)]
        calls.append(code)
        return httpx.Response(code, json=[])

    http = HttpClient(
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
        jitter=lambda: 0.0,
    )
    return http, calls


def test_503_se_reintenta_con_espera_2s():
    sleeps: list[float] = []
    http, calls = client_with([503, 200], sleeps)
    assert http.get("https://x.test/a").status_code == 200
    assert calls == [503, 200] and sleeps == [2.0]


def test_401_no_se_reintenta():
    sleeps: list[float] = []
    http, calls = client_with([401], sleeps)
    with pytest.raises(ConnectorError, match="401"):
        http.get("https://x.test/a")
    assert calls == [401] and sleeps == []


def test_5xx_persistente_agota_tres_reintentos():
    sleeps: list[float] = []
    http, calls = client_with([500, 500, 500, 500], sleeps)
    with pytest.raises(ConnectorError):
        http.get("https://x.test/a")
    assert len(calls) == 4 and sleeps == [2.0, 8.0, 30.0]
