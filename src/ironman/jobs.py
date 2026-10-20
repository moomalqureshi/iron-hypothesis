"""Redis-queued ingestion jobs (RQ) with retry/backoff and recorded permanent failures."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import redis
from rq import Queue, Retry

from ironman import db, metrics, strava
from ironman.config import get_settings
from ironman.ingest import store_workout

QUEUE = "ingest"


def queue(connection: redis.Redis | None = None) -> Queue:
    return Queue(QUEUE, connection=connection or redis.Redis.from_url(get_settings().redis_url))


def enqueue_activity(activity_id: int, q: Queue | None = None):
    q = q or queue()
    return q.enqueue(
        process_activity,
        activity_id,
        job_id=f"strava-{activity_id}",
        retry=Retry(max=5, interval=[30, 120, 600, 1800, 3600]),
        on_failure=record_failure,
        failure_ttl=7 * 86400,
    )


def enqueue_sync(q: Queue | None = None):
    q = q or queue()
    return q.enqueue(
        sync_strava,
        retry=Retry(max=5, interval=[60, 300, 900, 1800, 3600]),
        on_failure=record_failure,
    )


def process_activity(activity_id: int) -> str:
    with db.conn() as c:
        w = strava.fetch_activity(c, activity_id)
        wid, outcome = store_workout(c, w)
        metrics.score_workouts(c, since=w.start_time.date())
        metrics.recompute_from(c, w.start_time.date())
    return f"{outcome}:{wid}"


def sync_strava() -> int:
    """Backfill: enqueue every activity newer than the latest stored Strava workout (minus 1 day)."""
    with db.conn() as c:
        last = c.execute(
            "SELECT max(start_time) AS t FROM private.workouts WHERE source='strava'"
        ).fetchone()["t"]
        ids = strava.list_activity_ids(c, last - timedelta(days=1) if last else None)
        known = {
            r["source_id"]
            for r in c.execute("SELECT source_id FROM private.workouts WHERE source='strava'")
        }
    q = queue()
    n = 0
    for i in ids:
        if str(i) not in known:
            enqueue_activity(i, q)
            n += 1
    return n


def record_failure(job, connection, type, value, traceback):  # noqa: A002 - RQ callback signature
    with db.conn() as c:
        c.execute(
            "INSERT INTO private.failed_jobs (kind, payload, error) VALUES (%s,%s,%s)",
            (job.func_name, json.dumps({"args": list(job.args)}), f"{type.__name__}: {value}"),
        )


def now() -> datetime:
    return datetime.now(UTC)


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["sync"]:
        try:
            print("queued", sync_strava(), "new activities")
        except strava.StravaNotConnected:
            print("Strava not connected yet; nothing to sync")
    else:
        raise SystemExit("usage: python -m ironman.jobs sync")
