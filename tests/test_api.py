import fakeredis
import pyotp
import pytest
from conftest import make_fit, utc
from fastapi.testclient import TestClient

from ironman import auth, ingest

PW = "correct horse battery staple"


@pytest.fixture
def client(conn, monkeypatch):
    r = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(auth, "get_redis", lambda: r)
    from ironman.api import app

    return TestClient(app)


@pytest.fixture
def owner(client):
    uri = client.post("/api/auth/setup", json={"password": PW}).json()["totp_uri"]
    secret = pyotp.parse_uri(uri).secret
    r = client.post("/api/auth/login", json={"password": PW, "totp": pyotp.TOTP(secret).now()})
    assert r.status_code == 200
    return client, secret


def test_private_endpoints_require_auth(client):
    for path in ["/api/workouts", "/api/metrics/fitness", "/api/thresholds", "/api/share-links"]:
        assert client.get(path).status_code == 401


def test_login_without_totp_denied(client):
    client.post("/api/auth/setup", json={"password": PW})
    assert client.post("/api/auth/login", json={"password": PW}).status_code == 401
    assert (
        client.post("/api/auth/login", json={"password": PW, "totp": "000000"}).status_code == 401
    )
    assert client.get("/api/workouts").status_code == 401


def test_wrong_password_denied(client):
    uri = client.post("/api/auth/setup", json={"password": PW}).json()["totp_uri"]
    code = pyotp.TOTP(pyotp.parse_uri(uri).secret).now()
    assert (
        client.post("/api/auth/login", json={"password": "x" * 20, "totp": code}).status_code == 401
    )


def test_setup_only_once_and_weak_password(client):
    assert client.post("/api/auth/setup", json={"password": "short"}).status_code == 422
    assert client.post("/api/auth/setup", json={"password": PW}).status_code == 200
    assert client.post("/api/auth/setup", json={"password": PW}).status_code == 409


def test_owner_can_read_and_logout(owner):
    c, _ = owner
    assert c.get("/api/workouts").status_code == 200
    c.post("/api/auth/logout")
    assert c.get("/api/workouts").status_code == 401


def test_share_link_lifecycle(owner):
    c, _ = owner
    link = c.post("/api/share-links", json={"scope": ["metrics"], "days": 7}).json()
    c.cookies.clear()
    h = {"Authorization": f"Bearer {link['token']}"}
    assert c.get("/api/metrics/fitness", headers=h).status_code == 200
    assert c.get("/api/workouts", headers=h).status_code == 403  # outside scope
    assert (
        c.put("/api/goal", headers=h, json={"name": "x", "race_date": "2027-01-01"}).status_code
        == 403
    )
    assert c.post("/api/share-links", headers=h, json={"scope": ["metrics"]}).status_code == 403
    assert (
        c.get(
            "/api/metrics/fitness", headers={"Authorization": "Bearer " + link["token"][:-2] + "xx"}
        ).status_code
        == 401
    )


def test_revoked_and_expired_links_denied(owner, conn):
    c, _ = owner
    link = c.post("/api/share-links", json={"scope": ["metrics"]}).json()
    expired = c.post("/api/share-links", json={"scope": ["metrics"]}).json()
    conn.execute(
        "UPDATE private.share_links SET expires_at = now() - interval '1 day' WHERE id=%s",
        (expired["id"],),
    )
    conn.commit()
    h = {"Authorization": f"Bearer {link['token']}"}
    hx = {"Authorization": f"Bearer {expired['token']}"}
    cookies = dict(c.cookies)
    c.cookies.clear()
    assert c.get("/api/metrics/fitness", headers=h).status_code == 200
    assert c.get("/api/metrics/fitness", headers=hx).status_code == 401
    assert c.delete(f"/api/share-links/{link['id']}", cookies=cookies).status_code == 200
    assert c.get("/api/metrics/fitness", headers=h).status_code == 401


def test_link_use_and_creation_audited(owner, conn):
    c, _ = owner
    link = c.post("/api/share-links", json={"scope": ["metrics"]}).json()
    c.cookies.clear()
    c.get("/api/metrics/fitness", headers={"Authorization": f"Bearer {link['token']}"})
    events = [r["event"] for r in conn.execute("SELECT event FROM private.audit_log")]
    assert "link_created" in events and "link_used" in events and "login_ok" in events


def test_invalid_scope_rejected(owner):
    c, _ = owner
    assert c.post("/api/share-links", json={"scope": ["everything"]}).status_code == 422


def test_upload_fit_and_corrupt(owner):
    c, _ = owner
    ok = c.post("/api/workouts/upload", files={"file": ("a.fit", make_fit(utc(2026, 5, 1, 6)))})
    assert ok.status_code == 200 and ok.json()["outcome"] == "created"
    bad = c.post("/api/workouts/upload", files={"file": ("b.fit", b"garbage")})
    assert bad.status_code == 422 and "cannot parse FIT" in bad.json()["detail"]
    assert c.post("/api/workouts/upload", files={"file": ("c.txt", b"x")}).status_code == 422


def test_webhook_verification(client):
    ok = client.get(
        "/api/strava/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "ironman-verify",
            "hub.challenge": "abc",
        },
    )
    assert ok.json() == {"hub.challenge": "abc"}
    bad = client.get(
        "/api/strava/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "abc"},
    )
    assert bad.status_code == 403


def test_webhook_unknown_owner_rejected(client, conn):
    assert (
        client.post(
            "/api/strava/webhook", json={"owner_id": 1, "object_type": "activity"}
        ).status_code
        == 403
    )


def test_webhook_enqueues_for_known_athlete(client, conn, monkeypatch):
    from ironman import jobs, security

    conn.execute(
        "INSERT INTO private.strava_tokens VALUES (1, 42, %s, %s, now())",
        (security.encrypt("a"), security.encrypt("b")),
    )
    conn.commit()
    seen = []
    monkeypatch.setattr(jobs, "enqueue_activity", lambda i, q=None: seen.append(i))
    ev = {"owner_id": 42, "object_type": "activity", "aspect_type": "create", "object_id": 99}
    assert client.post("/api/strava/webhook", json=ev).status_code == 200
    client.post("/api/strava/webhook", json=ev)  # duplicate delivery just re-enqueues same job id
    assert seen == [99, 99]


def test_thresholds_rescore_workouts(owner, conn):
    c, _ = owner
    ingest.store_workout(
        conn, ingest.Workout("strava", "1", "bike", utc(2026, 5, 1, 6), 3600, avg_power=250.0)
    )
    conn.commit()
    r = c.put("/api/thresholds", json={"effective_from": "2026-01-01", "ftp": 250})
    assert r.status_code == 200
    w = c.get("/api/workouts").json()[0]
    assert w["tss"] == pytest.approx(100) and w["tss_method"] == "power"
