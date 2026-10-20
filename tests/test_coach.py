import json
from datetime import date, timedelta

import fakeredis
import pytest
from conftest import utc
from fastapi import HTTPException

from ironman import analysis, coach, demo, ingest, metrics

WEEK = date.today() - timedelta(days=date.today().weekday()) + timedelta(days=7)


def _plan_json(minutes=60, intensity="easy", rest=True):
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    s = [
        {"day": d, "sport": "run", "minutes": minutes, "intensity": intensity, "intent": "x"}
        for d in days
    ]
    if rest:
        s[2] = {"day": "wed", "sport": "rest", "minutes": 0, "intensity": "rest", "intent": "rest"}
    return json.dumps({"sessions": s})


@pytest.fixture
def seeded(conn):
    demo.seed(conn, weeks=12)
    conn.commit()
    return conn


def test_prompt_contains_aggregates_only(seeded):
    seeded.execute(
        "INSERT INTO private.identity (name,email,password_hash) VALUES ('Jane Athlete','a@b.c','h')"
    )
    ingest.store_workout(
        seeded,
        ingest.Workout(
            "strava",
            "9",
            "run",
            utc(2026, 5, 1, 6),
            1800,
            samples=[
                {
                    "ts": utc(2026, 5, 1, 6),
                    "hr": 1,
                    "power": None,
                    "speed": 1,
                    "cadence": 1,
                    "altitude": 1,
                    "lat": 52.5200,
                    "lon": 13.4050,
                }
            ],
        ),
    )
    p = coach.build_prompt(coach.build_inputs(seeded, WEEK))
    for s in ("Jane", "a@b.c", "52.52", "13.405", "token", "strava"):
        assert s not in p
    assert "previous_week_tss" in p


def test_load_cap_enforced(seeded):
    plan = coach.parse_plan(_plan_json(minutes=240, intensity="hard"))
    safe, adj = coach.apply_guardrails(plan, previous_tss=300, risk_level="low")
    assert coach.plan_load(safe) <= 300 * 1.10 + 1
    assert any(a["rule"] == "load_cap" for a in adj)


def test_plan_under_cap_untouched():
    plan = coach.parse_plan(_plan_json(minutes=30))
    safe, adj = coach.apply_guardrails(plan, previous_tss=500, risk_level="low")
    assert adj == [] and safe == plan


def test_high_risk_forces_reduction():
    plan = coach.parse_plan(_plan_json(minutes=60, intensity="moderate"))
    prev = coach.plan_load(plan)  # same load would pass the 10% cap
    safe, adj = coach.apply_guardrails(plan, previous_tss=prev, risk_level="high")
    assert coach.plan_load(safe) <= prev * 0.8 + 1 and adj[0]["rule"] == "risk_reduction"


def test_rest_day_added():
    plan = coach.parse_plan(_plan_json(rest=False))
    safe, adj = coach.apply_guardrails(plan, previous_tss=10_000, risk_level="low")
    assert any(s.sport == "rest" for s in safe.sessions) and adj[0]["rule"] == "rest_day"


def test_generate_stores_plan_with_inputs(seeded):
    out = coach.generate_plan(seeded, WEEK, llm=lambda p: _plan_json(30))
    row = seeded.execute("SELECT * FROM private.plans").fetchone()
    assert row["inputs"]["previous_week_tss"] >= 0 and row["plan"]["sessions"]
    assert "not medical advice" in out["disclaimer"]


def test_malformed_output_retries_then_fails_without_storing(seeded):
    calls = []

    def bad(p):
        calls.append(1)
        return "sorry, I cannot do that"

    with pytest.raises(HTTPException) as e:
        coach.generate_plan(seeded, WEEK, llm=bad)
    assert e.value.status_code == 502 and len(calls) == coach.MAX_ATTEMPTS
    assert seeded.execute("SELECT count(*) AS n FROM private.plans").fetchone()["n"] == 0


def test_schema_violation_rejected(seeded):
    bad = json.dumps(
        {
            "sessions": [
                {"day": "mon", "sport": "run", "minutes": 9999, "intensity": "easy", "intent": "x"}
            ]
        }
    )
    with pytest.raises(HTTPException) as e:
        coach.generate_plan(seeded, WEEK, llm=lambda p: bad)
    assert e.value.status_code == 502


