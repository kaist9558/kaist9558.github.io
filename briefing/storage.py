from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from .config import DB_PATH, KST, ensure_dirs

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_articles (
    site TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    PRIMARY KEY (site, url)
);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def is_article_seen(conn: sqlite3.Connection, site: str, url: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM seen_articles WHERE site = ? AND url = ?",
        (site, url),
    ).fetchone()
    return row is not None


def mark_article_seen(conn: sqlite3.Connection, site: str, url: str, title: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO seen_articles(site, url, title, first_seen) VALUES (?, ?, ?, ?)",
        (site, url, title, datetime.now(KST).isoformat()),
    )
