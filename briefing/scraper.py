from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Iterable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .config import KEYWORDS, KST, SITES, Site, compute_window
from .http_client import get, make_session

log = logging.getLogger(__name__)

DATE_RE = re.compile(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})")


@dataclass
class Article:
    site: str
    title: str
    url: str
    published: datetime | None
    content: str


@dataclass
class ScrapeResult:
    articles: list[Article] = field(default_factory=list)
    unmatched_candidates: list[tuple[str, str, str]] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)

    def extend(self, other: "ScrapeResult") -> None:
        self.articles.extend(other.articles)
        self.unmatched_candidates.extend(other.unmatched_candidates)
        self.errors.extend(other.errors)


def _select_first(node: Tag, selector: str) -> Tag | None:
    for sel in (s.strip() for s in selector.split(",")):
        if not sel:
            continue
        found = node.select_one(sel)
        if found:
            return found
    return None


def _extract_date(node: Tag, selector: str | None) -> datetime | None:
    if not selector:
        return None
    cell = _select_first(node, selector)
    if not cell:
        for td in node.find_all(["td", "span", "div"]):
            m = DATE_RE.search(td.get_text(" ", strip=True))
            if m:
                return _build_date(*m.groups())
        return None
    m = DATE_RE.search(cell.get_text(" ", strip=True))
    if not m:
        return None
    return _build_date(*m.groups())


def _build_date(y: str, m: str, d: str) -> datetime | None:
    try:
        return datetime(int(y), int(m), int(d), tzinfo=KST)
    except ValueError:
        return None


def _matches_keyword(text: str) -> bool:
    return any(k in text for k in KEYWORDS)


def _extract_content(soup: BeautifulSoup, selector: str) -> str:
    for sel in (s.strip() for s in selector.split(",")):
        if not sel:
            continue
        node = soup.select_one(sel)
        if node:
            text = node.get_text("\n", strip=True)
            if text:
                return text
    for tag in soup.find_all(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    body = soup.find("body")
    return body.get_text("\n", strip=True) if body else ""


# ---------------------------------------------------------------
# 파싱 로직 (정적·JS 공용)
# ---------------------------------------------------------------

def _parse_list(
    list_html: str,
    site: Site,
    max_rows: int,
    fetch_detail: Callable[[str], Optional[str]],
) -> ScrapeResult:
    """List HTML을 파싱하고 keyword·window 필터를 통과한 글에 대해 fetch_detail로 본문을 가져온다."""
    result = ScrapeResult()
    soup = BeautifulSoup(list_html, "lxml")

    rows: list[Tag] = []
    for sel in (s.strip() for s in site.row_selector.split(",")):
        if not sel:
            continue
        rows = soup.select(sel)
        if rows:
            break
    if not rows:
        msg = "목록 셀렉터 매칭 실패 — 사이트 구조가 변경됐을 가능성"
        log.warning("[%s] %s", site.name, msg)
        result.errors.append((site.name, msg))
        return result

    window_start, window_end = compute_window()
    earliest_date = window_start.date()
    latest_date = window_end.date()

    for row in rows[:max_rows]:
        link = _select_first(row, site.title_link_selector)
        if not link or not link.get("href"):
            continue
        title = link.get_text(" ", strip=True)
        if not title:
            continue

        href = link["href"]
        if href.lower().startswith("javascript:"):
            continue
        url = urljoin(site.base_url + "/", href)

        published = _extract_date(row, site.date_selector)
        if published:
            d = published.date()
            if d < earliest_date or d > latest_date:
                continue

        if not _matches_keyword(title):
            result.unmatched_candidates.append((site.name, title, url))
            continue

        detail_html = fetch_detail(url)
        content = ""
        if detail_html:
            detail_soup = BeautifulSoup(detail_html, "lxml")
            content = _extract_content(detail_soup, site.detail_content_selector)[:4000]

        result.articles.append(
            Article(
                site=site.name,
                title=title,
                url=url,
                published=published,
                content=content,
            )
        )

    return result


# ---------------------------------------------------------------
# 페치 dispatch
# ---------------------------------------------------------------

def fetch_articles(session, site: Site, *, max_rows: int = 15, js_renderer=None) -> ScrapeResult:
    """site.requires_js 면 js_renderer를 통해, 아니면 requests 세션으로 페치."""
    if site.requires_js:
        if js_renderer is None:
            result = ScrapeResult()
            result.errors.append(
                (site.name, "JS 렌더러 미초기화 — fetch_all 경로로 호출하세요")
            )
            return result
        list_html = js_renderer.fetch(site.list_url)
        if list_html is None:
            result = ScrapeResult()
            result.errors.append((site.name, "JS 렌더 목록 페이지 로드 실패"))
            return result
        return _parse_list(list_html, site, max_rows, fetch_detail=js_renderer.fetch)

    res = get(session, site.list_url, encoding=site.encoding)
    if res is None:
        result = ScrapeResult()
        result.errors.append((site.name, "목록 페이지 접속 실패 (네트워크 또는 5xx)"))
        return result

    def static_detail(url: str) -> Optional[str]:
        d = get(session, url, encoding=site.encoding)
        return d.text if d is not None else None

    return _parse_list(res.text, site, max_rows, fetch_detail=static_detail)


def fetch_all(sites: Iterable[Site] = SITES) -> ScrapeResult:
    """SITES 목록을 순회. requires_js 사이트가 있으면 Playwright 1회 부팅하여 공유."""
    sites_list = list(sites)
    session = make_session()
    combined = ScrapeResult()

    needs_js = any(s.requires_js for s in sites_list)
    js_ctx = None
    if needs_js:
        try:
            from .js_fetcher import JsRenderer
            js_ctx = JsRenderer()
            js_ctx.__enter__()
        except ImportError as exc:
            log.error("playwright import 실패: %s", exc)
            for site in sites_list:
                if site.requires_js:
                    combined.errors.append(
                        (site.name, "playwright 미설치 — requirements.txt 및 워크플로우 확인")
                    )
            sites_list = [s for s in sites_list if not s.requires_js]
        except Exception as exc:  # noqa: BLE001
            log.exception("playwright 초기화 실패")
            for site in sites_list:
                if site.requires_js:
                    combined.errors.append(
                        (site.name, f"JS 렌더러 초기화 실패: {type(exc).__name__}: {exc}")
                    )
            sites_list = [s for s in sites_list if not s.requires_js]

    try:
        for site in sites_list:
            try:
                renderer = js_ctx if site.requires_js else None
                combined.extend(fetch_articles(session, site, js_renderer=renderer))
            except Exception as exc:  # noqa: BLE001 - one site shouldn't kill the run
                log.exception("[%s] scrape failed", site.name)
                combined.errors.append((site.name, f"예외 발생: {type(exc).__name__}: {exc}"))
    finally:
        if js_ctx is not None:
            js_ctx.__exit__(None, None, None)

    return combined
