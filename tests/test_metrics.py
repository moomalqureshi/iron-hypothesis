from datetime import date

import pytest
from conftest import utc

from ironman import ingest, metrics
from ironman.metrics import Thresholds, WorkoutLoad


def test_bike_power_tss_one_hour_at_ftp_is_100():
    tss, m = metrics.compute_tss(WorkoutLoad("bike", 3600, avg_power=250), Thresholds(ftp=250))
    assert tss == pytest.approx(100) and m == "power"


def test_run_pace_tss():
    # 10 km in 50 min at threshold pace 300 s/km -> IF 1.0 over 50/60 h
    tss, m = metrics.compute_tss(
        WorkoutLoad("run", 3000, distance_m=10000), Thresholds(run_threshold_pace=300)
    )
    assert tss == pytest.approx(100 * 50 / 60) and m == "pace"


def test_hr_fallback_marked_estimate():
    tss, m = metrics.compute_tss(WorkoutLoad("bike", 3600, avg_hr=150), Thresholds(max_hr=190))
    assert tss is not None and m == "hr-estimate"


def test_no_signal_returns_none():
    assert metrics.compute_tss(WorkoutLoad("bike", 3600), Thresholds()) == (None, None)
    assert metrics.compute_tss(WorkoutLoad("bike", 3600, avg_power=200), Thresholds()) == (
        None,
        None,
    )


def test_rest_days_decay_ctl_and_atl():
    s = metrics.fitness_series({date(2026, 5, 1): 100.0}, date(2026, 5, 1), date(2026, 5, 4))
    ctl = [r[2] for r in s]
    atl = [r[3] for r in s]
    assert ctl[0] > ctl[1] > ctl[2] > ctl[3] > 0
    assert atl[1] < atl[0] and atl[0] > ctl[0]
    assert s[1][4] == pytest.approx(ctl[0] - atl[0])  # TSB uses previous day


def test_threshold_history_respected():
    rows = [
        {
            "effective_from": date(2026, 1, 1),
            "ftp": 200,
            "run_threshold_pace": None,
            "swim_css": None,
            "max_hr": None,
            "lthr": None,
        },
        {
            "effective_from": date(2026, 6, 1),
            "ftp": 250,
            "run_threshold_pace": None,
            "swim_css": None,
            "max_hr": None,
            "lthr": None,
        },
    ]
    assert metrics.thresholds_for(rows, date(2026, 5, 1)).ftp == 200
    assert metrics.thresholds_for(rows, date(2026, 6, 2)).ftp == 250
    assert metrics.thresholds_for(rows, date(2025, 1, 1)).ftp is None


def _add(conn, day, sid, **kw):
    base = dict(
        source="strava",
        source_id=sid,
        sport="bike",
        start_time=utc(2026, 5, day, 6),
        duration_s=3600,
        avg_power=250.0,
    )
    ingest.store_workout(conn, ingest.Workout(**{**base, **kw}))


def test_db_scoring_flags_unscorable_and_recompute(conn):
    _add(conn, 1, "a")
    _add(conn, 2, "b", sport="swim", avg_power=None)  # no thresholds for swim -> flagged
    conn.execute("INSERT INTO private.thresholds (effective_from, ftp) VALUES ('2026-01-01', 250)")
    metrics.score_workouts(conn)
    rows = {r["source_id"]: r for r in conn.execute("SELECT * FROM private.workouts")}
    assert rows["a"]["tss"] == pytest.approx(100) and rows["b"]["tss"] is None
    assert "no usable" in rows["b"]["flagged"]
    assert metrics.recompute_from(conn) > 0
    d = {r["day"]: r for r in conn.execute("SELECT * FROM private.daily_metrics")}
    assert d[date(2026, 5, 1)]["tss"] == pytest.approx(100)


def test_late_workout_recomputes_forward(conn):
    conn.execute("INSERT INTO private.thresholds (effective_from, ftp) VALUES ('2026-01-01', 250)")
    _add(conn, 5, "late1")
    metrics.score_workouts(conn)
    metrics.recompute_from(conn)
    before = conn.execute(
        "SELECT ctl FROM private.daily_metrics WHERE day='2026-05-06'"
    ).fetchone()["ctl"]
    _add(conn, 2, "late2")
    metrics.score_workouts(conn, date(2026, 5, 2))
    metrics.recompute_from(conn, date(2026, 5, 2))
    after = conn.execute("SELECT ctl FROM private.daily_metrics WHERE day='2026-05-06'").fetchone()[
        "ctl"
    ]
    assert after > before


def test_weekly_volume_per_sport(conn):
    _add(conn, 4, "a")
    _add(conn, 5, "b", sport="run", distance_m=10000.0)
    v = {r["sport"]: r for r in metrics.weekly_volume(conn)}
    assert v["bike"]["hours"] == pytest.approx(1.0) and v["run"]["distance_km"] == pytest.approx(10)


def test_zone_bounds():
    z = metrics.zone_bounds("power", Thresholds(ftp=200))
    assert len(z) == 7 and z[0][1] == 0 and z[3][2] == pytest.approx(210)
    assert metrics.zone_bounds("power", Thresholds()) == []


def test_time_in_zone_uses_threshold_in_effect(conn):
    conn.execute("INSERT INTO private.thresholds (effective_from, ftp) VALUES ('2000-01-01', 200)")
    samples = [
        {
            "ts": utc(2026, 5, 1, 6, 0, i),
            "hr": None,
            "power": p,
            "speed": None,
            "cadence": None,
            "altitude": None,
            "lat": None,
            "lon": None,
        }
        for i, p in enumerate([100, 100, 180, 250])
    ]
    wid, _ = ingest.store_workout(
        conn, ingest.Workout("s", "z", "bike", utc(2026, 5, 1, 6), 4, samples=samples)
    )
    t = metrics.thresholds_for(
        conn.execute("SELECT * FROM private.thresholds").fetchall(), date(2026, 5, 1)
    )
    z = metrics.time_in_zone(conn, wid, "power", t)
    assert (z["Z1"], z["Z2"], z["Z3"], z["Z4"], z["Z6"]) == (2, 0, 0, 1, 1)
