CREATE SCHEMA IF NOT EXISTS public_data;

CREATE TABLE public_data.meta (id int PRIMARY KEY DEFAULT 1 CHECK (id = 1), refreshed_at timestamptz NOT NULL);
CREATE TABLE public_data.athlete (pseudonym text PRIMARY KEY, age_bracket text);
CREATE TABLE public_data.workouts (
  pseudonym text NOT NULL, day date NOT NULL, sport text NOT NULL,
  duration_min int NOT NULL, distance_km real, tss real, avg_hr real
);
CREATE TABLE public_data.weekly_volume (
  week_start date NOT NULL, sport text NOT NULL, hours real NOT NULL, distance_km real NOT NULL,
  PRIMARY KEY (week_start, sport)
);
CREATE TABLE public_data.fitness_daily (day date PRIMARY KEY, ctl real NOT NULL, atl real NOT NULL, tsb real NOT NULL);
CREATE TABLE public_data.goal_progress (
  id int PRIMARY KEY DEFAULT 1 CHECK (id = 1), weeks_remaining int, current_ctl real,
  target_ctl real, percent_of_target real
);
CREATE TABLE public_data.reference_population (
  metric text NOT NULL, percentile int NOT NULL, value real NOT NULL, source text NOT NULL,
  PRIMARY KEY (metric, percentile)
);
CREATE TABLE public_data.percentiles (metric text PRIMARY KEY, percentile real NOT NULL, source text NOT NULL);

-- Roles. Passwords here are local-development defaults; the chart overrides them.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ironman_public') THEN
    CREATE ROLE ironman_public LOGIN PASSWORD 'ironman_public';
  END IF;
END $$;
REVOKE ALL ON SCHEMA private FROM ironman_public;
REVOKE ALL ON ALL TABLES IN SCHEMA private FROM ironman_public;
REVOKE ALL ON SCHEMA public FROM ironman_public;
GRANT USAGE ON SCHEMA public_data TO ironman_public;
GRANT SELECT ON ALL TABLES IN SCHEMA public_data TO ironman_public;
