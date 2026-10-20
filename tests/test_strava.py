from datetime import UTC, datetime, timedelta

import httpx
import pytest
from conftest import utc

from ironman import security, strava


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _seed_tokens(conn, expires_in):
    conn.execute(
        "INSERT INTO private.strava_tokens VALUES (1, 42, %s, %s, %s)",
        (
            security.encrypt("old-access"),
            security.encrypt("refresh-1"),
            datetime.now(UTC) + expires_in,
        ),
    )


def test_tokens_stored_encrypted(conn):
    data = {
        "access_token": "acc",
        "refresh_token": "ref",
        "expires_at": 4102444800,
        "athlete": {"id": 42},
    }
    strava._save_tokens(conn, data)
    row = conn.execute("SELECT * FROM private.strava_tokens").fetchone()
    assert (
        "acc" not in row["access_token_enc"] and security.decrypt(row["access_token_enc"]) == "acc"
    )


def test_expired_token_refreshed(conn):
    _seed_tokens(conn, timedelta(minutes=-1))
    calls = []

    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(
            200,
            json={
                "access_token": "new",
                "refresh_token": "ref-2",
                "expires_at": int((datetime.now(UTC) + timedelta(hours=6)).timestamp()),
            },
        )

    assert strava.access_token(conn, _client(handler)) == "new"
    assert calls == ["/oauth/token"]
    row = conn.execute("SELECT * FROM private.strava_tokens").fetchone()
    assert security.decrypt(row["refresh_token_enc"]) == "ref-2" and row["athlete_id"] == 42


def test_valid_token_not_refreshed(conn):
    _seed_tokens(conn, timedelta(hours=1))
    assert (
        strava.access_token(conn, _client(lambda r: pytest.fail("no call expected")))
        == "old-access"
    )


def test_not_connected(conn):
    with pytest.raises(strava.StravaNotConnected):
        strava.access_token(conn)


def test_rate_limit_raised(conn):
    _seed_tokens(conn, timedelta(hours=1))
    with pytest.raises(strava.StravaRateLimited):
        strava.fetch_activity(conn, 1, _client(lambda r: httpx.Response(429)))


def test_fetch_activity_maps_summary_and_streams(conn):
    _seed_tokens(conn, timedelta(hours=1))
    act = {
        "id": 7,
        "sport_type": "Ride",
        "start_date": "2026-05-01T06:00:00Z",
        "moving_time": 3,
        "distance": 20.0,
        "average_watts": 200,
        "weighted_average_watts": 210,
        "average_heartrate": 140,
    }
    streams = {
        "time": {"data": [0, 1, 2]},
        "heartrate": {"data": [130, 140, 150]},
        "watts": {"data": [190, 200, 210]},
    }

    def handler(req):
        return httpx.Response(200, json=streams if req.url.path.endswith("streams") else act)

    w = strava.fetch_activity(conn, 7, _client(handler))
    assert (w.source, w.source_id, w.sport) == ("strava", "7", "bike")
    assert w.start_time == utc(2026, 5, 1, 6) and w.np_power == 210
    assert [s["hr"] for s in w.samples] == [130, 140, 150]


def test_manual_activity_without_streams(conn):
    _seed_tokens(conn, timedelta(hours=1))
    act = {"id": 8, "type": "Run", "start_date": "2026-05-01T06:00:00Z", "elapsed_time": 600}

    def handler(req):
        return (
            httpx.Response(404)
            if req.url.path.endswith("streams")
            else httpx.Response(200, json=act)
        )

    w = strava.fetch_activity(conn, 8, _client(handler))
    assert w.samples == [] and w.sport == "run"


def test_list_activity_ids_paginates(conn):
    _seed_tokens(conn, timedelta(hours=1))

    def handler(req):
        page = int(req.url.params["page"])
        n = 100 if page == 1 else 3
        return httpx.Response(200, json=[{"id": page * 1000 + i} for i in range(n)])

    assert len(strava.list_activity_ids(conn, None, _client(handler))) == 103
