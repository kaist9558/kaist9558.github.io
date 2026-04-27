from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .config import HIKOREA_BASE, HIKOREA_FILE_DIR, HIKOREA_TARGETS, KST, HikoreaTarget
from .http_client import get, make_session
from .storage import latest_hikorea_file, record_hikorea_file

log = logging.getLogger(__name__)


@dataclass
class FileChange:
    target_label: str
    file_name: str
    page_url: str
    new_path: Path
    old_path: Path | None
    new_text: str | None
    old_text: str | None


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w가-힣().\-_ ]+", "_", name).strip() or "attachment"


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _extract_text(path: Path) -> str | None:
    """Best-effort text extraction. Returns None for unsupported formats (e.g. HWP)."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        if suffix in {".docx"}:
            from docx import Document

            doc = Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs)
        if suffix in {".txt", ".md", ".csv"}:
            return path.read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        log.exception("text extraction failed for %s", path)
    return None


def _find_attachment_links(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """Returns list of (display_name, href) for file download links."""
    from urllib.parse import urlparse

    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a"):
        href = a.get("href") or ""
        text = a.get_text(" ", strip=True)
        if not href or not text:
            continue

        # 외부 링크 제외 (예: 페이지 본문 안에 박힌 microsoft.com 'HWP 뷰어 다운로드' 안내).
        # netloc이 비어있으면 상대경로 (hikorea 자체) — 통과.
        parsed = urlparse(href)
        if parsed.netloc and "hikorea.go.kr" not in parsed.netloc.lower():
            continue
        # 스킴이 http/https/없음(상대경로)이 아닌 것은 제외 (예: ttp://... 오타).
        if parsed.scheme and parsed.scheme.lower() not in ("http", "https"):
            continue

        href_l = href.lower()
        is_download = (
            "download" in href_l
            or "fileDown" in href
            or "attach" in href_l
            or "FILEID" in href.upper()
        )
        looks_like_filename = re.search(
            r"\.(pdf|hwp|hwpx|docx?|xlsx?|pptx?|zip|txt|jpg|png)\b", text, re.I
        )
        if (is_download or looks_like_filename) and href not in seen:
            seen.add(href)
            candidates.append((text, href))
    return candidates


def _download(session, url: str) -> tuple[bytes, str | None] | None:
    try:
        res = session.get(url, timeout=30, stream=True)
        res.raise_for_status()
        suggested = None
        cd = res.headers.get("Content-Disposition", "")
        m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", cd)
        if m:
            try:
                from urllib.parse import unquote
                suggested = unquote(m.group(1))
            except Exception:
                suggested = m.group(1)
        return res.content, suggested
    except Exception:  # noqa: BLE001
        log.exception("download failed: %s", url)
        return None


def check_target(
    session, conn: sqlite3.Connection, target: HikoreaTarget
) -> list[FileChange]:
    res = get(session, target.url)
    if res is None:
        return []
    soup = BeautifulSoup(res.text, "lxml")
    links = _find_attachment_links(soup)
    if not links:
        log.info("[하이코리아:%s] no attachments detected", target.label)
        return []

    changes: list[FileChange] = []
    timestamp = datetime.now(KST).strftime("%Y%m%d_%H%M%S")

    for display_name, href in links:
        download_url = urljoin(HIKOREA_BASE, href)
        result = _download(session, download_url)
        if result is None:
            continue
        data, suggested = result

        file_name = _safe_filename(suggested or display_name)
        digest = _hash_bytes(data)

        prev = latest_hikorea_file(conn, target.notice_seq, file_name)
        if prev and prev["sha256"] == digest:
            continue  # unchanged

        save_dir = HIKOREA_FILE_DIR / str(target.notice_seq)
        save_dir.mkdir(parents=True, exist_ok=True)
        new_path = save_dir / f"{timestamp}_{file_name}"
        new_path.write_bytes(data)
        record_hikorea_file(
            conn,
            notice_seq=target.notice_seq,
            file_name=file_name,
            sha256=digest,
            saved_path=new_path,
        )

        old_path = Path(prev["saved_path"]) if prev else None
        old_text = _extract_text(old_path) if old_path and old_path.exists() else None
        new_text = _extract_text(new_path)

        changes.append(
            FileChange(
                target_label=target.label,
                file_name=file_name,
                page_url=target.url,
                new_path=new_path,
                old_path=old_path,
                new_text=new_text,
                old_text=old_text,
            )
        )

    return changes


def check_all(conn: sqlite3.Connection) -> list[FileChange]:
    session = make_session()
    out: list[FileChange] = []
    for target in HIKOREA_TARGETS:
        try:
            out.extend(check_target(session, conn, target))
        except Exception:  # noqa: BLE001
            log.exception("[하이코리아:%s] check failed", target.label)
    return out
