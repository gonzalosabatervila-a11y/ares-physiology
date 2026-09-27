-- 003_decisions.sql

CREATE TABLE decisions (           -- lo que ARES dijo: nunca se modifica
  d DATE PRIMARY KEY, level VARCHAR NOT NULL, cause VARCHAR,
  signals JSON NOT NULL,           -- valor, rol decisiva|contexto, etiqueta y origen
  context JSON, data_complete BOOLEAN,
  input_hash VARCHAR NOT NULL, metrics_snapshot JSON NOT NULL,
  baseline_id VARCHAR, algo_version VARCHAR, filter_version VARCHAR,
  rules_version VARCHAR NOT NULL, generated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE decision_conflicts (
  d DATE, detected_at TIMESTAMPTZ, existing_hash VARCHAR, new_hash VARCHAR,
  new_snapshot JSON,
  PRIMARY KEY (d, detected_at)
);

CREATE TABLE decisions_recomputed (
  recompute_id VARCHAR PRIMARY KEY,
  d DATE NOT NULL,
  rules_version VARCHAR NOT NULL,
  algo_version VARCHAR,
  filter_version VARCHAR,
  baseline_id VARCHAR,
  level VARCHAR,
  cause VARCHAR,
  signals JSON,
  computed_at TIMESTAMPTZ NOT NULL
  -- varias simulaciones del mismo día sin pisarse
);

CREATE TABLE gate_results (
  evaluated_at TIMESTAMPTZ PRIMARY KEY,
  level VARCHAR,                   -- none | provisional | validated
  filter_version VARCHAR, n_h10 INTEGER,
  criteria JSON, agreement JSON    -- Bland–Altman, CCC, concordancia longitudinal
);
