"""ARES workout explorer: synthetic sessions and no GPS/user note leakage."""

from datetime import date

from fastapi.testclient import TestClient

from ares.app import training
from ares.app.server import create_app
from ares.connectors.base import store_raw


def seed(conn, *, ident="run-123", with_series=True):
    record = {
        "_id": ident,
        "date": "2026-10-13T06:00:00.000Z",
        "sportType": "running",
        "title": "4 x 1 km",
        "notes": "PRIVATE ATHLETE NOTE",
        "summary": {"duration": 1200, "distance": 4000, "heartrate": 146,
                    "heartrateMax": 172, "power": 260, "cadence": 178},
        "laps": [
            {"duration": 270, "distance": 1000, "pace": 270, "heartrate": 162},
            {"duration": 280, "distance": 1000, "pace": 280, "heartrate": 165},
        ],
        "positionLat": 39.12345,
        "positionLong": -0.54321,
    }
    if with_series:
        record["seriesSampled"] = {
            "sampleSize": 1,
            "data": {"heartrate": list(range(100, 400)), "speed": [3.1] * 300},
        }
    store_raw(
        conn, source="tredict", endpoint="activity_detail",
        day=date(2026, 10, 13), body=record,
    )


def test_list_sessions_uses_full_details_without_invented_values(conn):
    seed(conn)
    all_sessions = training.list_sessions(conn)
    assert len(all_sessions) == 1
    s = all_sessions[0]
    assert s["distance_m"] == 4000
    assert s["duration_s"] == 1200
    assert s["pace_s_km"] == 300 and s["pace_calculated"]
    assert s["avg_hr"] == 146 and s["laps_count"] == 2 and s["has_series"]
    assert "notes" not in s and "positionLat" not in s


def test_session_laps_series_downsampled_and_gps_private(conn):
    seed(conn)
    s = training.session(conn, "run-123")
    assert s is not None
    assert s["laps"][0]["pace_s_km"] == 270
    assert len(s["series"]["heartrate"]) <= 250
    assert s["series"]["heartrate"][0] == {"second": 0, "v": 100}
    assert s["series"]["speed"][0]["v"] == 3.1
    assert "PRIVATE ATHLETE NOTE" not in str(s)
    assert "39.12345" not in str(s)


def test_empty_and_invalid_sessions_do_not_expose_arbitrary_files(conn):
    assert training.list_sessions(conn) == []
    assert training.session(conn, "../../etc/passwd") is None
    assert training.session(conn, "not-found") is None


def test_endpoint_list_and_detail_no_geolocation(conn, settings):
    seed(conn)
    client = TestClient(create_app(lambda: conn, settings))
    overview = client.get("/api/entrenos")
    detail = client.get("/api/entreno/run-123")
    assert overview.status_code == 200 and detail.status_code == 200
    assert detail.json()["laps"][1]["pace_s_km"] == 280
    assert "positionLat" not in detail.text and "PRIVATE ATHLETE NOTE" not in detail.text
    assert client.get("/api/entreno/unknown-activity").status_code == 404
    assert client.get("/api/entrenos?limit=51").status_code == 422


def test_no_series_not_interpolated(conn):
    seed(conn, with_series=False)
    s = training.session(conn, "run-123")
    assert s is not None and s["has_series"] is False
    assert s["series"]["heartrate"] == []
