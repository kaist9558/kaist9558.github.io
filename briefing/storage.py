from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
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

CREATE TABLE IF NOT EXISTS hikorea_files (
    notice_seq INTEGER NOT NULL,
    file_name TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    saved_path TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    PRIMARY KEY (notice_seq, file_name, sha256)
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


def latest_hikorea_file(
    conn: sqlite3.Connection, notice_seq: int, file_name: str
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT sha256, saved_path, captured_at
        FROM hikorea_files
        WHERE notice_seq = ? AND file_name = ?
        ORDER BY captured_at DESC
        LIMIT 1
        """,
        (notice_seq, file_name),
    ).fetchone()


def record_hikorea_file(
    conn: sqlite3.Connection,
    *,
    notice_seq: int,
    file_name: str,
    sha256: str,
    saved_path: Path,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO hikorea_files(notice_seq, file_name, sha256, saved_path, captured_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (notice_seq, file_name, sha256, str(saved_path), datetime.now(KST).isoformat()),
    )
