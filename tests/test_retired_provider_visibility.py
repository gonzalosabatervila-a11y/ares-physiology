"""Regression: historical providers remain archived, not presented as current sources."""

from __future__ import annotations

from ares.app import data


def test_retirado_no_aparece_en_fuentes_activas_ni_laboratorio(conn, settings):
    conn.execute(
        "INSERT INTO source_status (source, endpoint, device_id) VALUES "
        "('polar', 'sleeps', 'pulsera-anterior'), "
        "('whoop', 'recovery', 'pulsera-principal')"
    )
    conn.execute(
        """INSERT INTO raw_payload
           (source, endpoint, day, device_id, fetched_at, sha256, body)
           VALUES
           ('polar', 'sleeps', DATE '2026-09-01', 'pulsera-anterior',
            TIMESTAMPTZ '2026-09-01 09:00:00+00', 'legacy-fixture', '{}'),
           ('whoop', 'recovery', DATE '2026-10-13', 'pulsera-principal',
            TIMESTAMPTZ '2026-10-13 09:00:00+00', 'current-fixture', '{}')"""
    )

    current = data.sources(conn)
    panel = data.lab(conn, settings)
    assert {s["source"] for s in current} == {"whoop"}
    assert {s["source"] for s in panel["sources"]} == {"whoop"}
    assert {r["source"] for r in panel["raw"]} == {"whoop"}

    # Removing a provider from the UI must never erase historical health data.
    assert conn.execute(
        "SELECT count(*) FROM raw_payload WHERE source='polar'"
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT count(*) FROM source_status WHERE source='polar'"
    ).fetchone()[0] == 1
