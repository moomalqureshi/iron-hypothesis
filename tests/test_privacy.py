"""Privacy regression tests: these must fail the build if public output leaks."""

import fakeredis
import psycopg
import pytest
from conftest import TEST_URL, utc
from fastapi.testclient import TestClient

from ironman import auth, demo, ingest, metrics, sanitize

PUBLIC_URL = TEST_URL.replace("ironman:ironman@", "ironman_public:ironman_public@")
SENSITIVE = ["owner@example.com", "Jane Athlete", "52.5200", "13.4050"]


def _seed(conn):
    conn.execute(
        "INSERT INTO private.identity (name, email, password_hash, birth_year) "
        "VALUES ('Jane Athlete','owner@example.com','x',1990)"
    )
    conn.execute(
        "INSERT INTO private.race_goal VALUES (1,'Ironman Secret City','2099-07-01',9000,80)"
    )
    conn.execute(
        "INSERT INTO private.thresholds (effective_from, ftp, max_hr) VALUES ('2000-01-01',250,190)"
    )
    samples = [
        {
            "ts": utc(2026, 5, 1, 6, 17, 33),
            "hr": 150,
            "power": 200,
            "speed": 8,
            "cadence": 80,
            "altitude": 30,
            "lat": 52.52001,
            "lon": 13.40501,
        }
    ]
    ingest.store_workout(
        conn,
        ingest.Workout(
            "strava",
            "1",
            "bike",
            utc(2026, 5, 1, 6, 17, 33),
            3671,
            distance_m=40123.4,
            avg_hr=151.3,
            avg_power=210.0,
            samples=samples,
        ),
    )
    ingest.store_workout(
        conn,
        ingest.Workout(
            "strava", "2", "run", utc(2026, 5, 2, 7), 3000, distance_m=10000.0, avg_hr=160.0
        ),
    )
    metrics.score_workouts(conn)
    metrics.recompute_from(conn)
    sanitize.seed_reference_synthetic(conn)
    conn.commit()


def _dump_public(conn) -> str:
    out = []
    for t in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public_data'"
    ):
        for r in conn.execute(f"SELECT * FROM public_data.{t['table_name']}").fetchall():
            out.append(str(r))
    return "\n".join(out)


def test_no_identity_or_coordinates_in_public_tables(conn):
    _seed(conn)
    sanitize.run(conn)
    dump = _dump_public(conn)
    for s in SENSITIVE + ["Ironman Secret City", "2099-07-01", "strava", "lat", "lon"]:
        assert s not in dump, f"public data leaked {s!r}"


def test_public_columns_have_no_gps_or_exact_time(conn):
    cols = conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='public_data'"
    ).fetchall()
    for c in cols:
        assert c["column_name"] not in {
            "lat",
            "lon",
            "latitude",
            "longitude",
            "email",
            "name",
            "start_time",
        }
        assert "timestamp" not in c["data_type"] or c["column_name"] == "refreshed_at"


def test_day_level_dates_and_coarsened_values(conn):
    _seed(conn)
    sanitize.run(conn)
    w = conn.execute("SELECT * FROM public_data.workouts WHERE sport='bike'").fetchone()
    assert str(w["day"]) == "2026-05-01"
    assert w["duration_min"] % 5 == 0 and w["distance_km"] == 40.1
    assert (
        conn.execute("SELECT age_bracket FROM public_data.athlete").fetchone()["age_bracket"]
        == "35-39"
    )


def test_pseudonym_does_not_join_back(conn):
    _seed(conn)
    sanitize.run(conn)
    p = conn.execute("SELECT pseudonym FROM public_data.athlete").fetchone()["pseudonym"]
    assert p.startswith("ath_") and "owner" not in p and "1" != p


def test_hr_hidden_when_requested(conn):
    _seed(conn)
    sanitize.run(conn, hide_hr=True)
    assert all(r["avg_hr"] is None for r in conn.execute("SELECT avg_hr FROM public_data.workouts"))
    sanitize.run(conn, hide_hr=False)
    assert any(
        r["avg_hr"] is not None for r in conn.execute("SELECT avg_hr FROM public_data.workouts")
    )


def test_deletion_propagates(conn):
    _seed(conn)
    sanitize.run(conn)
    conn.execute("DELETE FROM private.workouts WHERE source_id='2'")
    sanitize.run(conn)
    assert conn.execute("SELECT count(*) AS n FROM public_data.workouts").fetchone()["n"] == 1


def test_public_role_cannot_read_any_private_table(conn):
    _seed(conn)
    tables = [
        r["table_name"]
        for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='private'"
        )
    ]
    assert tables
    for t in tables:
        with psycopg.connect(PUBLIC_URL, autocommit=True) as pc:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                pc.execute(f"SELECT * FROM private.{t}")


def test_public_role_cannot_write_public_data():
    with psycopg.connect(PUBLIC_URL, autocommit=True) as pc:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            pc.execute("DELETE FROM public_data.workouts")


@pytest.fixture
def pub(monkeypatch, conn):
    r = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(auth, "get_redis", lambda: r)
    monkeypatch.setenv("IRONMAN_PUBLIC_DATABASE_URL", PUBLIC_URL)
    from ironman import config

    config.get_settings.cache_clear()
    from ironman.public_api import app

    yield TestClient(app)
    config.get_settings.cache_clear()


def test_public_api_serves_sanitized_data_without_login(conn, pub):
    _seed(conn)
    sanitize.run(conn)
    conn.commit()
    r = pub.get("/public/api/dashboard")
    assert r.status_code == 200
    body = r.text
    for s in SENSITIVE + ["Ironman Secret City"]:
        assert s not in body
    j = r.json()
    assert (
        j["disclaimer"]
        and j["refreshed_at"]
        and j["fitness"]
        and {p["metric"] for p in j["percentiles"]}
    )


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_public_api_rejects_writes(pub, method):
    assert getattr(pub, method)("/public/api/dashboard").status_code == 405


def test_public_api_cannot_see_private_paths(pub):
    assert pub.get("/api/workouts").status_code == 404
    assert pub.get("/api/thresholds").status_code == 404


def test_public_rate_limit(pub, monkeypatch):
    from ironman import config

    monkeypatch.setenv("IRONMAN_PUBLIC_RATE_LIMIT_PER_MIN", "3")
    config.get_settings.cache_clear()
    codes = [pub.get("/public/api/demo").status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]


def test_demo_mode_is_synthetic_and_db_free(pub, monkeypatch):
    monkeypatch.setenv("IRONMAN_PUBLIC_DATABASE_URL", "postgresql://nobody:x@127.0.0.1:1/none")
    from ironman import config

    config.get_settings.cache_clear()
    j = pub.get("/public/api/demo").json()
    assert j["demo"] is True and "demo" in j["label"] and j["fitness"] and j["volume"]


def test_demo_is_deterministic():
    assert demo.public_demo_payload() == demo.public_demo_payload()


def test_percentile_interpolation():
    ref = [(25, 2.0), (50, 4.0), (75, 8.0)]
    assert sanitize.percentile_of(3.0, ref) == 37.5
    assert sanitize.percentile_of(0.1, ref) == 25 and sanitize.percentile_of(99, ref) == 75


def test_age_bracket():
    from datetime import date

    assert (
        sanitize.age_bracket(1990, date(2026, 1, 1)) == "35-39"
        and sanitize.age_bracket(None) is None
    )
