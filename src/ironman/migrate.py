"""Apply SQL migrations in migrations/ in filename order; forward-only."""

import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql

from ironman.config import get_settings

MIGRATIONS = Path(
    os.environ.get("IRONMAN_MIGRATIONS_DIR") or Path(__file__).resolve().parents[2] / "migrations"
)


def run(url: str | None = None, directory: Path = MIGRATIONS) -> list[str]:
    files = sorted(directory.glob("*.sql"))
    if not files:
        raise SystemExit(f"no migrations found in {directory}")
    applied: list[str] = []
    with psycopg.connect(url or get_settings().database_url, autocommit=True) as c:
        c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY)")
        done = {r[0] for r in c.execute("SELECT name FROM schema_migrations")}
        for f in files:
            if f.name in done:
                continue
            with c.transaction():
                c.execute(f.read_text())
                c.execute("INSERT INTO schema_migrations VALUES (%s)", (f.name,))
            applied.append(f.name)
        pw = os.environ.get("IRONMAN_PUBLIC_ROLE_PASSWORD")
        if pw:  # deployments override the development default
            c.execute(sql.SQL("ALTER ROLE ironman_public PASSWORD {}").format(sql.Literal(pw)))
    return applied


if __name__ == "__main__":
    names = run()
    print("applied:", ", ".join(names) if names else "nothing to do", file=sys.stdout)
