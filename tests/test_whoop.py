"""Pruebas del conector WHOOP API v2 con datos sintéticos, sin red ni credenciales."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from ares import whoop_metrics
from ares.connectors import whoop
from ares.connectors.base import HttpClient


def test_auth_url_requests_minimal_scopes_and_state():
    url = whoop.authorization_url("test-client", "https://gonzaloos.es/whoop/callback", "abcdefgh")
    args = parse_qs(urlparse(url).query)
    assert args["state"] == ["abcdefgh"]
    assert args["scope"] == [whoop.SCOPES]
    assert "offline" in args["scope"][0]
    assert "read:profile" not in args["scope"][0]
    with pytest.raises(ValueError):
        whoop.authorization_url("c", "https://example.com/cb", "short")


def test_rotating_refresh_token_is_persisted(monkeypatch):
    data = {
        "whoop_client_id": "client",
        "whoop_client_secret": "secret",
        "whoop_access_token": "expired",
        "whoop_refresh_token": "old-refresh",
        "whoop_token_expiry": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
    }
    monkeypatch.setattr(whoop.config, "get_secret", data.get)
    monkeypatch.setattr(whoop.config, "set_secret", data.__setitem__)
    def handle(request):
        assert request.url.path == "/oauth/oauth2/token"
        assert b"refresh_token=old-refresh" in request.content
        return httpx.Response(200, json={
            "access_token": "fresh", "refresh_token": "rotated", "expires_in": 3600
        })
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert whoop.get_access_token(http=client) == "fresh"
    assert data["whoop_refresh_token"] == "rotated"
    assert data["whoop_access_token"] == "fresh"


def test_sync_paginated_idempotent_and_summary(conn):
    counts = {"sleep": 0, "recovery": 0, "cycle": 0, "workout": 0}
    sleep = {
        "id": "sleep-1", "end": "2026-11-02T06:45:00Z",
        "start": "2026-11-01T21:00:00Z", "nap": False,
        "score_state": "SCORED",
        "score": {
            "stage_summary": {
                "total_light_sleep_time_milli": 14_400_000,
                "total_slow_wave_sleep_time_milli": 7_200_000,
                "total_rem_sleep_time_milli": 3_600_000,
            },
            "sleep_performance_percentage": 90,
            "sleep_needed": {"baseline_milli": 28_800_000},
        },
    }
    rec = {
        "sleep_id": "sleep-1", "cycle_id": 42, "created_at": "2026-11-02T07:00:00Z",
        "score_state": "SCORED",
        "score": {"recovery_score": 68, "hrv_rmssd_milli": 62, "resting_heart_rate": 50},
    }
    cycle = {"id": 42, "start": "2026-11-02T07:00:00Z", "score_state": "SCORED",
             "score": {"strain": 11.3}, "step_count": 11200}
    workout = {"id": "workout-1", "end": "2026-11-02T09:00:00Z"}

    def handle(request):
        ep = request.url.path.rsplit("/", 1)[-1]
        counts[ep] += 1
        assert request.headers["Authorization"] == "Bearer test-token"
        if ep == "sleep":
            if request.url.params.get("nextToken"):
                return httpx.Response(200, json={"records": [sleep], "next_token": None})
            return httpx.Response(200, json={"records": [], "next_token": "page2"})
        return httpx.Response(200, json={"records": [{
            "recovery": rec, "cycle": cycle, "workout": workout
        }[ep]], "next_token": None})
    with httpx.Client(transport=httpx.MockTransport(handle)) as c:
        http = HttpClient(client=c)
        now = datetime(2026, 11, 3, tzinfo=UTC)
        first = whoop.sync_whoop(conn, http, "test-token", 5, now=now)
        again = whoop.sync_whoop(conn, http, "test-token", 5, now=now)
    assert (first.fetched, first.inserted) == (4, 4)
    assert (again.fetched, again.inserted) == (4, 0)
    assert counts == {"sleep": 4, "recovery": 2, "cycle": 2, "workout": 2}
    result = whoop_metrics.summary(conn)
    assert result["connected"]
    row = result["records"][0]
    assert row["date"] == "2026-11-02"
    assert row["recovery"] == 68
    assert row["hrv_rmssd_ms"] == 62
    assert row["strain"] == 11.3
    assert row["sleep_hours"] == 7.0
    assert row["sleep_need_hours"] == 8.0


def test_missing_whoop_data_is_not_fabricated(conn):
    result = whoop_metrics.summary(conn)
    assert result["connected"] is False
    assert result["records"] == []
    assert result["last_sync"] is None
