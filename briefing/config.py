from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

ROOT = Path(__file__).resolve().parent.parent
STORAGE_DIR = ROOT / "data"
HIKOREA_FILE_DIR = STORAGE_DIR / "hikorea_files"
DB_PATH = STORAGE_DIR / "state.sqlite3"

KEYWORDS: tuple[str, ...] = (
    "이민", "비자", "사증", "외국인", "출입국", "입국",
    "국적", "체류", "영주", "귀화", "난민", "이주",
    "유학생", "고용허가", "계절근로자", "워킹홀리데이",
    "전자여행허가", "K-ETA", "재외동포",
)

# 브리핑 윈도우: 매일 [어제 09:30 KST, 오늘 09:30 KST) 24시간 구간을 센싱.
# 워크플로우는 09:40 KST에 실행되어 윈도우 종료 10분 후 게시.
WINDOW_HOURS = int(os.getenv("WINDOW_HOURS", "24"))
WINDOW_END_HOUR_KST = int(os.getenv("WINDOW_END_HOUR_KST", "9"))
WINDOW_END_MINUTE_KST = int(os.getenv("WINDOW_END_MINUTE_KST", "30"))


def compute_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """브리핑 시간 윈도우 (start, end) — 둘 다 KST tz-aware."""
    now = now or datetime.now(KST)
    end = now.replace(
        hour=WINDOW_END_HOUR_KST,
        minute=WINDOW_END_MINUTE_KST,
        second=0,
        microsecond=0,
    )
    if end > now:
        # 오늘의 종료 시각이 아직 안 지났으면 어제 종료 시각으로
        end -= timedelta(days=1)
    start = end - timedelta(hours=WINDOW_HOURS)
    return start, end

REQUEST_TIMEOUT = 15
REQUEST_RETRIES = 3
USER_AGENT = (
    "Mozilla/5.0 (compatible; ImmigrationBriefingBot/1.0; "
    "+https://github.com/kaist9558/kaist9558.github.io)"
)


@dataclass(frozen=True)
class Site:
    name: str
    list_url: str
    base_url: str
    row_selector: str
    title_link_selector: str
    date_selector: str | None
    detail_content_selector: str
    encoding: str | None = None


# 법무부와 출입국·외국인정책본부는 같은 통합 CMS(artclLinkView/_artclTd*/_articleTable)를 사용.
# 과기부(msit.go.kr)는 글 목록이 JS 렌더링으로 채워지는 SPA 형태라 정적 HTML 크롤링 불가 —
# 현재는 비활성화. 추후 playwright 등 headless 브라우저 도입 시 재활성화.
SITES: tuple[Site, ...] = (
    Site(
        name="법무부",
        list_url="https://www.moj.go.kr/moj/221/subview.do",
        base_url="https://www.moj.go.kr",
        row_selector="div._articleTable table tbody tr, table tbody tr",
        title_link_selector="a.artclLinkView, td._artclTdTitle a",
        date_selector="td._artclTdRdate",
        detail_content_selector="div.artclView, div._articleTable._mojView",
    ),
    Site(
        name="출입국·외국인정책본부",
        list_url="https://www.immigration.go.kr/immigration/1502/subview.do",
        base_url="https://www.immigration.go.kr",
        row_selector="div._articleTable table tbody tr, table tbody tr",
        title_link_selector="a.artclLinkView, td._artclTdTitle a",
        date_selector="td._artclTdRdate",
        detail_content_selector="div.artclView, div._articleTable._mojView",
    ),
    # TODO(msit): 과기부는 글 목록이 JS로 렌더링되는 구조 — 정적 HTML에 <table>이 없음.
    # 재활성화 옵션: (1) playwright 도입, (2) 백엔드 AJAX 엔드포인트 직접 호출, (3) RSS 피드 활용.
    # Site(
    #     name="과학기술정보통신부",
    #     list_url="https://www.msit.go.kr/bbs/list.do?sCode=user&mPid=208&mId=307",
    #     base_url="https://www.msit.go.kr",
    #     row_selector="...",
    #     title_link_selector="...",
    #     date_selector="...",
    #     detail_content_selector="...",
    # ),
)


@dataclass(frozen=True)
class HikoreaTarget:
    """하이코리아 공지사항 게시글 — 첨부파일이 갱신되는 페이지를 추적."""

    label: str
    url: str
    bbs_seq: int
    notice_seq: int


HIKOREA_TARGETS: tuple[HikoreaTarget, ...] = (
    HikoreaTarget(
        label="체류관리지침",
        url="https://www.hikorea.go.kr/board/BoardNtcDetailR.pt"
        "?BBS_SEQ=1&BBS_GB_CD=BS10&NTCCTT_SEQ=1062&page=1",
        bbs_seq=1,
        notice_seq=1062,
    ),
)
HIKOREA_BASE = "https://www.hikorea.go.kr"


CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
CLAUDE_MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS", "1024"))


def ensure_dirs() -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    HIKOREA_FILE_DIR.mkdir(parents=True, exist_ok=True)
