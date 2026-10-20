"""Private API: auth, ingestion endpoints, metrics, plans, share links."""

from __future__ import annotations

import hmac
from datetime import date, datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from ironman import auth, db, ingest, jobs, metrics, strava
from ironman.config import get_settings

app = FastAPI(title="Ironman private API")
DISCLAIMER = "Training signals only, not medical advice."


@app.get("/healthz")
def healthz():
    with db.conn() as c:
        c.execute("SELECT 1")
    return {"ok": True}


# --- auth -------------------------------------------------------------------
class SetupIn(BaseModel):
    password: str


class LoginIn(BaseModel):
    password: str
    totp: str | None = None


@app.post("/api/auth/setup")
def setup(body: SetupIn):
    with db.conn() as c:
        return {"totp_uri": auth.setup_owner(c, body.password)}


@app.post("/api/auth/login")
def login(body: LoginIn, response: Response):
    with db.conn() as c:
        sid = auth.login(c, body.password, body.totp)
    response.set_cookie(
        auth.SESSION_COOKIE,
        sid,
        httponly=True,
        samesite="lax",
        max_age=get_settings().session_ttl_s,
    )
    return {"ok": True}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    auth.logout(request.cookies.get(auth.SESSION_COOKIE))
    response.delete_cookie(auth.SESSION_COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(p: auth.Principal = Depends(auth.current_principal)):
    return {"role": p.role, "scope": sorted(p.scope)}


class LinkIn(BaseModel):
    scope: list[str]
    days: int = 14
    label: str = ""


@app.post("/api/share-links")
def create_link(body: LinkIn, _=Depends(auth.require_owner)):
    with db.conn() as c:
        return auth.create_link(c, body.scope, body.days, body.label)


@app.get("/api/share-links")
def list_links(_=Depends(auth.require_owner)):
    with db.conn() as c:
        return c.execute("SELECT * FROM private.share_links ORDER BY created_at DESC").fetchall()


@app.delete("/api/share-links/{link_id}")
def revoke_link(link_id: str, _=Depends(auth.require_owner)):
    with db.conn() as c:
        auth.revoke_link(c, link_id)
    return {"ok": True}


# --- Strava -----------------------------------------------------------------
@app.get("/api/strava/connect")
def strava_connect(_=Depends(auth.require_owner)):
    if not get_settings().strava_client_id:
        raise HTTPException(503, "IRONMAN_STRAVA_CLIENT_ID is not configured")
    return {"url": strava.authorize_url()}


@app.get("/api/strava/callback")
def strava_callback(code: str, _=Depends(auth.require_owner)):
    with db.conn() as c:
        strava.exchange_code(c, code)
    jobs.enqueue_sync()
    return RedirectResponse(get_settings().web_origin + "/?strava=connected")


@app.post("/api/strava/sync")
def strava_sync(_=Depends(auth.require_owner)):
    jobs.enqueue_sync()
    return {"queued": True}


@app.get("/api/strava/webhook")
def webhook_verify(request: Request):
    q = request.query_params
    if q.get("hub.mode") != "subscribe" or not hmac.compare_digest(
        q.get("hub.verify_token", ""), get_settings().strava_verify_token
    ):
        raise HTTPException(403, "verification failed")
    return {"hub.challenge": q.get("hub.challenge")}


@app.post("/api/strava/webhook")
async def webhook_event(request: Request):
    # Events carry no signature, so accept only those for the connected athlete and fetch the
    # data ourselves from Strava rather than trusting the payload.
    ev = await request.json()
    with db.conn() as c:
        row = c.execute("SELECT athlete_id FROM private.strava_tokens").fetchone()
    if not row or ev.get("owner_id") != row["athlete_id"]:
        raise HTTPException(403, "unknown subscription")
    if ev.get("object_type") == "activity" and ev.get("aspect_type") in ("create", "update"):
        jobs.enqueue_activity(int(ev["object_id"]))
    return {"ok": True}


@app.post("/api/workouts/upload")
async def upload(file: UploadFile, sport: str = "other", _=Depends(auth.require_owner)):
    data = await file.read()
    name = file.filename or "upload"
    try:
        if name.lower().endswith(".fit"):
            w = ingest.parse_fit(data, name)
        elif name.lower().endswith(".gpx"):
            w = ingest.parse_gpx(data, name, sport=ingest.norm_sport(sport))
        else:
            raise ingest.ParseError("only .fit and .gpx files are supported")
    except ingest.ParseError as e:
        raise HTTPException(422, str(e)) from e
    with db.conn() as c:
        wid, outcome = ingest.store_workout(c, w)
        metrics.score_workouts(c, since=w.start_time.date())
        metrics.recompute_from(c, w.start_time.date())
    return {"id": wid, "outcome": outcome}


# --- data -------------------------------------------------------------------
@app.get("/api/workouts")
def workouts(limit: int = 50, _=Depends(auth.require_scope("workouts"))):
    with db.conn() as c:
        return c.execute(
            "SELECT id, source, sport, start_time, duration_s, distance_m, avg_hr, avg_power, "
            "tss, tss_method, flagged FROM private.workouts ORDER BY start_time DESC LIMIT %s",
            (min(limit, 500),),
        ).fetchall()


@app.get("/api/metrics/fitness")
def fitness(days: int = 180, _=Depends(auth.require_scope("metrics"))):
    with db.conn() as c:
        return c.execute(
            "SELECT * FROM private.daily_metrics WHERE day >= current_date - %s ORDER BY day",
            (days,),
        ).fetchall()


@app.get("/api/metrics/volume")
def volume(_=Depends(auth.require_scope("metrics"))):
    with db.conn() as c:
        return metrics.weekly_volume(c)


@app.get("/api/metrics/goal")
def goal(_=Depends(auth.require_scope("metrics"))):
    with db.conn() as c:
        return metrics.goal_progress(c)


class ThresholdsIn(BaseModel):
    effective_from: date
    ftp: float | None = None
    run_threshold_pace: float | None = None
    swim_css: float | None = None
    max_hr: float | None = None
    lthr: float | None = None


@app.put("/api/thresholds")
def set_thresholds(body: ThresholdsIn, _=Depends(auth.require_owner)):
    with db.conn() as c:
        c.execute(
            "INSERT INTO private.thresholds VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (effective_from) "
            "DO UPDATE SET ftp=EXCLUDED.ftp, run_threshold_pace=EXCLUDED.run_threshold_pace, "
            "swim_css=EXCLUDED.swim_css, max_hr=EXCLUDED.max_hr, lthr=EXCLUDED.lthr",
            (
                body.effective_from,
                body.ftp,
                body.run_threshold_pace,
                body.swim_css,
                body.max_hr,
                body.lthr,
            ),
        )
        metrics.score_workouts(c, since=body.effective_from)
        metrics.recompute_from(c, body.effective_from)
    return {"ok": True}


@app.get("/api/thresholds")
def get_thresholds(_=Depends(auth.require_owner)):
    with db.conn() as c:
        return c.execute("SELECT * FROM private.thresholds ORDER BY effective_from DESC").fetchall()


class GoalIn(BaseModel):
    name: str
    race_date: date
    target_seconds: int | None = None
    target_ctl: float | None = None


@app.put("/api/goal")
def set_goal(body: GoalIn, _=Depends(auth.require_owner)):
    with db.conn() as c:
        c.execute(
            "INSERT INTO private.race_goal VALUES (1,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET "
            "name=EXCLUDED.name, race_date=EXCLUDED.race_date, "
            "target_seconds=EXCLUDED.target_seconds, target_ctl=EXCLUDED.target_ctl",
            (body.name, body.race_date, body.target_seconds, body.target_ctl),
        )
    return {"ok": True}


@app.get("/api/jobs/failed")
def failed_jobs(_=Depends(auth.require_owner)):
    with db.conn() as c:
        return c.execute("SELECT * FROM private.failed_jobs ORDER BY at DESC LIMIT 50").fetchall()


def _since(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


# --- predictions and plans ----------------------------------------------------
from ironman import analysis, coach  # noqa: E402


@app.get("/api/predictions/race-time")
def p_race_time(_=Depends(auth.require_scope("predictions"))):
    with db.conn() as c:
        return {**analysis.predict_race_time(c), "disclaimer": DISCLAIMER}


@app.get("/api/predictions/forecast")
def p_forecast(weekly_tss: float | None = None, _=Depends(auth.require_scope("predictions"))):
    with db.conn() as c:
        return {"forecast": analysis.forecast_to_race(c, weekly_tss), "disclaimer": DISCLAIMER}


@app.get("/api/predictions/risk")
def p_risk(_=Depends(auth.require_scope("predictions"))):
    with db.conn() as c:
        return {**analysis.overtraining_risk(c), "disclaimer": DISCLAIMER}


@app.get("/api/predictions/anomalies")
def p_anomalies(_=Depends(auth.require_scope("predictions"))):
    with db.conn() as c:
        return {**analysis.anomalies(c), "disclaimer": DISCLAIMER}


class PlanIn(BaseModel):
    week_start: date | None = None


@app.post("/api/plans/generate")
def generate(body: PlanIn, _=Depends(auth.require_owner)):
    today = date.today()
    week = body.week_start or today + timedelta(days=7 - today.weekday())
    with db.conn() as c:
        return coach.generate_plan(c, week, redis=auth.get_redis())


@app.get("/api/plans")
def list_plans(_=Depends(auth.require_scope("plans"))):
    with db.conn() as c:
        rows = c.execute("SELECT * FROM private.plans ORDER BY created_at DESC LIMIT 10").fetchall()
    return [{**r, "disclaimer": DISCLAIMER} for r in rows]


@app.get("/api/workouts/{workout_id}/zones")
def workout_zones(workout_id: str, _=Depends(auth.require_scope("workouts"))):
    with db.conn() as c:
        w = c.execute(
            "SELECT start_time FROM private.workouts WHERE id=%s", (workout_id,)
        ).fetchone()
        if not w:
            raise HTTPException(404, "workout not found")
        t = metrics.thresholds_for(
            c.execute("SELECT * FROM private.thresholds").fetchall(), w["start_time"].date()
        )
        return {kind: metrics.time_in_zone(c, workout_id, kind, t) for kind in ("power", "hr")}
