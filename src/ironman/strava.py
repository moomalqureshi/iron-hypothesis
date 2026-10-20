"""Strava OAuth, activity fetch and sync. Network calls go through httpx so tests can mock them."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx

from ironman import security
from ironman.config import get_settings
from ironman.ingest import Workout, norm_sport

API = "https://www.strava.com/api/v3"
OAUTH = "https://www.strava.com/oauth"


class StravaRateLimited(Exception):
    def __init__(self, retry_after: int = 900):
        super().__init__("Strava rate limit reached")
        self.retry_after = retry_after


class StravaNotConnected(Exception):
    pass


def authorize_url() -> str:
    s = get_settings()
    q = {
        "client_id": s.strava_client_id,
        "redirect_uri": s.strava_redirect_uri,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": "read,activity:read_all",
    }
    return f"{OAUTH}/authorize?{urlencode(q)}"


def _save_tokens(conn, data: dict, athlete_id: int | None = None) -> None:
    row = conn.execute("SELECT athlete_id FROM private.strava_tokens").fetchone()
    athlete = athlete_id or (row["athlete_id"] if row else (data.get("athlete") or {}).get("id"))
    conn.execute(
        "INSERT INTO private.strava_tokens (athlete_id, access_token_enc, refresh_token_enc, expires_at) "
        "VALUES (%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET athlete_id=EXCLUDED.athlete_id, "
        "access_token_enc=EXCLUDED.access_token_enc, refresh_token_enc=EXCLUDED.refresh_token_enc, "
        "expires_at=EXCLUDED.expires_at",
        (
            athlete,
            security.encrypt(data["access_token"]),
            security.encrypt(data["refresh_token"]),
            datetime.fromtimestamp(data["expires_at"], UTC),
        ),
    )


def exchange_code(conn, code: str, client: httpx.Client | None = None) -> None:
    s = get_settings()
    c = client or httpx.Client(timeout=30)
    r = c.post(
        f"{OAUTH}/token",
        data={
            "client_id": s.strava_client_id,
            "client_secret": s.strava_client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
    )
    r.raise_for_status()
    _save_tokens(conn, r.json())


def access_token(conn, client: httpx.Client | None = None) -> str:
    """Return a valid access token, refreshing it when it expires within 5 minutes."""
    row = conn.execute("SELECT * FROM private.strava_tokens").fetchone()
    if not row:
        raise StravaNotConnected("Strava is not connected")
    if row["expires_at"] - datetime.now(UTC) > timedelta(minutes=5):
        return security.decrypt(row["access_token_enc"])
    s = get_settings()
    c = client or httpx.Client(timeout=30)
    r = c.post(
        f"{OAUTH}/token",
        data={
            "client_id": s.strava_client_id,
            "client_secret": s.strava_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": security.decrypt(row["refresh_token_enc"]),
        },
    )
    r.raise_for_status()
    _save_tokens(conn, r.json(), row["athlete_id"])
    return r.json()["access_token"]


def _get(client: httpx.Client, token: str, path: str, params: dict | None = None):
    r = client.get(f"{API}{path}", params=params, headers={"Authorization": f"Bearer {token}"})
    if r.status_code == 429:
        raise StravaRateLimited()
    r.raise_for_status()
    return r.json()


def to_workout(a: dict, streams: dict | None = None) -> Workout:
    start = datetime.fromisoformat(a["start_date"].replace("Z", "+00:00"))
    samples = []
    if streams and "time" in streams:
        times = streams["time"]["data"]

        def col(name):
            d = streams.get(name, {}).get("data")
            return d if d and len(d) == len(times) else [None] * len(times)

        hr, pw, vel, cad, alt = (
            col(n) for n in ("heartrate", "watts", "velocity_smooth", "cadence", "altitude")
        )
        ll = streams.get("latlng", {}).get("data")
        ll = ll if ll and len(ll) == len(times) else [[None, None]] * len(times)
        for i, t in enumerate(times):
            samples.append(
                {
                    "ts": start + timedelta(seconds=t),
                    "hr": hr[i],
                    "power": pw[i],
                    "speed": vel[i],
                    "cadence": cad[i],
                    "altitude": alt[i],
                    "lat": ll[i][0],
                    "lon": ll[i][1],
                }
            )
    return Workout(
        source="strava",
        source_id=str(a["id"]),
        sport=norm_sport(a.get("sport_type") or a.get("type")),
        start_time=start,
        duration_s=int(a.get("moving_time") or a.get("elapsed_time") or 0),
        distance_m=a.get("distance"),
        avg_hr=a.get("average_heartrate"),
        max_hr=a.get("max_heartrate"),
        avg_power=a.get("average_watts"),
        np_power=a.get("weighted_average_watts"),
        avg_speed=a.get("average_speed"),
        elevation_gain_m=a.get("total_elevation_gain"),
        samples=samples,
    )


def fetch_activity(conn, activity_id: int, client: httpx.Client | None = None) -> Workout:
    c = client or httpx.Client(timeout=30)
    token = access_token(conn, c)
    a = _get(c, token, f"/activities/{activity_id}")
    keys = "time,heartrate,watts,velocity_smooth,cadence,altitude,latlng"
    try:
        streams = _get(
            c, token, f"/activities/{activity_id}/streams", {"keys": keys, "key_by_type": "true"}
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 404:  # manual activities have no streams
            raise
        streams = None
    return to_workout(a, streams)


def list_activity_ids(
    conn, after: datetime | None, client: httpx.Client | None = None
) -> list[int]:
    c = client or httpx.Client(timeout=30)
    token = access_token(conn, c)
    ids: list[int] = []
    page = 1
    while True:
        params = {"per_page": 100, "page": page}
        if after:
            params["after"] = int(after.timestamp())
        batch = _get(c, token, "/athlete/activities", params)
        ids += [a["id"] for a in batch]
        if len(batch) < 100:
            return ids
        page += 1
