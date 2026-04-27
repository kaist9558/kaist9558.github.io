from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable
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
    # 키워드는 못 맞췄지만 윈도우엔 들어온 후보들 — 키워드 후보 추천에 사용.
    unmatched_candidates: list[tuple[str, str, str]] = field(default_factory=list)
    # ("법무부", "HTTP 503"), ("출입국·외국인정책본부", "no rows matched selectors") 등.
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


def fetch_articles(session, site: Site, *, max_rows: int = 15) -> ScrapeResult:
    result = ScrapeResult()

    res = get(session, site.list_url, encoding=site.encoding)
    if res is None:
        result.errors.append((site.name, "목록 페이지 접속 실패 (네트워크 또는 5xx)"))
        return result

    soup = BeautifulSoup(res.text, "lxml")
    rows: list[Tag] = []
    for sel in (s.strip() for s in site.row_selector.split(",")):
        if not sel:
            continue
        rows = soup.select(sel)
        if rows:
            break
    if not rows:
        msg = "목록 셀렉터 매칭 실패 — 사이트 구조가 변경됐을 가능성 (config.py의 row_selector 확인)"
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

        detail_res = get(session, url, encoding=site.encoding)
        content = ""
        if detail_res is not None:
            detail_soup = BeautifulSoup(detail_res.text, "lxml")
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


def fetch_all(sites: Iterable[Site] = SITES) -> ScrapeResult:
    session = make_session()
    combined = ScrapeResult()
    for site in sites:
        try:
            combined.extend(fetch_articles(session, site))
        except Exception as exc:  # noqa: BLE001 - one site shouldn't kill the run
            log.exception("[%s] scrape failed", site.name)
            combined.errors.append((site.name, f"예외 발생: {type(exc).__name__}: {exc}"))
    return combined
