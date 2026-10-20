"""Rebuild public_data.* from private.* through an explicit column allowlist.

Full rebuild in one transaction so deletions propagate and readers never see a partial state."""

from __future__ import annotations

import bisect
from datetime import date

from ironman import db, metrics, security
from ironman.config import get_settings

# Reference distributions (p5..p95 step 5) used for percentile display. Real open-dataset
# values replace these via load_reference_csv; the seeded set is labelled synthetic.
SYNTHETIC_SOURCE = "synthetic-seed (replace with open-dataset values)"


def age_bracket(birth_year: int | None, today: date | None = None) -> str | None:
    if not birth_year:
        return None
    age = (today or date.today()).year - birth_year
    lo = age // 5 * 5
    return f"{lo}-{lo + 4}"


def percentile_of(value: float, ref: list[tuple[int, float]]) -> float:
    """Interpolated percentile of `value` in a reference [(pct, value)] table."""
    ref = sorted(ref)
    vals = [v for _, v in ref]
    if value <= vals[0]:
        return float(ref[0][0])
    if value >= vals[-1]:
        return float(ref[-1][0])
    i = bisect.bisect_left(vals, value)
    (p0, v0), (p1, v1) = ref[i - 1], ref[i]
    return round(p0 + (p1 - p0) * (value - v0) / (v1 - v0), 1) if v1 != v0 else float(p1)


def seed_reference_synthetic(conn) -> None:
    import statistics

    for metric, mu, sigma in (("weekly_hours", 6.0, 2.5), ("ctl", 45.0, 18.0)):
        nd = statistics.NormalDist(mu, sigma)
        for p in range(5, 100, 5):
            conn.execute(
                "INSERT INTO public_data.reference_population VALUES (%s,%s,%s,%s) "
                "ON CONFLICT DO NOTHING",
                (metric, p, max(nd.inv_cdf(p / 100), 0), SYNTHETIC_SOURCE),
            )


def load_reference_csv(conn, path: str, source: str) -> int:
    """CSV columns: metric,percentile,value. `source` records dataset and licence."""
    import csv

    n = 0
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            conn.execute(
                "INSERT INTO public_data.reference_population VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (metric, percentile) DO UPDATE SET value=EXCLUDED.value, source=EXCLUDED.source",
                (r["metric"], int(r["percentile"]), float(r["value"]), source),
            )
            n += 1
    return n


def run(conn, hide_hr: bool | None = None) -> dict:
    s = get_settings()
    ident = conn.execute("SELECT * FROM private.identity").fetchone()
    hide = (
        hide_hr
        if hide_hr is not None
        else (s.public_hide_hr or bool(ident and ident["hide_hr_public"]))
    )
    for t in (
        "workouts",
        "weekly_volume",
        "fitness_daily",
        "goal_progress",
        "percentiles",
        "athlete",
        "meta",
    ):
        conn.execute(f"DELETE FROM public_data.{t}")
    pseud = security.pseudonym("owner-1")
    conn.execute(
        "INSERT INTO public_data.athlete VALUES (%s,%s)",
        (pseud, age_bracket(ident["birth_year"]) if ident else None),
    )
    rows = conn.execute(
        "SELECT start_time::date AS day, sport, duration_s, distance_m, tss, avg_hr "
        "FROM private.workouts WHERE sport <> 'other'"
    ).fetchall()
    for r in rows:
        conn.execute(
            "INSERT INTO public_data.workouts VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                pseud,
                r["day"],
                r["sport"],
                round(r["duration_s"] / 60 / 5) * 5,
                round(r["distance_m"] / 1000, 1) if r["distance_m"] else None,
                round(r["tss"]) if r["tss"] is not None else None,
                None if hide or r["avg_hr"] is None else round(r["avg_hr"]),
            ),
        )
    for v in metrics.weekly_volume(conn):
        if v["sport"] != "other":
            conn.execute(
                "INSERT INTO public_data.weekly_volume VALUES (%s,%s,%s,%s)",
                (v["week_start"], v["sport"], round(v["hours"], 2), round(v["distance_km"], 1)),
            )
    for m in conn.execute("SELECT * FROM private.daily_metrics").fetchall():
        conn.execute(
            "INSERT INTO public_data.fitness_daily VALUES (%s,%s,%s,%s)",
            (m["day"], round(m["ctl"], 1), round(m["atl"], 1), round(m["tsb"], 1)),
        )
    g = metrics.goal_progress(conn)
    if g:  # race name and date are omitted; only relative progress is public
        conn.execute(
            "INSERT INTO public_data.goal_progress VALUES (1,%s,%s,%s,%s)",
            (
                g["weeks_remaining"],
                round(g["current_ctl"], 1),
                g["target_ctl"],
                g["percent_of_target"],
            ),
        )
    _percentiles(conn)
    conn.execute("INSERT INTO public_data.meta VALUES (1, now())")
    return {"workouts": len(rows)}


def _percentiles(conn) -> None:
    refs: dict[str, list[tuple[int, float]]] = {}
    src: dict[str, str] = {}
    for r in conn.execute("SELECT * FROM public_data.reference_population"):
        refs.setdefault(r["metric"], []).append((r["percentile"], r["value"]))
        src[r["metric"]] = r["source"]
    last8 = conn.execute(
        "SELECT coalesce(sum(hours),0)/8 AS h FROM public_data.weekly_volume "
        "WHERE week_start >= current_date - 56"
    ).fetchone()["h"]
    ctl = conn.execute(
        "SELECT ctl FROM public_data.fitness_daily ORDER BY day DESC LIMIT 1"
    ).fetchone()
    current = {"weekly_hours": last8, "ctl": ctl["ctl"] if ctl else None}
    for m, ref in refs.items():
        if current.get(m) is not None:
            conn.execute(
                "INSERT INTO public_data.percentiles VALUES (%s,%s,%s)",
                (m, percentile_of(current[m], ref), src[m]),
            )


if __name__ == "__main__":
    with db.conn() as c:
        seed_reference_synthetic(c)
        print(run(c))
