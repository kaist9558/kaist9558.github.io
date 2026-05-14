from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

ROOT = Path(__file__).resolve().parent.parent
STORAGE_DIR = ROOT / "data"
DB_PATH = STORAGE_DIR / "state.sqlite3"

KEYWORDS: tuple[str, ...] = (
    # 핵심 카테고리
    "이민", "비자", "사증", "외국인", "출입국", "입국",
    "국적", "체류", "영주", "귀화", "난민", "이주",
    # 학업·노동·관광 채널
    "유학생", "고용허가", "계절근로자", "워킹홀리데이",
    "전자여행허가", "K-ETA",
    # 동포·재외국민
    "재외동포", "재외국민",
    # 다문화·사회통합 — 이민 정책 직접 인접어
    "다문화", "사회통합", "KIIP",
    # 인재 비자 정책 (디지털/과학기술 인재 유치 기조)
    "인재유치", "우수인재", "고급인재",
    # 비자 분류 코드 — 본문이 코드만 쓰는 경우 (E-9 고용허가 등은 위 키워드로 cover)
    "E-7", "F-2", "F-4", "F-5", "F-6", "D-8", "D-10",
)

# 브리핑 윈도우: 매일 [어제 10:00 KST, 오늘 10:00 KST] 24시간 구간을 센싱.
# 워크플로우는 매일 10:00 KST (UTC 01:00, cron "0 1 * * *")에 실행되며,
# 게시일 ≤ 당일 10:00 KST 조건을 만족하는 글만 수집해 즉시 발송.
WINDOW_HOURS = int(os.getenv("WINDOW_HOURS", "24"))
WINDOW_END_HOUR_KST = int(os.getenv("WINDOW_END_HOUR_KST", "10"))
WINDOW_END_MINUTE_KST = int(os.getenv("WINDOW_END_MINUTE_KST", "0"))


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
    requires_js: bool = False  # True면 Playwright(JsRenderer)로 페치
    # title_link_selector 가 가리키는 element 안에 제목 외 텍스트(부서/담당자 등)가
    # 섞여 있는 사이트(예: MSIT)는 별도 selector 로 제목 텍스트만 추출.
    title_selector: str | None = None
    # 일부 사이트는 <a href="javascript:;" onclick="fn_detail(NNN)"> 형태로 SPA 라우팅.
    # onclick 패턴에서 ID를 뽑아 view URL 을 직접 만들어야 한다.
    onclick_id_pattern: str | None = None      # e.g., r"fn_detail\((\d+)\)"
    view_url_template: str | None = None       # e.g., "{base}/bbs/view.do?...&nttSeqNo={id}"
    # AJAX 로 행 데이터가 채워지는 사이트 — Playwright 가 이 selector 가 비어있지 않을
    # 때까지 추가 대기.
    wait_selector: str | None = None


# 수집 소스 3개:
#   - 법무부 보도자료 / 출입국·외국인정책본부 보도자료 — 정부 통합 CMS
#     (artclLinkView / _artclTd* / _articleTable 셀렉터 공유)
#   - 하이코리아 공지사항 — 자체 게시판 시스템 (boardDetailR onclick 패턴, 정적 HTML)
# 셀렉터는 사이트 진단 결과(`python -m briefing.diagnose`) 기반으로 보정 가능.
SITES: tuple[Site, ...] = (
    Site(
        name="법무부 보도자료",
        list_url="https://www.moj.go.kr/moj/221/subview.do",
        base_url="https://www.moj.go.kr",
        row_selector="div._articleTable table tbody tr, table tbody tr",
        title_link_selector="a.artclLinkView, td._artclTdTitle a",
        date_selector="td._artclTdRdate",
        detail_content_selector="div.artclView, div._articleTable._mojView",
    ),
    Site(
        name="출입국·외국인정책본부 보도자료",
        list_url="https://www.immigration.go.kr/immigration/1502/subview.do",
        base_url="https://www.immigration.go.kr",
        row_selector="div._articleTable table tbody tr, table tbody tr",
        title_link_selector="a.artclLinkView, td._artclTdTitle a",
        date_selector="td._artclTdRdate",
        detail_content_selector="div.artclView, div._articleTable._mojView",
    ),
    Site(
        name="하이코리아 공지사항",
        list_url="https://www.hikorea.go.kr/board/BoardNtcListR.pt?BBS_GB_CD=BS10",
        base_url="https://www.hikorea.go.kr",
        # 행: <tr class="board_line"> (검색 폼 테이블 제외용 클래스).
        # 링크: javascript:void(0) + onclick="boardDetailR('NNN')" 패턴
        #       → onclick_id_pattern + view_url_template 으로 view URL 직접 구성.
        # 날짜: 마지막 td (YYYY-MM-DD 텍스트).
        row_selector="tr.board_line",
        title_link_selector="td a[onclick*='boardDetailR']",
        date_selector="td:last-child",
        detail_content_selector="div.board_view, div.viewbox, div.contents",
        onclick_id_pattern=r"boardDetailR\('?(\d+)'?\)",
        view_url_template=(
            "https://www.hikorea.go.kr/board/BoardNtcDetailR.pt?"
            "BBS_SEQ=1&BBS_GB_CD=BS10&NTCCTT_SEQ={id}&page=1"
        ),
    ),
)


