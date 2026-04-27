from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

ROOT = Path(__file__).resolve().parent.parent
STORAGE_DIR = ROOT / "data"
HIKOREA_FILE_DIR = STORAGE_DIR / "hikorea_files"
DB_PATH = STORAGE_DIR / "state.sqlite3"

KEYWORDS: tuple[str, ...] = (
    "이민", "비자", "외국인", "출입국", "국적", "체류",
    "영주", "귀화", "난민", "유학생", "고용허가", "워킹홀리데이",
    "전자여행허가", "K-ETA", "재외동포",
)

LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "1"))

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


SITES: tuple[Site, ...] = (
    Site(
        name="법무부",
        list_url="https://www.moj.go.kr/moj/221/subview.do",
        base_url="https://www.moj.go.kr",
        row_selector="table.board_list tbody tr, div.board_list table tbody tr, ul.board_list li",
        title_link_selector="td.title a, td.subject a, a.title, .title a",
        date_selector="td.date, td.reg_date, .date",
        detail_content_selector="div.board_view, div.view_cont, .board_view_cont, .bbs_view",
    ),
    Site(
        name="출입국·외국인정책본부",
        list_url="https://www.immigration.go.kr/immigration/1502/subview.do",
        base_url="https://www.immigration.go.kr",
        row_selector="table tbody tr, div.board_list table tbody tr, ul.board_list li",
        title_link_selector="td.title a, td.subject a, a.title, .title a, td a",
        date_selector="td.date, td.reg_date, .date, td:nth-of-type(4)",
        detail_content_selector="div.board_view, div.view_cont, .board_view_cont, .bbs_view, .view_content",
    ),
    Site(
        name="과학기술정보통신부",
        list_url="https://www.msit.go.kr/bbs/list.do?sCode=user&mPid=208&mId=307",
        base_url="https://www.msit.go.kr",
        row_selector="table.board_list tbody tr, div.board_list table tbody tr, table tbody tr",
        title_link_selector="td.title a, td.subject a, a.title, .title a, td a",
        date_selector="td.date, td.reg_date, .date",
        detail_content_selector="div.board_view, div.view_cont, .board_view_cont, .bbs_view, .view_content",
    ),
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


SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "")


def ensure_dirs() -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    HIKOREA_FILE_DIR.mkdir(parents=True, exist_ok=True)
