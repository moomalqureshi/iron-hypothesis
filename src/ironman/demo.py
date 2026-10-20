"""Synthetic training data: seeds a local database and backs the public demo mode.

Nothing here reads real records; the generator is deterministic for a given seed."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta

from ironman import metrics
from ironman.ingest import Workout, store_workout


def synthetic_workouts(weeks: int = 26, seed: int = 7, end: date | None = None) -> list[Workout]:
    rng = random.Random(seed)
    end = end or date.today()
    start = end - timedelta(weeks=weeks)
    monday = start - timedelta(days=start.weekday())
    out: list[Workout] = []
    for wk in range(weeks):
        ramp = 0.6 + 0.01 * wk  # gentle build
        if wk % 4 == 3:
            ramp *= 0.7  # recovery week
        plan = [
            (0, "swim", 3000),
            (1, "run", 8000),
            (2, "bike", 40000),
            (3, "swim", 3200),
            (4, "run", 10000),
            (5, "bike", 90000),
            (6, "run", 14000),
        ]
        for dow, sport, dist in plan:
            day = monday + timedelta(weeks=wk, days=dow)
            if day > end or day < start or rng.random() < 0.1:
                continue
            d = dist * ramp * rng.uniform(0.9, 1.1)
            speed = {"swim": 1.1, "run": 3.1, "bike": 8.0}[sport] * rng.uniform(0.95, 1.05)
            dur = int(d / speed)
            out.append(
                Workout(
                    source="demo",
                    source_id=f"demo-{seed}-{day}-{sport}",
                    sport=sport,
                    start_time=datetime(day.year, day.month, day.day, 6, 30, tzinfo=UTC),
                    duration_s=dur,
                    distance_m=d,
                    avg_hr=rng.uniform(130, 155),
                    avg_power=rng.uniform(170, 210) if sport == "bike" else None,
                    np_power=rng.uniform(185, 225) if sport == "bike" else None,
                )
            )
    return out


DEMO_THRESHOLDS = {
    "ftp": 230.0,
    "run_threshold_pace": 285.0,
    "swim_css": 100.0,
    "max_hr": 185.0,
    "lthr": 165.0,
}


def seed(conn, weeks: int = 26) -> int:
    for w in synthetic_workouts(weeks):
        store_workout(conn, w)
    conn.execute(
        "INSERT INTO private.thresholds VALUES ('2000-01-01', %(ftp)s, %(run_threshold_pace)s, "
        "%(swim_css)s, %(max_hr)s, %(lthr)s) ON CONFLICT DO NOTHING",
        DEMO_THRESHOLDS,
    )
    metrics.score_workouts(conn)
    return metrics.recompute_from(conn)


def public_demo_payload(weeks: int = 26) -> dict:
    """Pure in-memory demo view; the database is never touched."""
    ws = synthetic_workouts(weeks)
    t = metrics.Thresholds(**DEMO_THRESHOLDS)
    daily: dict[date, float] = {}
    weekly: dict[tuple[date, str], list[float]] = {}
    for w in ws:
        tss, _ = metrics.compute_tss(
            metrics.WorkoutLoad(
                w.sport, w.duration_s, w.distance_m, w.avg_hr, w.avg_power, w.np_power
            ),
            t,
        )
        d = w.start_time.date()
        daily[d] = daily.get(d, 0) + (tss or 0)
        k = (d - timedelta(days=d.weekday()), w.sport)
        h, km = weekly.setdefault(k, [0.0, 0.0])
        weekly[k] = [h + w.duration_s / 3600, km + (w.distance_m or 0) / 1000]
    series = metrics.fitness_series(daily, min(daily), max(daily))
    return {
        "demo": True,
        "fitness": [
            {"day": d, "ctl": round(c, 1), "atl": round(a, 1), "tsb": round(s, 1)}
            for d, _, c, a, s in series
        ],
        "volume": [
            {
                "week_start": k[0],
                "sport": k[1],
                "hours": round(v[0], 2),
                "distance_km": round(v[1], 1),
            }
            for k, v in sorted(weekly.items())
        ],
        "refreshed_at": None,
    }


if __name__ == "__main__":
    from ironman import db

    with db.conn() as c:
        print("seeded days of metrics:", seed(c))
