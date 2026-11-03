"""Tredict full activity API contracts, entirely synthetic and offline."""

from datetime import date

import httpx
import pytest

from ares.connectors.base import HttpClient, store_raw
from ares.connectors.tredict import (
    BASE_URL, fetch_activity_detail, sync_activity_details,
)


def activity_list(conn):
    for day, ident in (("2026-10-13", "act-13"), ("2026-10-12", "act-12"),
                       ("2026-09-13", "act-old")):
        store_raw(
            conn, source="tredict", endpoint="activity",
            day=date.fromisoformat(day),
            body={"id": ident, "date": day+"T07:00:00.000Z", "sportType": "running"},
        )


def mock():
    seen = []

    def handler(req):
        seen.append(req)
        ident = req.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={
            "_id": ident,
            "date": "2026-10-13T07:00:00.000Z",
            "sportType": "running",
            "summary": {"duration": 3000, "distance": 10800, "heartrate": 145},
            "laps": [{"duration": 300, "distance": 1000, "pace": 300, "heartrate": 148}],
            "seriesSampled": {"sampleSize": 1, "data": {"heartrate": [120, 123],
                                                           "speed": [3.1, 3.3]}},
        })

    http = HttpClient(httpx.Client(transport=httpx.MockTransport(handler)),
                      sleep=lambda _: None, jitter=lambda: 0)
    return http, seen


def test_full_activity_parameters_authenticated_and_saved_locally(conn):
    activity_list(conn)
    http, seen = mock()
    sleeps = []
    r = sync_activity_details(conn, http, "fake-secret", days=2, limit=2,
                              today=date(2026, 10, 13), sleep=sleeps.append)
    assert (r.fetched, r.inserted) == (2, 2)
    assert len(seen) == 2 and sleeps == [0.2]
    for request in seen:
        assert request.url.path.startswith("/api/oauth/v2/activity/act-")
        assert request.headers["Authorization"] == "Bearer fake-secret"
        assert request.url.params["allSeries"] == "1"
        assert request.url.params["withLaps"] == "1"
        assert request.url.params["extraValues"] == "1"
    assert conn.execute(
        "SELECT count(*) FROM raw_payload WHERE endpoint='activity_detail'"
    ).fetchone()[0] == 2
    # Ningún token forma parte de la capa bruta.
    assert "fake-secret" not in str(conn.execute(
        "SELECT body FROM raw_payload WHERE endpoint='activity_detail'"
    ).fetchall())
    assert conn.execute("SELECT endpoint, last_ok IS NOT NULL FROM source_status "
                        "WHERE source='tredict' AND endpoint='activity_detail'").fetchone() == (
                            "activity_detail", True
                        )


def test_full_activity_id_mismatch_rejected_and_error_visible(conn):
    activity_list(conn)

    def wrong_id(_):
        return httpx.Response(200, json={"_id": "another-id", "summary": {}})
    http = HttpClient(httpx.Client(transport=httpx.MockTransport(wrong_id)),
                      sleep=lambda _: None)
    with pytest.raises(ValueError, match="otra actividad"):
        sync_activity_details(conn, http, "fake-secret", days=1, limit=1,
                              today=date(2026, 10, 13))
    assert conn.execute("SELECT last_error IS NOT NULL FROM source_status "
                        "WHERE source='tredict' AND endpoint='activity_detail'").fetchone() == (True,)


def test_full_activity_duplicate_is_not_written_again(conn):
    activity_list(conn)
    http, _ = mock()
    first = sync_activity_details(conn, http, "fake-secret", days=2, limit=2,
                                  today=date(2026, 10, 13), sleep=lambda _: None)
    second = sync_activity_details(conn, http, "fake-secret", days=2, limit=2,
                                   today=date(2026, 10, 13), sleep=lambda _: None)
    assert (first.inserted, second.inserted, second.unchanged) == (2, 0, 2)


def test_invalid_detail_id_and_limits_rejected(conn):
    http, _ = mock()
    with pytest.raises(ValueError, match="no válido"):
        fetch_activity_detail(http, "fake-secret", "../../secret")
    with pytest.raises(ValueError, match="limit"):
        sync_activity_details(conn, http, "fake-secret", limit=100)
    with pytest.raises(ValueError, match="days"):
        sync_activity_details(conn, http, "fake-secret", days=0)
