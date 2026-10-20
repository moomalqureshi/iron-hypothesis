CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE SCHEMA IF NOT EXISTS private;

CREATE TABLE private.identity (
  id          int PRIMARY KEY DEFAULT 1 CHECK (id = 1),  -- single owner
  name        text NOT NULL DEFAULT '',
  email       text NOT NULL,
  password_hash text,
  totp_secret text,
  totp_confirmed boolean NOT NULL DEFAULT false,
  birth_year  int,
  hide_hr_public boolean NOT NULL DEFAULT false
);

CREATE TABLE private.strava_tokens (
  id          int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  athlete_id  bigint NOT NULL,
  access_token_enc  text NOT NULL,
  refresh_token_enc text NOT NULL,
  expires_at  timestamptz NOT NULL
);

CREATE TABLE private.workouts (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source      text NOT NULL,                  -- strava | fit | gpx
  source_id   text,
  sport       text NOT NULL CHECK (sport IN ('swim','bike','run','other')),
  start_time  timestamptz NOT NULL,
  duration_s  int NOT NULL CHECK (duration_s > 0),
  distance_m  double precision,
  avg_hr      real,
  max_hr      real,
  avg_power   real,
  np_power    real,
  avg_speed   real,
  elevation_gain_m real,
  tss         real,
  tss_method  text,                           -- power | pace | hr | hr-estimate
  flagged     text,
  has_samples boolean NOT NULL DEFAULT false,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source, source_id)
);
CREATE INDEX workouts_start_idx ON private.workouts (start_time);

CREATE TABLE private.workout_samples (
  workout_id  uuid NOT NULL,
  ts          timestamptz NOT NULL,
  hr          real, power real, speed real, cadence real, altitude real,
  lat         double precision, lon double precision
);
SELECT create_hypertable('private.workout_samples', 'ts');
CREATE INDEX ON private.workout_samples (workout_id, ts);

CREATE TABLE private.daily_metrics (
  day date PRIMARY KEY,
  tss real NOT NULL, ctl real NOT NULL, atl real NOT NULL, tsb real NOT NULL
);

CREATE TABLE private.thresholds (
  effective_from date PRIMARY KEY,
  ftp real, run_threshold_pace real,  -- seconds per km
  swim_css real,                      -- seconds per 100 m
  max_hr real, lthr real
);

CREATE TABLE private.race_goal (
  id int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  name text NOT NULL, race_date date NOT NULL,
  target_seconds int, target_ctl real
);

CREATE TABLE private.plans (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  week_start date NOT NULL,
  plan jsonb NOT NULL, inputs jsonb NOT NULL, adjustments jsonb NOT NULL DEFAULT '[]',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE private.share_links (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scope text[] NOT NULL, label text NOT NULL DEFAULT '',
  expires_at timestamptz NOT NULL, revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE private.audit_log (
  id bigserial PRIMARY KEY, at timestamptz NOT NULL DEFAULT now(),
  event text NOT NULL, detail jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE private.failed_jobs (
  id bigserial PRIMARY KEY, at timestamptz NOT NULL DEFAULT now(),
  kind text NOT NULL, payload jsonb NOT NULL, error text NOT NULL
);

CREATE TABLE private.model_predictions (
  id bigserial PRIMARY KEY, at timestamptz NOT NULL DEFAULT now(),
  kind text NOT NULL, result jsonb NOT NULL, model_version text
);