def test_llm_outage_is_503_and_rest_of_app_works(seeded, monkeypatch):
    def down(p):
        raise coach.LLMError("LLM API unavailable: boom")

    with pytest.raises(HTTPException) as e:
        coach.generate_plan(seeded, WEEK, llm=down)
    assert e.value.status_code == 503
    assert metrics.weekly_volume(seeded)  # unaffected


def test_missing_api_key_reports_clearly(seeded):
    with pytest.raises(HTTPException) as e:
        coach.generate_plan(seeded, WEEK)
    assert e.value.status_code == 503 and "IRONMAN_LLM_API_KEY" in e.value.detail


def test_daily_rate_limit(seeded, monkeypatch):
    monkeypatch.setenv("IRONMAN_LLM_MAX_CALLS_PER_DAY", "2")
    from ironman import config

    config.get_settings.cache_clear()
    r = fakeredis.FakeRedis()
    try:
        coach.generate_plan(seeded, WEEK, llm=lambda p: _plan_json(30), redis=r)
        coach.generate_plan(seeded, WEEK, llm=lambda p: _plan_json(30), redis=r)
        with pytest.raises(HTTPException) as e:
            coach.generate_plan(seeded, WEEK, llm=lambda p: _plan_json(30), redis=r)
        assert e.value.status_code == 429
    finally:
        config.get_settings.cache_clear()


# --- analysis -------------------------------------------------------------------
def test_forecast_converges_toward_planned_load():
    f = analysis.forecast_ctl(50, 50, [100] * 90)
    assert f[0]["ctl"] > 50 and f[-1]["ctl"] > f[10]["ctl"] and f[-1]["ctl"] < 100


def test_risk_unknown_without_history(conn):
    assert analysis.overtraining_risk(conn)["level"] == "unknown"


def test_risk_rises_with_ramp(conn):
    conn.execute("INSERT INTO private.thresholds (effective_from, ftp) VALUES ('2000-01-01', 250)")
    today = date.today()
    for i in range(1, 5):  # steady prior weeks
        ingest.store_workout(
            conn,
            ingest.Workout(
                "s",
                f"p{i}",
                "bike",
                utc(today.year, today.month, today.day, 6) - timedelta(weeks=i, days=-1),
                3600,
                avg_power=200.0,
            ),
        )
    for i in range(3):  # big current week
        ingest.store_workout(
            conn,
            ingest.Workout(
                "s",
                f"c{i}",
                "bike",
                utc(today.year, today.month, today.day, 5) - timedelta(days=i),
                14400,
                avg_power=250.0,
            ),
        )
    metrics.score_workouts(conn)
    metrics.recompute_from(conn)
    r = analysis.overtraining_risk(conn)
    assert r["level"] in ("medium", "high") and r["factors"]


def test_anomalies_insufficient_data(conn):
    r = analysis.anomalies(conn)
    assert r["status"] == "insufficient data" and r["flagged"] == []


def test_anomalies_flags_outlier(conn):
    demo.seed(conn, weeks=26)
    ingest.store_workout(
        conn,
        ingest.Workout(
            "s", "weird", "run", utc(2026, 1, 1, 6), 3600, distance_m=10000.0, avg_hr=198.0
        ),
    )
    metrics.score_workouts(conn)
    r = analysis.anomalies(conn)
    assert r["status"] == "ok"


def test_race_time_needs_data_then_estimates(conn):
    assert analysis.predict_race_time(conn)["status"] == "insufficient data"
    demo.seed(conn, weeks=12)
    r = analysis.predict_race_time(conn)
    lo, hi = r["range_seconds"]
    assert (
        r["status"] == "ok"
        and lo < r["finish_seconds"] < hi
        and 8 * 3600 < r["finish_seconds"] < 30 * 3600
    )


def test_hr_drift():
    flat = [(200, 140)] * 700
    drift = [(200, 140)] * 350 + [(200, 154)] * 350
    assert analysis.hr_drift(flat) == pytest.approx(0)
    assert analysis.hr_drift(drift) > 0.05
    assert analysis.hr_drift([(1, 1)] * 10) is None
