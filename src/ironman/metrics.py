"""Training stress and CTL/ATL/TSB. Pure functions plus DB recompute helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

CTL_DAYS = 42
ATL_DAYS = 7
REST_HR = 50.0


@dataclass
class Thresholds:
    ftp: float | None = None
    run_threshold_pace: float | None = None  # s/km
    swim_css: float | None = None  # s/100m
    max_hr: float | None = None
    lthr: float | None = None


@dataclass
class WorkoutLoad:
    sport: str
    duration_s: int
    distance_m: float | None = None
    avg_hr: float | None = None
    avg_power: float | None = None
    np_power: float | None = None


def compute_tss(w: WorkoutLoad, t: Thresholds) -> tuple[float | None, str | None]:
    """Return (tss, method). (None, None) when no usable signal exists."""
    hours = w.duration_s / 3600
    if w.sport == "bike" and t.ftp:
        power = w.np_power or w.avg_power
        if power:
            return hours * (power / t.ftp) ** 2 * 100, "power"
    if w.sport == "run" and t.run_threshold_pace and w.distance_m:
        pace = w.duration_s / (w.distance_m / 1000)
        return hours * (t.run_threshold_pace / pace) ** 2 * 100, "pace"
    if w.sport == "swim" and t.swim_css and w.distance_m:
        pace = w.duration_s / (w.distance_m / 100)
        return hours * (t.swim_css / pace) ** 3 * 100, "pace"
    if w.avg_hr:
        lthr = t.lthr or (t.max_hr * 0.88 if t.max_hr else None)
        if lthr and lthr > REST_HR:
            ratio = max(w.avg_hr - REST_HR, 0) / (lthr - REST_HR)
            return hours * ratio**2 * 100, "hr" if t.lthr else "hr-estimate"
    return None, None


def fitness_series(
    daily_tss: dict[date, float], start: date, end: date, ctl0: float = 0.0, atl0: float = 0.0
) -> list[tuple[date, float, float, float, float]]:
    """Daily (day, tss, ctl, atl, tsb). Rest days decay; TSB is the previous day's CTL - ATL."""
    out = []
    ctl, atl = ctl0, atl0
    day = start
    while day <= end:
        tss = daily_tss.get(day, 0.0)
        tsb = ctl - atl
        ctl += (tss - ctl) / CTL_DAYS
        atl += (tss - atl) / ATL_DAYS
        out.append((day, tss, ctl, atl, tsb))
        day += timedelta(days=1)
    return out


def thresholds_for(rows: list[dict], on: date) -> Thresholds:
    """Pick the threshold row in effect on `on` (latest effective_from <= on)."""
    eligible = [r for r in rows if r["effective_from"] <= on]
    if not eligible:
        return Thresholds()
    r = max(eligible, key=lambda r: r["effective_from"])
    return Thresholds(r["ftp"], r["run_threshold_pace"], r["swim_css"], r["max_hr"], r["lthr"])


def score_workouts(conn, since: date | None = None) -> int:
    """Compute TSS for workouts (all, or from `since`) using thresholds in effect that day."""
    rows = conn.execute("SELECT * FROM private.thresholds").fetchall()
    q = "SELECT * FROM private.workouts"
    args: tuple = ()
    if since:
        q += " WHERE start_time::date >= %s"
        args = (since,)
    n = 0
    for w in conn.execute(q, args).fetchall():
        t = thresholds_for(rows, w["start_time"].date())
        tss, method = compute_tss(
            WorkoutLoad(
                w["sport"],
                w["duration_s"],
                w["distance_m"],
                w["avg_hr"],
                w["avg_power"],
                w["np_power"],
            ),
            t,
        )
        flag = None if tss is not None else "no usable stress signal (set thresholds)"
        conn.execute(
            "UPDATE private.workouts SET tss=%s, tss_method=%s, flagged=%s WHERE id=%s",
            (tss, method, flag, w["id"]),
        )
        n += 1
    return n


