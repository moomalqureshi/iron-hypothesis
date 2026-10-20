"""Public read-only API. Connects as the ironman_public role, which can read public_data only."""

from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ironman import auth, db, demo
from ironman.config import get_settings

app = FastAPI(title="Ironman public API", docs_url=None, redoc_url=None, openapi_url=None)
DISCLAIMER = "Training signals only, not medical advice."


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.method not in ("GET", "HEAD"):
        return JSONResponse({"detail": "read-only API"}, status_code=405)
    if request.url.path != "/healthz":
        ip = request.client.host if request.client else "unknown"
        key = f"rl:{ip}:{int(time.time() // 60)}"
        r = auth.get_redis()
        n = r.incr(key)
        if n == 1:
            r.expire(key, 90)
        if n > get_settings().public_rate_limit_per_min:
            return JSONResponse(
                {"detail": "rate limit exceeded"}, status_code=429, headers={"Retry-After": "60"}
            )
    return await call_next(request)


@app.get("/healthz")
def healthz():
    return {"ok": True}


def _meta(c) -> dict:
    m = c.execute("SELECT refreshed_at FROM public_data.meta").fetchone()
    return {
        "refreshed_at": m["refreshed_at"] if m else None,
        "disclaimer": DISCLAIMER,
        "demo": False,
    }


@app.get("/public/api/dashboard")
def dashboard():
    with db.public_conn() as c:
        return {
            **_meta(c),
            "fitness": c.execute("SELECT * FROM public_data.fitness_daily ORDER BY day").fetchall(),
            "volume": c.execute(
                "SELECT * FROM public_data.weekly_volume ORDER BY week_start, sport"
            ).fetchall(),
            "goal": c.execute("SELECT * FROM public_data.goal_progress").fetchone(),
            "percentiles": c.execute("SELECT * FROM public_data.percentiles").fetchall(),
            "athlete": c.execute("SELECT * FROM public_data.athlete").fetchone(),
        }


@app.get("/public/api/demo")
def demo_dashboard():
    return {
        **demo.public_demo_payload(),
        "disclaimer": DISCLAIMER,
        "label": "demo - synthetic data",
    }
