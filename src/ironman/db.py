from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from ironman.config import get_settings


def connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or get_settings().database_url, row_factory=dict_row)


@contextmanager
def conn(url: str | None = None):
    c = connect(url)
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def public_conn():
    return conn(get_settings().public_database_url)
