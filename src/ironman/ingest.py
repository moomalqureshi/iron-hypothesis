"""Workout storage with cross-source de-duplication, and FIT/GPX parsing."""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime

import fitparse
import gpxpy

SPORT_MAP = {
    "swimming": "swim",
    "swim": "swim",
    "openwaterswim": "swim",
    "lap_swimming": "swim",
    "cycling": "bike",
    "ride": "bike",
    "virtualride": "bike",
    "bike": "bike",
    "ebikeride": "bike",
    "gravelride": "bike",
    "mountainbikeride": "bike",
    "running": "run",
    "run": "run",
    "trailrun": "run",
    "virtualrun": "run",
}


def norm_sport(s: str | None) -> str:
    return SPORT_MAP.get((s or "").replace(" ", "").lower(), "other")


class ParseError(ValueError):
    pass


@dataclass
class Workout:
    source: str
    source_id: str | None
    sport: str
    start_time: datetime
    duration_s: int
    distance_m: float | None = None
    avg_hr: float | None = None
    max_hr: float | None = None
    avg_power: float | None = None
    np_power: float | None = None
    avg_speed: float | None = None
    elevation_gain_m: float | None = None
    samples: list[dict] = field(default_factory=list)


def normalized_power(powers: list[float]) -> float | None:
    """30 s rolling mean, ^4, mean, ^(1/4). Samples are assumed ~1 Hz."""
    if len(powers) < 30:
        return None
    window = sum(powers[:30])
    rolled = [window / 30]
    for i in range(30, len(powers)):
        window += powers[i] - powers[i - 30]
        rolled.append(window / 30)
    return (sum(p**4 for p in rolled) / len(rolled)) ** 0.25


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def parse_fit(data: bytes, filename: str = "upload.fit") -> Workout:
    try:
        ff = fitparse.FitFile(io.BytesIO(data))
        records = [{d.name: d.value for d in m} for m in ff.get_messages("record")]
        sessions = [{d.name: d.value for d in m} for m in ff.get_messages("session")]
    except Exception as e:  # fitparse raises several error types
        raise ParseError(f"cannot parse FIT file {filename}: {e}") from e
    if not sessions and not records:
        raise ParseError(f"FIT file {filename} contains no activity data")
    s = sessions[0] if sessions else {}
    start = s.get("start_time") or next(
        (r["timestamp"] for r in records if r.get("timestamp")), None
    )
    if start is None:
        raise ParseError(f"FIT file {filename} has no start time")
    start = start.replace(tzinfo=UTC)
    duration = s.get("total_timer_time") or s.get("total_elapsed_time")
    if not duration and len(records) > 1:
        duration = (records[-1]["timestamp"] - records[0]["timestamp"]).total_seconds()
    if not duration:
        raise ParseError(f"FIT file {filename} has no duration")
    semi = 180 / 2**31
    samples = []
    for r in records:
        if not r.get("timestamp"):
            continue
        lat, lon = r.get("position_lat"), r.get("position_long")
        samples.append(
            {
                "ts": r["timestamp"].replace(tzinfo=UTC),
                "hr": r.get("heart_rate"),
                "power": r.get("power"),
                "speed": r.get("enhanced_speed") or r.get("speed"),
                "cadence": r.get("cadence"),
                "altitude": r.get("enhanced_altitude") or r.get("altitude"),
                "lat": lat * semi if lat is not None else None,
                "lon": lon * semi if lon is not None else None,
            }
        )
    powers = [p["power"] for p in samples if p["power"] is not None]
    hrs = [p["hr"] for p in samples if p["hr"] is not None]
    return Workout(
        source="fit",
        source_id=None,
        sport=norm_sport(str(s.get("sport", ""))),
        start_time=start,
        duration_s=int(duration),
        distance_m=s.get("total_distance"),
        avg_hr=s.get("avg_heart_rate") or _mean(hrs),
        max_hr=s.get("max_heart_rate"),
        avg_power=s.get("avg_power") or _mean(powers),
        np_power=normalized_power(powers),
        avg_speed=s.get("enhanced_avg_speed") or s.get("avg_speed"),
        elevation_gain_m=s.get("total_ascent"),
        samples=samples,
    )


