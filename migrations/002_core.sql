-- 002_core.sql · todo reconstruible desde la capa bruta

CREATE TABLE devices (device_id VARCHAR PRIMARY KEY, model VARCHAR, first_day DATE, last_day DATE);

CREATE TABLE baselines (
  baseline_id VARCHAR PRIMARY KEY, device_id VARCHAR, valid_from DATE,
  n_nights INTEGER,
  status VARCHAR,                 -- provisional (21–59 noches) | mature (>= 60)
  filter_version VARCHAR, params JSON
);

CREATE TABLE ppi_quality (        -- cuánto elimina cada regla, por noche y versión de filtro
  device_id VARCHAR, local_sleep_date DATE, filter_version VARCHAR,
  n_total INTEGER, n_movement INTEGER, n_contact INTEGER, n_error INTEGER,
  n_range INTEGER, n_delta INTEGER,
  night_ppi_hours DOUBLE, window_coverage DOUBLE,
  PRIMARY KEY (device_id, local_sleep_date, filter_version)
);

CREATE TABLE daily_metrics (
  local_sleep_date DATE, device_id VARCHAR,
  sleep_start TIMESTAMPTZ, sleep_end TIMESTAMPTZ,  -- almacenados en UTC
  source_tz VARCHAR,                -- offset o zona original de la fuente, si la trae
  sleep_min INTEGER, battery_ran_out BOOLEAN,
  rmssd_ms DOUBLE, ln_rmssd DOUBLE,
  hrv_tag VARCHAR, hrv_origin VARCHAR,  -- CALC + ARES | CALC + POLAR
  night_ppi_hours DOUBLE, window_coverage DOUBLE, rejected_pct DOUBLE,
  rhr DOUBLE, resp_rate DOUBLE, ctl DOUBLE, atl DOUBLE,
  quality VARCHAR,                  -- high | fair | excluded
  algo_version VARCHAR, filter_version VARCHAR,
  PRIMARY KEY (local_sleep_date, device_id)
);

CREATE TABLE source_status (
  source VARCHAR NOT NULL, endpoint VARCHAR NOT NULL,
  device_id VARCHAR NOT NULL DEFAULT 'global',   -- nunca NULL
  last_ok TIMESTAMPTZ, last_error TIMESTAMPTZ, error VARCHAR,
  PRIMARY KEY (source, endpoint, device_id)
);

CREATE TABLE job_runs (
  run_id VARCHAR PRIMARY KEY, job VARCHAR, started TIMESTAMPTZ, ended TIMESTAMPTZ,
  status VARCHAR, git_commit VARCHAR, app_version VARCHAR, host VARCHAR,
  rules_version VARCHAR, detail JSON
);
