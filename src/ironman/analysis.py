"""Baseline predictive analysis: CTL forecast, overtraining risk, anomalies, race-time estimate.

These are transparent baselines that run in-process. Trained models served by the inference
service (LightGBM, MLflow registry) are separate tasks and are not implemented yet."""

from __future__ import annotations

from datetime import date, timedelta

from ironman import metrics

MIN_ANOMALY_HISTORY = 20
RACE = {"swim_m": 3800, "bike_m": 180000, "run_m": 42195}  # full distance


def forecast_ctl(ctl: float, atl: float, planned_daily_tss: list[float]) -> list[dict]:
    series = metrics.fitness_series(
        {date(2000, 1, 1) + timedelta(days=i): t for i, t in enumerate(planned_daily_tss)},
        date(2000, 1, 1),
        date(2000, 1, 1) + timedelta(days=len(planned_daily_tss) - 1),
        ctl,
        atl,
    )
    return [
        {"day_offset": i + 1, "ctl": round(c, 1), "atl": round(a, 1), "tsb": round(s, 1)}
        for i, (_, _, c, a, s) in enumerate(series)
    ]


def forecast_to_race(conn, weekly_tss: float | None = None) -> dict | None:
    """Project CTL/TSB to race day if the owner holds `weekly_tss` (default: last 4-week average)."""
    g = conn.execute("SELECT * FROM private.race_goal").fetchone()
    m = conn.execute(
        "SELECT ctl, atl FROM private.daily_metrics ORDER BY day DESC LIMIT 1"
    ).fetchone()
    if not g or not m:
        return None
    days = (g["race_date"] - date.today()).days
    if days <= 0:
        return None
    if weekly_tss is None:
        weekly_tss = _recent_weekly_tss(conn, 4)
    series = forecast_ctl(m["ctl"], m["atl"], [weekly_tss / 7] * days)
    return {"assumed_weekly_tss": round(weekly_tss), "days_to_race": days, "race_day": series[-1]}


def _recent_weekly_tss(conn, weeks: int) -> float:
    r = conn.execute(
        "SELECT coalesce(sum(tss),0) AS s FROM private.workouts WHERE start_time >= now() - %s * interval '1 week'",
        (weeks,),
    ).fetchone()
    return float(r["s"]) / weeks


def overtraining_risk(conn) -> dict:
    """Rule-based risk from load ramp and form; lists the contributing factors."""
    this_wk = _recent_weekly_tss(conn, 1)
    prev = (
        conn.execute(
            "SELECT coalesce(sum(tss),0) AS s FROM private.workouts WHERE start_time >= now() - interval '5 weeks' "
            "AND start_time < now() - interval '1 week'"
        ).fetchone()["s"]
        / 4
    )
    m = conn.execute("SELECT * FROM private.daily_metrics ORDER BY day DESC LIMIT 1").fetchone()
    if not m or prev <= 0:
        return {"level": "unknown", "factors": ["insufficient history"]}
    ramp = this_wk / prev - 1
    factors, score = [], 0
    if ramp > 0.3:
        factors.append(f"weekly load up {ramp:.0%} on the 4-week average")
        score += 2
    elif ramp > 0.15:
        factors.append(f"weekly load up {ramp:.0%} on the 4-week average")
        score += 1
    if m["tsb"] < -30:
        factors.append(f"form (TSB) very low at {m['tsb']:.0f}")
        score += 2
    elif m["tsb"] < -20:
        factors.append(f"form (TSB) low at {m['tsb']:.0f}")
        score += 1
    if m["atl"] > m["ctl"] * 1.5 and m["ctl"] > 20:
        factors.append("fatigue is far above fitness")
        score += 1
    return {
        "level": "high" if score >= 3 else "medium" if score >= 1 else "low",
        "factors": factors,
        "ramp": round(ramp, 3),
        "tsb": round(m["tsb"], 1),
    }


def hr_drift(samples: list[tuple[float, float]]) -> float | None:
    """Aerobic decoupling: relative rise in HR per unit of output (power or speed), 2nd vs 1st half."""
    pts = [(o, h) for o, h in samples if o and o > 0 and h and h > 0]
    if len(pts) < 600:
        return None
    half = len(pts) // 2

    def ratio(p):
        return sum(h for _, h in p) / sum(o for o, _ in p)

    return ratio(pts[half:]) / ratio(pts[:half]) - 1


def anomalies(conn) -> dict:
    """Flag workouts whose features sit far outside the owner's own history (Isolation Forest)."""
    rows = conn.execute(
        "SELECT id, start_time, sport, duration_s, avg_hr, avg_power, distance_m, tss FROM private.workouts "
        "WHERE avg_hr IS NOT NULL AND tss IS NOT NULL"
    ).fetchall()
    if len(rows) < MIN_ANOMALY_HISTORY:
        return {
            "status": "insufficient data",
            "needed": MIN_ANOMALY_HISTORY,
            "have": len(rows),
            "flagged": [],
        }
    import numpy as np
    from sklearn.ensemble import IsolationForest

    flagged = []
    for sport in ("swim", "bike", "run"):
        sub = [r for r in rows if r["sport"] == sport]
        if len(sub) < MIN_ANOMALY_HISTORY:
            continue
        x = np.array(
            [
                [r["duration_s"] / 3600, r["avg_hr"], r["tss"] / (r["duration_s"] / 3600)]
                for r in sub
            ]
        )
        model = IsolationForest(random_state=0, contamination=0.05).fit(x)
        for r, p in zip(sub, model.predict(x), strict=True):
            if p == -1:
                flagged.append(
                    {
                        "workout_id": str(r["id"]),
                        "date": r["start_time"].date().isoformat(),
                        "sport": sport,
                        "reason": "unusual duration/HR/intensity combination",
                    }
                )
    return {"status": "ok", "flagged": flagged}


def predict_race_time(conn) -> dict:
    """Baseline finish-time estimate from recent per-sport pace with a fatigue factor, plus a range."""
    r = conn.execute(
        "SELECT sport, sum(duration_s) AS s, sum(distance_m) AS d, count(*) AS n FROM private.workouts "
        "WHERE start_time >= now() - interval '8 weeks' AND distance_m > 0 AND sport IN ('swim','bike','run') "
        "AND duration_s > 900 GROUP BY sport"
    ).fetchall()
    by = {x["sport"]: x for x in r}
    missing = [s for s in ("swim", "bike", "run") if s not in by or by[s]["n"] < 4]
    if missing:
        return {
            "status": "insufficient data",
            "missing_sports": missing,
            "note": "needs at least 4 sessions of each sport in the last 8 weeks",
        }
    speed = {s: float(by[s]["d"]) / float(by[s]["s"]) for s in by}  # m/s
    fatigue = {"swim": 0.97, "bike": 0.93, "run": 0.80}  # race-distance durability (assumed)
    secs = {
        "swim": RACE["swim_m"] / (speed["swim"] * fatigue["swim"]),
        "bike": RACE["bike_m"] / (speed["bike"] * fatigue["bike"]),
        "run": RACE["run_m"] / (speed["run"] * fatigue["run"]),
    }
    total = sum(secs.values()) + 600 + 300  # transitions
    return {
        "status": "ok",
        "finish_seconds": round(total),
        "range_seconds": [round(total * 0.92), round(total * 1.10)],
        "splits_seconds": {k: round(v) for k, v in secs.items()},
        "model": "baseline-pace-v1",
    }
