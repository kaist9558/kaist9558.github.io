from __future__ import annotations

import logging
import re
from dataclasses import dataclass
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
        # Fall back: scan all <td> for a date-shaped string.
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
    # Last resort: strip nav/footer/script then dump body text.
    for tag in soup.find_all(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    body = soup.find("body")
    return body.get_text("\n", strip=True) if body else ""


def fetch_articles(
    session, site: Site, *, max_rows: int = 15
) -> list[Article]:
    res = get(session, site.list_url, encoding=site.encoding)
    if res is None:
        return []
    soup = BeautifulSoup(res.text, "lxml")

    rows: list[Tag] = []
    for sel in (s.strip() for s in site.row_selector.split(",")):
        if not sel:
            continue
        rows = soup.select(sel)
        if rows:
            break
    if not rows:
        log.warning("[%s] no rows matched selectors on %s", site.name, site.list_url)
        return []

    articles: list[Article] = []
    window_start, window_end = compute_window()
    # 보도자료는 일 단위 날짜만 제공되므로 date() 비교.
    # 윈도우가 [어제 09:30, 오늘 09:30) 라면 어제·오늘 두 날짜의 글을 모두 후보로 본다.
    # (오늘 09:30 이후 글이 함께 들어올 수 있으나, dedup 테이블이 다음 실행에서 중복 발송을 막음.)
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
            # Skip JS-only links — site likely needs a headless browser.
            continue
        url = urljoin(site.base_url + "/", href)

        published = _extract_date(row, site.date_selector)
        if published:
            d = published.date()
            if d < earliest_date or d > latest_date:
                continue

        if not _matches_keyword(title):
            continue

        detail_res = get(session, url, encoding=site.encoding)
        content = ""
        if detail_res is not None:
            detail_soup = BeautifulSoup(detail_res.text, "lxml")
            content = _extract_content(detail_soup, site.detail_content_selector)
            content = content[:4000]

        articles.append(
            Article(
                site=site.name,
                title=title,
                url=url,
                published=published,
                content=content,
            )
        )

    return articles


def fetch_all(sites: Iterable[Site] = SITES) -> list[Article]:
    session = make_session()
    out: list[Article] = []
    for site in sites:
        try:
            out.extend(fetch_articles(session, site))
        except Exception:  # noqa: BLE001 - one site shouldn't kill the run
            log.exception("[%s] scrape failed", site.name)
    return out