def recompute_from(conn, from_day: date | None = None) -> int:
    """Recompute daily_metrics from `from_day` (or the beginning) through today."""
    first = conn.execute("SELECT min(start_time::date) AS d FROM private.workouts").fetchone()["d"]
    if first is None:
        return 0
    start = min(from_day, date.today()) if from_day else first
    start = max(start, first)
    ctl0 = atl0 = 0.0
    prev = conn.execute(
        "SELECT ctl, atl FROM private.daily_metrics WHERE day = %s", (start - timedelta(days=1),)
    ).fetchone()
    if prev:
        ctl0, atl0 = prev["ctl"], prev["atl"]
    elif start > first:  # no stored predecessor: rebuild from the beginning
        return recompute_from(conn, None)
    daily = {
        r["d"]: float(r["s"])
        for r in conn.execute(
            "SELECT start_time::date AS d, sum(coalesce(tss,0)) AS s FROM private.workouts "
            "WHERE start_time::date >= %s GROUP BY 1",
            (start,),
        )
    }
    series = fitness_series(daily, start, date.today(), ctl0, atl0)
    for day, tss, ctl, atl, tsb in series:
        conn.execute(
            "INSERT INTO private.daily_metrics VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (day) DO UPDATE SET tss=EXCLUDED.tss, ctl=EXCLUDED.ctl, "
            "atl=EXCLUDED.atl, tsb=EXCLUDED.tsb",
            (day, tss, ctl, atl, tsb),
        )
    return len(series)


def weekly_volume(conn, week_start: date | None = None) -> list[dict]:
    q = (
        "SELECT date_trunc('week', start_time)::date AS week_start, sport, "
        "(sum(duration_s)/3600.0)::float8 AS hours, (coalesce(sum(distance_m),0)/1000.0)::float8 AS distance_km, "
        "coalesce(sum(tss),0)::float8 AS tss FROM private.workouts "
    )
    args: tuple = ()
    if week_start:
        q += "WHERE date_trunc('week', start_time)::date = %s "
        args = (week_start,)
    q += "GROUP BY 1,2 ORDER BY 1,2"
    return conn.execute(q, args).fetchall()


def zone_bounds(kind: str, t: Thresholds) -> list[tuple[str, float, float]]:
    """Seven-zone (power) / five-zone (hr) bounds as fractions of the threshold."""
    if kind == "power" and t.ftp:
        edges = [0, 0.55, 0.75, 0.90, 1.05, 1.20, 1.50, 10]
        return [(f"Z{i + 1}", t.ftp * edges[i], t.ftp * edges[i + 1]) for i in range(7)]
    if kind == "hr" and (t.lthr or t.max_hr):
        lthr = t.lthr or t.max_hr * 0.88
        edges = [0, 0.85, 0.89, 0.94, 0.99, 10]
        return [(f"Z{i + 1}", lthr * edges[i], lthr * edges[i + 1]) for i in range(5)]
    return []


def time_in_zone(conn, workout_id, kind: str, t: Thresholds) -> dict[str, int]:
    """Seconds per zone from stored 1 Hz-ish samples (each sample counts as 1 s)."""
    col = {"power": "power", "hr": "hr"}[kind]
    zones = zone_bounds(kind, t)
    out = {z: 0 for z, _, _ in zones}
    for r in conn.execute(
        f"SELECT {col} AS v FROM private.workout_samples WHERE workout_id=%s AND {col} IS NOT NULL",
        (workout_id,),
    ):
        for z, lo, hi in zones:
            if lo <= r["v"] < hi:
                out[z] += 1
                break
    return out


def goal_progress(conn) -> dict | None:
    g = conn.execute("SELECT * FROM private.race_goal").fetchone()
    if not g:
        return None
    m = conn.execute("SELECT ctl FROM private.daily_metrics ORDER BY day DESC LIMIT 1").fetchone()
    ctl = m["ctl"] if m else 0.0
    weeks = max((g["race_date"] - date.today()).days // 7, 0)
    target = g["target_ctl"]
    return {
        "name": g["name"],
        "race_date": g["race_date"],
        "weeks_remaining": weeks,
        "current_ctl": ctl,
        "target_ctl": target,
        "percent_of_target": round(100 * ctl / target, 1) if target else None,
    }
