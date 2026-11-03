"""Workout ↔ WHOOP context uses real UTC chronology, not just local date."""
from datetime import date

from ares.app.training_context import training_night_context


DEVICE = "pulsera-principal"


def night(conn, d, start, end, *, quality="high", hrv=50, rhr=48):
    conn.execute(
        """INSERT INTO daily_metrics
           (local_sleep_date, device_id, sleep_start, sleep_end,
            quality, score_state, calibrating, night_check, sleep_min,
            rmssd_ms, rhr, provider_recovery)
           VALUES (?, ?, ?, ?, ?, 'SCORED', false, 'ok', 450, ?, ?, 75)""",
        [date.fromisoformat(d), DEVICE, start, end, quality, hrv, rhr],
    )


def test_before_and_after_are_strictly_chronological(conn):
    night(conn, "2026-10-13", "2026-10-12T21:00:00+00",
          "2026-10-13T04:00:00+00", hrv=50, rhr=48)
    night(conn, "2026-10-14", "2026-10-13T21:00:00+00",
          "2026-10-14T05:00:00+00", hrv=42, rhr=54)
    r = training_night_context(conn, DEVICE, "2026-10-13T05:00:00Z", 3600)
    assert r["available"]
    assert r["before"]["date"] == "2026-10-13"
    assert r["after"]["date"] == "2026-10-14"
    assert r["difference"]["rmssd_ms"] == -8
    assert r["difference"]["rhr"] == 6


def test_overlapping_sleep_is_not_previous_or_next(conn):
    # Sleep ended after the exercise started; it must not be paired as "before".
    night(conn, "2026-10-13", "2026-10-12T23:00:00+00",
          "2026-10-13T06:00:00+00")
    r = training_night_context(conn, DEVICE, "2026-10-13T05:00:00Z", 3600)
    assert r["available"] is False
    assert r["before"] is None and r["after"] is None


def test_no_future_night_does_not_invent_response(conn):
    night(conn, "2026-10-13", "2026-10-12T21:00:00+00",
          "2026-10-13T04:00:00+00")
    r = training_night_context(conn, DEVICE, "2026-10-13T05:00:00Z", 3600)
    assert r["available"] is True
    assert r["after"] is None
    assert all(x is None for x in r["difference"].values())


def test_invalid_or_unscored_nights_not_used(conn):
    night(conn, "2026-10-13", "2026-10-12T21:00:00+00",
          "2026-10-13T04:00:00+00", quality="excluded")
    assert not training_night_context(
        conn, DEVICE, "2026-10-13T05:00:00Z", 3600
    )["available"]
    assert not training_night_context(
        conn, DEVICE, "2026-10-13T05:00:00", 3600
    )["available"]
    assert not training_night_context(
        conn, DEVICE, "2026-10-13T05:00:00Z", float("nan")
    )["available"]
