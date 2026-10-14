-- 005_lab_events.sql · ARES LAB: eventos manuales propios, separados de sensores.
-- Migración ADITIVA: no modifica raw_payload, daily_metrics ni datos históricos.
-- Cada evento conserva el instante original, procedencia y revisiones.
CREATE TABLE lab_events (
    event_id VARCHAR PRIMARY KEY,
    device_id VARCHAR NOT NULL,
    event_type VARCHAR NOT NULL CHECK (event_type IN ('coffee', 'dinner_end', 'bedtime')),
    occurred_at TIMESTAMPTZ NOT NULL,
    timezone VARCHAR NOT NULL DEFAULT 'Europe/Madrid',
    caffeine_mg DOUBLE,
    amount_basis VARCHAR,
    note VARCHAR,
    source VARCHAR NOT NULL DEFAULT 'manual',
    client_event_key VARCHAR NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    deleted_at TIMESTAMPTZ,
    CHECK (
      (event_type = 'coffee' AND caffeine_mg IS NOT NULL
       AND caffeine_mg >= 0 AND caffeine_mg <= 500
       AND amount_basis IN ('estimated','label','measured'))
      OR
      (event_type IN ('dinner_end','bedtime') AND caffeine_mg IS NULL
       AND amount_basis IS NULL)
    )
);
CREATE INDEX lab_events_time_idx ON lab_events(device_id, occurred_at);
