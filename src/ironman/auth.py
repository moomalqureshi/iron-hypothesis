"""Owner login (password + TOTP, Redis sessions), signed viewer share links, audit log."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import pyotp
import redis
from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, URLSafeSerializer

from ironman import db, security
from ironman.config import get_settings

SESSION_COOKIE = "ironman_session"
SCOPES = {"metrics", "workouts", "plans", "predictions"}


@lru_cache
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


@dataclass
class Principal:
    role: str  # owner | viewer
    scope: frozenset[str] = frozenset(SCOPES)
    link_id: str | None = None


def audit(conn, event: str, **detail) -> None:
    conn.execute(
        "INSERT INTO private.audit_log (event, detail) VALUES (%s, %s)", (event, json.dumps(detail))
    )


def setup_owner(conn, password: str) -> str:
    """One-time owner creation. Returns the TOTP provisioning URI."""
    if conn.execute("SELECT 1 FROM private.identity").fetchone():
        raise HTTPException(409, "owner already configured")
    if len(password) < 12:
        raise HTTPException(422, "password must be at least 12 characters")
    secret = pyotp.random_base32()
    conn.execute(
        "INSERT INTO private.identity (email, password_hash, totp_secret) VALUES (%s,%s,%s)",
        (get_settings().owner_email, security.hash_password(password), secret),
    )
    audit(conn, "owner_setup")
    return pyotp.TOTP(secret).provisioning_uri(get_settings().owner_email, issuer_name="Ironman")


def login(conn, password: str, code: str | None) -> str:
    """Create a session only when password AND a valid TOTP code are supplied."""
    ident = conn.execute("SELECT * FROM private.identity").fetchone()
    ok = bool(ident) and security.verify_password(password, ident["password_hash"])
    if ok and not (code and pyotp.TOTP(ident["totp_secret"]).verify(code, valid_window=1)):
        ok = False
    audit(conn, "login_ok" if ok else "login_failed")
    conn.commit()
    if not ok:
        raise HTTPException(401, "invalid credentials or second factor")
    if not ident["totp_confirmed"]:
        conn.execute("UPDATE private.identity SET totp_confirmed=true")
    sid = secrets.token_urlsafe(32)
    get_redis().setex(f"sess:{sid}", get_settings().session_ttl_s, "owner")
    return sid


def logout(sid: str | None) -> None:
    if sid:
        get_redis().delete(f"sess:{sid}")


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().secret_key, salt="share-link")


def create_link(conn, scope: list[str], days: int, label: str = "") -> dict:
    bad = set(scope) - SCOPES
    if bad or not scope:
        raise HTTPException(422, f"scope must be a non-empty subset of {sorted(SCOPES)}")
    exp = datetime.now(UTC) + timedelta(days=days)
    row = conn.execute(
        "INSERT INTO private.share_links (scope, label, expires_at) VALUES (%s,%s,%s) RETURNING id",
        (scope, label, exp),
    ).fetchone()
    lid = str(row["id"])
    audit(conn, "link_created", link_id=lid, scope=scope)
    return {
        "id": lid,
        "token": _serializer().dumps({"id": lid, "scope": sorted(scope)}),
        "expires_at": exp,
    }


def revoke_link(conn, link_id: str) -> None:
    n = conn.execute(
        "UPDATE private.share_links SET revoked_at=now() WHERE id=%s AND revoked_at IS NULL",
        (link_id,),
    ).rowcount
    if not n:
        raise HTTPException(404, "link not found or already revoked")
    audit(conn, "link_revoked", link_id=link_id)


def verify_link(token: str) -> Principal | None:
    try:
        data = _serializer().loads(token)
    except BadSignature:
        return None
    with db.conn() as c:
        row = c.execute("SELECT * FROM private.share_links WHERE id=%s", (data["id"],)).fetchone()
        if not row or row["revoked_at"] or row["expires_at"] < datetime.now(UTC):
            return None
        # Scope comes from the database row, not the token, so a tampered or stale claim
        # can never widen access.
        audit(c, "link_used", link_id=data["id"])
        return Principal("viewer", frozenset(row["scope"]), data["id"])


def current_principal(request: Request) -> Principal:
    sid = request.cookies.get(SESSION_COOKIE)
    if sid and get_redis().get(f"sess:{sid}") == "owner":
        return Principal("owner")
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        p = verify_link(auth[7:])
        if p:
            return p
    raise HTTPException(401, "authentication required")


def require_owner(p: Principal = Depends(current_principal)) -> Principal:
    if p.role != "owner":
        raise HTTPException(403, "owner only")
    return p


def require_scope(scope: str):
    def dep(request: Request, p: Principal = Depends(current_principal)) -> Principal:
        if request.method not in ("GET", "HEAD") and p.role != "owner":
            raise HTTPException(403, "viewers are read-only")
        if scope not in p.scope:
            raise HTTPException(403, f"link does not grant '{scope}'")
        return p

    return dep
