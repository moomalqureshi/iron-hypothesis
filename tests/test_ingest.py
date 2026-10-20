import pytest
from conftest import make_fit, utc

from ironman import ingest

GPX = b"""<?xml version="1.0"?><gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">
<trk><type>running</type><trkseg>
<trkpt lat="52.0" lon="13.0"><ele>30</ele><time>2026-05-01T06:00:00Z</time></trkpt>
<trkpt lat="52.001" lon="13.0"><ele>32</ele><time>2026-05-01T06:00:30Z</time></trkpt>
<trkpt lat="52.002" lon="13.0"><ele>31</ele><time>2026-05-01T06:01:00Z</time></trkpt>
</trkseg></trk></gpx>"""


def test_parse_fit_valid():
    w = ingest.parse_fit(make_fit(utc(2026, 5, 1, 6), seconds=120))
    assert w.sport == "bike" and w.duration_s == 120
    assert w.start_time == utc(2026, 5, 1, 6)
    assert len(w.samples) == 120 and w.avg_power == pytest.approx(200)


def test_parse_fit_corrupt_names_problem():
    with pytest.raises(ingest.ParseError, match="cannot parse FIT"):
        ingest.parse_fit(b"not a fit file at all", "bad.fit")


def test_parse_gpx():
    w = ingest.parse_gpx(GPX)
    assert w.sport == "run" and w.duration_s == 60 and w.distance_m > 200


def test_parse_gpx_corrupt():
    with pytest.raises(ingest.ParseError):
        ingest.parse_gpx(b"<gpx", "bad.gpx")


def _w(**kw):
    base = dict(
        source="strava", source_id="1", sport="bike", start_time=utc(2026, 5, 1, 6), duration_s=3600
    )
    return ingest.Workout(**{**base, **kw})


def test_duplicate_webhook_delivery(conn):
    a = ingest.store_workout(conn, _w())
    b = ingest.store_workout(conn, _w())
    assert a[1] == "created" and b[1] == "duplicate" and a[0] == b[0]
    assert conn.execute("SELECT count(*) AS n FROM private.workouts").fetchone()["n"] == 1


def test_cross_source_merge_keeps_richer_data(conn):
    ingest.store_workout(conn, _w(avg_power=None))
    fit = _w(
        source="fit",
        source_id=None,
        start_time=utc(2026, 5, 1, 6, 0, 30),
        duration_s=3610,
        avg_power=210.0,
        samples=[
            {
                "ts": utc(2026, 5, 1, 6),
                "hr": 1,
                "power": 2,
                "speed": 3,
                "cadence": 4,
                "altitude": 5,
                "lat": None,
                "lon": None,
            }
        ],
    )
    _, outcome = ingest.store_workout(conn, fit)
    assert outcome == "merged"
    row = conn.execute("SELECT * FROM private.workouts").fetchone()
    assert row["avg_power"] == 210.0 and row["has_samples"]
    assert conn.execute("SELECT count(*) AS n FROM private.workouts").fetchone()["n"] == 1


def test_different_workouts_not_merged(conn):
    ingest.store_workout(conn, _w())
    _, o = ingest.store_workout(conn, _w(source_id="2", start_time=utc(2026, 5, 1, 18)))
    assert o == "created"


def test_normalized_power_needs_30s():
    assert ingest.normalized_power([100.0] * 10) is None
    assert ingest.normalized_power([200.0] * 60) == pytest.approx(200)