def parse_gpx(data: bytes, filename: str = "upload.gpx", sport: str = "other") -> Workout:
    try:
        g = gpxpy.parse(io.BytesIO(data))
    except Exception as e:
        raise ParseError(f"cannot parse GPX file {filename}: {e}") from e
    pts = [p for t in g.tracks for seg in t.segments for p in seg.points if p.time]
    if len(pts) < 2:
        raise ParseError(f"GPX file {filename} has fewer than two timed points")
    for p in pts:
        if p.time.tzinfo is None:
            p.time = p.time.replace(tzinfo=UTC)
    dist = sum(a.distance_2d(b) or 0 for a, b in zip(pts, pts[1:], strict=False))
    dur = (pts[-1].time - pts[0].time).total_seconds()
    ascent = sum(
        max((b.elevation or 0) - (a.elevation or 0), 0) for a, b in zip(pts, pts[1:], strict=False)
    )
    typ = norm_sport(g.tracks[0].type) if g.tracks and g.tracks[0].type else sport
    samples = [
        {
            "ts": p.time,
            "hr": None,
            "power": None,
            "speed": None,
            "cadence": None,
            "altitude": p.elevation,
            "lat": p.latitude,
            "lon": p.longitude,
        }
        for p in pts
    ]
    return Workout(
        source="gpx",
        source_id=None,
        sport=typ,
        start_time=pts[0].time,
        duration_s=int(dur),
        distance_m=dist,
        avg_speed=dist / dur if dur else None,
        elevation_gain_m=ascent,
        samples=samples,
    )


def _same_workout(a_start, a_dur, b_start, b_dur) -> bool:
    return abs((a_start - b_start).total_seconds()) <= 120 and math.isclose(
        a_dur, b_dur, rel_tol=0.05, abs_tol=60
    )


_FIELDS = [
    "distance_m",
    "avg_hr",
    "max_hr",
    "avg_power",
    "np_power",
    "avg_speed",
    "elevation_gain_m",
]


def store_workout(conn, w: Workout) -> tuple[str, str]:
    """Insert a workout once. Returns (workout_id, 'created'|'duplicate'|'merged')."""
    if w.source_id is not None:
        row = conn.execute(
            "SELECT id FROM private.workouts WHERE source=%s AND source_id=%s",
            (w.source, w.source_id),
        ).fetchone()
        if row:
            return str(row["id"]), "duplicate"
    cands = conn.execute(
        "SELECT * FROM private.workouts WHERE sport=%s AND start_time BETWEEN "
        "%s - interval '2 minutes' AND %s + interval '2 minutes'",
        (w.sport, w.start_time, w.start_time),
    ).fetchall()
    for c in cands:
        if _same_workout(c["start_time"], c["duration_s"], w.start_time, w.duration_s):
            return _merge(conn, c, w)
    row = conn.execute(
        f"INSERT INTO private.workouts (source, source_id, sport, start_time, duration_s, "
        f"{', '.join(_FIELDS)}, has_samples) VALUES (%s,%s,%s,%s,%s,{', '.join(['%s'] * len(_FIELDS))},%s) "
        "RETURNING id",
        (
            w.source,
            w.source_id,
            w.sport,
            w.start_time,
            w.duration_s,
            *[getattr(w, f) for f in _FIELDS],
            bool(w.samples),
        ),
    ).fetchone()
    _store_samples(conn, row["id"], w.samples)
    return str(row["id"]), "created"


def _merge(conn, existing: dict, w: Workout) -> tuple[str, str]:
    """Keep the richer record: add missing summary fields, and samples if it has none."""
    updates = {
        f: getattr(w, f) for f in _FIELDS if existing[f] is None and getattr(w, f) is not None
    }
    added_samples = bool(w.samples) and not existing["has_samples"]
    if added_samples:
        updates["has_samples"] = True
    if not updates:
        return str(existing["id"]), "duplicate"
    sets = ", ".join(f"{k}=%s" for k in updates)
    conn.execute(
        f"UPDATE private.workouts SET {sets} WHERE id=%s", (*updates.values(), existing["id"])
    )
    if added_samples:
        _store_samples(conn, existing["id"], w.samples)
    return str(existing["id"]), "merged"


def _store_samples(conn, workout_id, samples: list[dict]) -> None:
    if not samples:
        return
    with conn.cursor().copy(
        "COPY private.workout_samples (workout_id, ts, hr, power, speed, cadence, altitude, lat, lon) "
        "FROM STDIN"
    ) as cp:
        for s in samples:
            cp.write_row(
                (
                    workout_id,
                    s["ts"],
                    s["hr"],
                    s["power"],
                    s["speed"],
                    s["cadence"],
                    s["altitude"],
                    s["lat"],
                    s["lon"],
                )
            )