# ⚠️ 과학기술정보통신부(MSIT) — GitHub Actions runner 환경(비-한국 IP)에서
# `net::ERR_CONNECTION_RESET` 으로 서버가 TCP 연결을 능동적으로 끊습니다.
# 첫 페이지는 빈 placeholder 만 받고(39KB) 재시도는 즉시 reset.
# Playwright + stealth + 실제 Chrome UA 로도 우회되지 않음 (IP 기반 차단).
# 아래 Site 정의는 한국 IP proxy / self-hosted KR runner 가 준비되면
# `SITES = SITES + (_MSIT_SITE,)` 한 줄로 즉시 활성화할 수 있도록 보존.
_MSIT_SITE = Site(
    name="과학기술정보통신부",
    list_url="https://www.msit.go.kr/bbs/list.do?sCode=user&mPid=208&mId=307",
    base_url="https://www.msit.go.kr",
    # MSIT 보도자료: AJAX 후주입. row 컨테이너는 <div class="toggle">, header row는 .thead 클래스로 제외.
    row_selector="div.board_list div.toggle:not(.thead)",
    # <a href="javascript:;" onclick="fn_detail(NNN)"> wrapper.
    title_link_selector="a[onclick*='fn_detail']",
    # 진짜 제목 텍스트는 <a> 내부 <p class="title">.
    title_selector="p.title",
    date_selector="div.date",
    detail_content_selector="div.board_view, div.view_cont, .view_wrap",
    onclick_id_pattern=r"fn_detail\((\d+)\)",
    view_url_template=(
        "https://www.msit.go.kr/bbs/view.do?"
        "sCode=user&mPid=208&mId=307&nttSeqNo={id}"
    ),
    # placeholder 가 채워질 때까지 대기. 첫 행의 <p class="title"> 텍스트가
    # 빈 상태에서 채워지는 시점을 기준.
    wait_selector="div.board_list p.title:not(:empty)",
    requires_js=True,
)


@dataclass(frozen=True)
class TrackedPage:
    """게시판 목록이 아니라 '단일 글 페이지'의 첨부파일 갱신만 추적.

    예: 하이코리아 체류관리지침처럼 글 URL은 고정인데 첨부 PDF/HWP 가
    교체되는 페이지. 페이지의 apndList hidden field 또는 첨부 링크
    영역을 해시해 비교한다."""

    label: str
    url: str
    # 변경 신호 추출 규칙. 기본은 apndList hidden field (하이코리아 게시판 패턴).
    # 다른 사이트면 별도 추출 regex 를 줘서 재사용 가능.
    signal_pattern: str = r'name="apndList"[^>]*value="([^"]*)"'


TRACKED_PAGES: tuple[TrackedPage, ...] = (
    TrackedPage(
        # 하이코리아 게시글의 실제 제목과 동일하게 표기.
        label="체류자격별 통합 안내 매뉴얼(최신)",
        url=(
            "https://www.hikorea.go.kr/board/BoardNtcDetailR.pt?"
            "BBS_SEQ=1&BBS_GB_CD=BS10&NTCCTT_SEQ=1062&page=1"
        ),
    ),
)


CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
CLAUDE_MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS", "1024"))


def ensure_dirs() -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
