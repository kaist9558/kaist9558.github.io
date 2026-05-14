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

CREATE TABLE IF NOT EXISTS tracked_pages (
    label TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    last_checked TEXT NOT NULL
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


def get_tracked_page_hash(conn: sqlite3.Connection, label: str) -> str | None:
    row = conn.execute(
        "SELECT content_hash FROM tracked_pages WHERE label = ?",
        (label,),
    ).fetchone()
    return row["content_hash"] if row else None


def upsert_tracked_page_hash(
    conn: sqlite3.Connection, label: str, content_hash: str
) -> None:
    conn.execute(
        """
        INSERT INTO tracked_pages(label, content_hash, last_checked)
        VALUES (?, ?, ?)
        ON CONFLICT(label) DO UPDATE SET
            content_hash = excluded.content_hash,
            last_checked = excluded.last_checked
        """,
        (label, content_hash, datetime.now(KST).isoformat()),
    )
