-- 004_provider_whoop.sql · WHOOP como proveedor fisiológico (Implementation Plan v0.3, §4;
-- fe de erratas v0.3). No borra ni modifica nada de la capa bruta: las tablas y vistas del
-- proveedor anterior siguen intactas hasta una retirada aparte (005), que exige aprobación.

CREATE VIEW raw_whoop_recovery AS SELECT * FROM raw_payload WHERE source='whoop' AND endpoint='recovery';
CREATE VIEW raw_whoop_sleep    AS SELECT * FROM raw_payload WHERE source='whoop' AND endpoint='sleep';
CREATE VIEW raw_whoop_cycle    AS SELECT * FROM raw_payload WHERE source='whoop' AND endpoint='cycle';
CREATE VIEW raw_whoop_workout  AS SELECT * FROM raw_payload WHERE source='whoop' AND endpoint='workout';

-- daily_metrics: reconstruible desde lo bruto; se recrea con la forma v0.3
DROP TABLE daily_metrics;
CREATE TABLE daily_metrics (
  local_sleep_date DATE, device_id VARCHAR,
  sleep_start TIMESTAMPTZ, sleep_end TIMESTAMPTZ,      -- UTC
  source_tz VARCHAR,                                   -- offset o zona original, si la trae
  sleep_min INTEGER,                                   -- ligero + profundo + REM (fe de erratas D8)
  rmssd_ms DOUBLE, ln_rmssd DOUBLE,
  hrv_tag VARCHAR, hrv_origin VARCHAR,                 -- MED + WHOOP
  rhr DOUBLE, resp_rate DOUBLE, spo2 DOUBLE, skin_temp DOUBLE,
  provider_recovery DOUBLE,                            -- segunda opinión, nunca decide
  steps_whoop_cycle INTEGER,                           -- pasos del ciclo; segunda fuente, puede ser nulo
  score_state VARCHAR, calibrating BOOLEAN,
  ctl DOUBLE, atl DOUBLE,
  quality VARCHAR,                                     -- high | fair | excluded
  algo_version VARCHAR, adapter_version VARCHAR,
  whoop_sleep_id VARCHAR,                              -- sueño usado como noche (recovery.sleep_id)
  whoop_cycle_id BIGINT,                               -- ciclo de la recuperación
  night_check VARCHAR,                                 -- ok | siesta | difiere_del_mas_largo | offset_incoherente
  PRIMARY KEY (local_sleep_date, device_id)
);

ALTER TABLE devices ADD COLUMN provider VARCHAR;

-- Aquí no hay DROP de lo bruto. Lo del proveedor anterior sigue intacto hasta la 005.
