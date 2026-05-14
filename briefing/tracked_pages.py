"""단일 글 페이지의 콘텐츠 갱신을 추적.

게시판 목록과 달리 URL 이 고정인 '특정 게시글' 의 첨부 갱신을 감지한다.
예: 하이코리아 '체류자격별 통합 안내 매뉴얼' (NTCCTT_SEQ=1062) —
PDF/HWP 가 정기적으로 새 버전으로 교체됨.

방식:
1. 페이지 fetch
2. signal_pattern 에 매칭되는 영역(기본: apndList hidden field) 추출
3. SHA256 해시
4. DB 의 직전 해시와 비교
5. 다르면 변경 알림 + 새 해시 저장
"""
from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from dataclasses import dataclass

from .config import TRACKED_PAGES, TrackedPage
from .http_client import get, make_session
from .storage import get_tracked_page_hash, upsert_tracked_page_hash

log = logging.getLogger(__name__)


@dataclass
class TrackedPageChange:
    label: str
    url: str
    is_first: bool
    attachments: list[str]


# apndList 안의 ORI_FILE_NM=... 값을 뽑아내 사람 보기 좋은 첨부파일 이름 목록 생성.
_ORI_FILE_NM_RE = re.compile(r"ORI_FILE_NM=([^,}]+)")


def _extract_signal(html: str, pattern: str) -> str | None:
    """signal_pattern 에 매칭되는 첫 그룹 반환. 매칭 실패 시 None."""
    m = re.search(pattern, html)
    return m.group(1) if m else None


def _extract_attachment_names(signal: str) -> list[str]:
    """apndList 형식 신호에서 ORI_FILE_NM 값을 모두 추출."""
    return [name.strip() for name in _ORI_FILE_NM_RE.findall(signal)]


def _check_one(
    session, conn: sqlite3.Connection, page: TrackedPage
) -> TrackedPageChange | None:
    res = get(session, page.url)
    if res is None:
        log.warning("[tracked:%s] fetch 실패", page.label)
        return None

    signal = _extract_signal(res.text, page.signal_pattern)
    if signal is None:
        log.warning(
            "[tracked:%s] signal_pattern 매칭 실패 — 페이지 구조 변경 가능성",
            page.label,
        )
        # signal 없으면 변경 비교 자체가 불안정 — 알림 건너뜀.
        return None

    new_hash = hashlib.sha256(signal.encode("utf-8")).hexdigest()
    old_hash = get_tracked_page_hash(conn, page.label)

    if old_hash == new_hash:
        return None  # 변경 없음

    upsert_tracked_page_hash(conn, page.label, new_hash)

    return TrackedPageChange(
        label=page.label,
        url=page.url,
        is_first=old_hash is None,
        attachments=_extract_attachment_names(signal),
    )


def check_all(conn: sqlite3.Connection) -> list[TrackedPageChange]:
    session = make_session()
    changes: list[TrackedPageChange] = []
    for page in TRACKED_PAGES:
        try:
            change = _check_one(session, conn, page)
            if change is not None:
                changes.append(change)
        except Exception:  # noqa: BLE001 - 한 페이지 실패가 전체를 막지 않게
            log.exception("[tracked:%s] 점검 중 예외", page.label)
    return changes
