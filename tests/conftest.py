import os
from datetime import UTC, datetime

import pytest

TEST_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://ironman:ironman@localhost:55432/ironman"
)
os.environ["IRONMAN_DATABASE_URL"] = TEST_URL
os.environ.setdefault(
    "IRONMAN_PUBLIC_DATABASE_URL",
    "postgresql://ironman_public:ironman_public@localhost:55432/ironman",
)

from ironman import db, migrate  # noqa: E402

PRIVATE = [
    "workouts",
    "workout_samples",
    "daily_metrics",
    "thresholds",
    "race_goal",
    "plans",
    "share_links",
    "audit_log",
    "failed_jobs",
    "model_predictions",
    "identity",
    "strava_tokens",
]
PUBLIC = [
    "meta",
    "athlete",
    "workouts",
    "weekly_volume",
    "fitness_daily",
    "goal_progress",
    "reference_population",
    "percentiles",
]


@pytest.fixture(scope="session", autouse=True)
def _migrated():
    try:
        migrate.run(TEST_URL)
    except Exception as e:  # fail loud rather than skipping DB tests silently
        pytest.exit(f"test database unavailable at {TEST_URL}: {e}", returncode=2)


@pytest.fixture
def conn():
    with db.conn(TEST_URL) as c:
        for t in PRIVATE:
            c.execute(f"TRUNCATE private.{t} CASCADE")
        for t in PUBLIC:
            c.execute(f"TRUNCATE public_data.{t}")
        c.commit()
        yield c


def make_fit(
    start: datetime, seconds: int = 120, power: int | None = 200, hr: int = 140, sport=None
) -> bytes:
    from fit_tool.fit_file_builder import FitFileBuilder
    from fit_tool.profile.messages.file_id_message import FileIdMessage
    from fit_tool.profile.messages.record_message import RecordMessage
    from fit_tool.profile.messages.session_message import SessionMessage
    from fit_tool.profile.profile_type import FileType, Manufacturer, Sport

    b = FitFileBuilder(auto_define=True)
    fid = FileIdMessage()
    fid.type = FileType.ACTIVITY
    fid.manufacturer = Manufacturer.GARMIN.value
    fid.product = 0
    fid.serial_number = 1
    fid.time_created = int(start.timestamp() * 1000)
    b.add(fid)
    t0 = int(start.timestamp() * 1000)
    for i in range(seconds):
        r = RecordMessage()
        r.timestamp = t0 + i * 1000
        r.heart_rate = hr
        if power is not None:
            r.power = power
        r.distance = i * 8.0
        b.add(r)
    s = SessionMessage()
    s.timestamp = t0 + seconds * 1000
    s.start_time = t0
    s.total_elapsed_time = seconds
    s.total_timer_time = seconds
    s.total_distance = seconds * 8.0
    s.sport = sport or Sport.CYCLING
    b.add(s)
    return b.build().to_bytes()


def utc(*a):
    return datetime(*a, tzinfo=UTC)
