"""COROS running / WHOOP walking and rucking catalog · offline synthetic tests."""
from datetime import date

from fastapi.testclient import TestClient

from ares.app import training_catalog
from ares.app.server import create_app
from ares.connectors.base import store_raw


def tredict(conn, *, ident: str, when: str, sport="running", summary=None):
    store_raw(
        conn, source="tredict", endpoint="activity",
        day=date.fromisoformat(when[:10]),
        body={
            "id": ident, "date": when, "sportType": sport,
            "title": "Series" if sport == "running" else "Fuerza",
            "summary": summary or {"duration": 3600, "distance": 9000, "heartrate": 148},
        },
    )


def whoop(conn, device: str, *, ident: str, when: str, sport="walking",
          end="2026-10-13T06:40:00+00:00"):
    store_raw(
        conn, source="whoop", endpoint="workout",
        device_id=device, day=date.fromisoformat(when[:10]),
        body={
            "id": ident, "start": when, "end": end,
            "sport_name": sport, "score_state": "SCORED",
            "score": {"average_heart_rate": 108, "max_heart_rate": 136, "strain": 6.9},
        },
    )


def test_running_from_tredict_other_from_whoop_no_whoop_run(conn, settings):
    tredict(conn, ident="coros-run-1", when="2026-10-13T05:00:00Z")
    whoop(conn, settings.device_id, ident="whoop-run-1",
          when="2026-10-13T05:00:00Z", sport="running")
    whoop(conn, settings.device_id, ident="whoop-walk-1",
          when="2026-10-13T05:30:00Z", sport="walking")
    whoop(conn, settings.device_id, ident="whoop-ruck-1",
          when="2026-10-12T05:30:00Z", sport="rucking",
          end="2026-10-12T06:30:00Z")

    r = training_catalog.catalog(conn, settings.device_id, category="running")
    o = training_catalog.catalog(conn, settings.device_id, category="other")
    assert r["counts"] == o["counts"] == {"running": 1, "other": 2}
    assert [x["id"] for x in r["sessions"]] == ["coros-run-1"]
    assert {x["title"] for x in o["sessions"]} == {"Caminar", "Rucking"}
    assert {x["source"] for x in o["sessions"]} == {"whoop"}
    assert not any("Rucking" == x["title"] for x in r["sessions"])


def test_simple_walking_is_never_mislabelled_rucking(conn, settings):
    whoop(conn, settings.device_id, ident="whoop-walk-1",
          when="2026-10-13T05:30:00Z", sport="walking")
    x = training_catalog.catalog(conn, settings.device_id, category="other")["sessions"][0]
    assert x["title"] == "Caminar" and "ruck" not in x["title"].lower()


def test_other_activity_duplicate_15_min_priority_whoop(conn, settings):
    whoop(conn, settings.device_id, ident="whoop-strength",
          when="2026-10-13T05:30:00Z", sport="weightlifting")
    tredict(conn, ident="coros-strength", when="2026-10-13T05:32:00Z",
            sport="misc", summary={"duration": 3600})
    o = training_catalog.catalog(conn, settings.device_id, category="other")
    assert o["counts"]["other"] == 1
    assert o["sessions"][0]["source"] == "whoop"


def test_same_time_different_sports_not_deduplicated(conn, settings):
    whoop(conn, settings.device_id, ident="whoop-walking",
          when="2026-10-13T05:30:00Z", sport="walking")
    tredict(conn, ident="coros-strength", when="2026-10-13T05:32:00Z",
            sport="misc", summary={"duration": 3600})
    r = training_catalog.catalog(conn, settings.device_id, category="other")
    assert r["counts"]["other"] == 2
    assert {x["source"] for x in r["sessions"]} == {"whoop", "tredict"}


def test_whoop_device_id_isolation_and_detail_without_series(conn, settings):
    whoop(conn, "other-wearer", ident="another-walk",
          when="2026-10-13T05:00:00Z")
    whoop(conn, settings.device_id, ident="walk-001",
          when="2026-10-13T05:30:00Z")
    o = training_catalog.catalog(conn, settings.device_id, category="other")
    assert [x["id"] for x in o["sessions"]] == ["walk-001"]
    detail = training_catalog.detail(conn, "walk-001", device_id=settings.device_id)
    assert detail["source"] == "whoop"
    assert detail["analysis"] is None
    assert detail["laps"] == []
    assert detail["series"]["heartrate"] == []
    assert detail["avg_hr"] == 108
    assert training_catalog.detail(conn, "another-walk", device_id=settings.device_id) is None


def test_tredict_summary_visible_before_full_training_import(conn, settings):
    tredict(conn, ident="coros-run-1", when="2026-10-13T05:00:00Z")
    summary = training_catalog.catalog(conn, settings.device_id, category="running")
    assert len(summary["sessions"]) == 1
    assert summary["sessions"][0]["has_detail"] is False
    workout = training_catalog.detail(conn, "coros-run-1", device_id=settings.device_id)
    assert workout["has_detail"] is False
    assert workout["source"] == "tredict"
    assert workout["laps"] == []


def test_http_correr_otros_and_read_only_status(conn, settings):
    tredict(conn, ident="coros-run-1", when="2026-10-13T05:00:00Z")
    whoop(conn, settings.device_id, ident="walk-001",
          when="2026-10-13T05:30:00Z")
    api = TestClient(create_app(lambda: conn, settings))
    a = api.get("/api/entrenos?category=running")
    b = api.get("/api/entrenos?category=other")
    assert a.status_code == b.status_code == 200
    assert a.json()["sync_mode"] == b.json()["sync_mode"] == "read_only"
    assert a.json()["sessions"][0]["source"] == "tredict"
    assert b.json()["sessions"][0]["source"] == "whoop"
    assert a.json()["last_record_dates"]["tredict/activity"] == "2026-10-13"
    assert api.get("/api/entrenos?category=none").status_code == 422
    assert api.get("/api/entreno/walk-001").json()["source"] == "whoop"
    automatic = TestClient(create_app(lambda: conn, settings, auto_sync=True))
    assert automatic.get("/api/entrenos").json()["sync_mode"] == "automatic"
    assert automatic.get("/api/home").json()["sync_mode"] == "automatic"
