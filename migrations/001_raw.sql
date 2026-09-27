-- 001_raw.sql · capa bruta: solo se añade, nunca se modifica
-- (schema_version la crea y mantiene db.py antes de aplicar migraciones)

CREATE TABLE raw_payload (
  source VARCHAR NOT NULL,         -- polar | intervals | tredict | apple_health
  endpoint VARCHAR NOT NULL,
  day DATE NOT NULL,
  device_id VARCHAR,
  fetched_at TIMESTAMPTZ NOT NULL,
  sha256 VARCHAR NOT NULL,
  body JSON NOT NULL,
  PRIMARY KEY (source, endpoint, day, sha256)
);

CREATE TABLE raw_polar_ppi (
  device_id VARCHAR, day DATE, offset_ms BIGINT,
  pp_ms INTEGER, err_ms INTEGER,
  skin_contact BOOLEAN, movement BOOLEAN, offline BOOLEAN,
  source_sha256 VARCHAR,
  PRIMARY KEY (device_id, day, offset_ms)
);

CREATE TABLE raw_h10_rr (
  session_id VARCHAR, t_utc TIMESTAMPTZ, rr_ms INTEGER, file_sha256 VARCHAR,
  PRIMARY KEY (session_id, t_utc)
);

CREATE TABLE raw_checkin_events (
  id VARCHAR PRIMARY KEY, received_at TIMESTAMPTZ NOT NULL,
  effective_date DATE NOT NULL, body JSON NOT NULL
);

CREATE VIEW checkin_latest AS
  SELECT * FROM raw_checkin_events
  QUALIFY row_number() OVER (PARTITION BY effective_date ORDER BY received_at DESC) = 1;

CREATE VIEW raw_polar_nightly      AS SELECT * FROM raw_payload WHERE source='polar' AND endpoint='nightly-recharge-results';
CREATE VIEW raw_polar_sleep        AS SELECT * FROM raw_payload WHERE source='polar' AND endpoint='sleeps';
CREATE VIEW raw_polar_hr           AS SELECT * FROM raw_payload WHERE source='polar' AND endpoint='continuous-samples';
CREATE VIEW raw_intervals_wellness AS SELECT * FROM raw_payload WHERE source='intervals' AND endpoint='wellness';
CREATE VIEW raw_tredict_activity   AS SELECT * FROM raw_payload WHERE source='tredict' AND endpoint='activity';
CREATE VIEW raw_tredict_metrics    AS SELECT * FROM raw_payload WHERE source='tredict' AND endpoint='metrics';
