"""사이트별 HTML 구조 진단 — 셀렉터 보정용.

GitHub Actions에서 `python -m briefing.diagnose` 로 호출하면 각 사이트의
응답 구조를 분석해서 stdout에 출력합니다. 출력 결과를 보면 어떤 CSS
셀렉터가 매칭되는지, 어떤 wrapping 컨테이너가 후보인지 한눈에 보입니다.
"""
from __future__ import annotations

import logging
import sys

from bs4 import BeautifulSoup

from .config import SITES, Site
from .http_client import get, make_session

logging.basicConfig(level="INFO", format="%(message)s")
log = logging.getLogger("diagnose")


CANDIDATE_ROW_SELECTORS = [
    "table.board_list tbody tr",
    "table.board-list tbody tr",
    "table.bbs_list tbody tr",
    "table.bbs-list tbody tr",
    "table.tbl_list tbody tr",
    "table.tbl-list tbody tr",
    "table.list_table tbody tr",
    "div.board_list table tbody tr",
    "div.bbs_list table tbody tr",
    "div.list_wrap table tbody tr",
    "div.board_wrap table tbody tr",
    "div.bbs_wrap table tbody tr",
    "section.board table tbody tr",
    "table tbody tr",
    "ul.board_list > li",
    "ul.bbs_list > li",
    "ul.board-list > li",
    "div.list_board ul > li",
    "div.board_list > ul > li",
]


def inspect_site(session, site: Site, js_renderer=None) -> None:
    print()
    print("=" * 70)
    print(f"[{site.name}]  {site.list_url}")
    if site.requires_js:
        print("(requires_js=True — Playwright 사용)")
    print("=" * 70)

    if site.requires_js:
        if js_renderer is None:
            print("FETCH FAILED — JS 렌더러 미초기화")
            return
        html = js_renderer.fetch(site.list_url)
        if html is None:
            print("FETCH FAILED — JS 렌더 페이지 로드 실패")
            return
        print(f"JS 렌더 완료. size={len(html)} bytes")
    else:
        res = get(session, site.list_url, encoding=site.encoding)
        if res is None:
            print("FETCH FAILED — http_client.get returned None")
            return
        html = res.text
        print(f"HTTP {res.status_code}   size={len(res.text)} bytes   encoding={res.encoding}")
        if res.headers.get("content-type"):
            print(f"Content-Type: {res.headers['content-type']}")

    soup = BeautifulSoup(html, "lxml")

    page_title = soup.find("title")
    print(f"<title>: {page_title.get_text(strip=True) if page_title else '(none)'}")

    # 1) 후보 셀렉터 매칭 시도
    print("\n--- 후보 row 셀렉터 매칭 결과 ---")
    matches: list[tuple[str, int]] = []
    for sel in CANDIDATE_ROW_SELECTORS:
        try:
            rows = soup.select(sel)
        except Exception:
            continue
        if rows:
            matches.append((sel, len(rows)))

    if not matches:
        print("  ❌ 어떤 후보도 매칭되지 않음 → JS 렌더링 가능성 또는 완전히 다른 구조")
    else:
        for sel, n in matches:
            print(f"  ✅ {sel!r:60s} → {n}개")

    # 2) 첫 매칭 셀렉터에 대한 상세
    if matches:
        best_sel, _ = matches[0]
        rows = soup.select(best_sel)
        first = rows[0] if rows else None
        if first:
            print(f"\n--- '{best_sel}' 첫 행 구조 ---")
            print(f"  태그: <{first.name} class={first.get('class')} id={first.get('id')}>")
            link = first.select_one("a[href]")
            if link:
                href = link.get("href", "")
                print(f"  첫 <a>: class={link.get('class')} href={href[:100]!r}")
                print(f"  첫 <a> 텍스트: {link.get_text(' ', strip=True)[:120]!r}")
            else:
                print("  첫 <a href> 못찾음")
            # 모든 td/li 안의 클래스 정보
            for child in first.find_all(["td", "th", "span", "div"], recursive=False):
                child_cls = " ".join(child.get("class") or [])
                child_text = child.get_text(" ", strip=True)[:60]
                print(f"  <{child.name} class={child_cls!r}>: {child_text!r}")

    # 3) class/id에 board/bbs/list/tbl 포함된 컨테이너 후보
    print("\n--- wrapping 컨테이너 후보 (class/id에 board/bbs/list/tbl/article) ---")
    keywords = ("board", "bbs", "list", "tbl", "article", "notice")
    seen: set[str] = set()
    for tag in soup.find_all(["table", "div", "ul", "ol", "section"]):
        cls = " ".join(tag.get("class") or [])
        tid = tag.get("id") or ""
        attr_text = (cls + " " + tid).lower()
        if not any(k in attr_text for k in keywords):
            continue
        sig = f"{tag.name}:{cls}:{tid}"
        if sig in seen:
            continue
        seen.add(sig)
        child_rows = len(tag.find_all(["tr", "li"], recursive=True))
        if child_rows == 0:
            continue
        print(f"  <{tag.name} class={cls!r} id={tid!r}> → 내부 tr/li {child_rows}개")

    # 4) 본문 추출 시도 — 셀렉터 첫 후보로 첫 글의 상세페이지에 접속해 본문 컨테이너 후보 보고
    if matches:
        best_sel, _ = matches[0]
        rows = soup.select(best_sel)
        if rows:
            first = rows[0]
            link = first.select_one("a[href]")
            if link and link.get("href") and not link.get("href", "").startswith("javascript:"):
                from urllib.parse import urljoin
                detail_url = urljoin(site.base_url + "/", link["href"])
                print(f"\n--- 첫 글 상세페이지: {detail_url}")
                if site.requires_js and js_renderer is not None:
                    detail_html = js_renderer.fetch(detail_url)
                    if detail_html is None:
                        print("  detail fetch failed (JS renderer)")
                        return
                    detail_soup = BeautifulSoup(detail_html, "lxml")
                    print(f"  JS 렌더 완료 size={len(detail_html)}")
                else:
                    detail_res = get(session, detail_url, encoding=site.encoding)
                    if detail_res is None:
                        print("  detail fetch failed")
                        return
                    detail_soup = BeautifulSoup(detail_res.text, "lxml")
                    print(f"  HTTP {detail_res.status_code} size={len(detail_res.text)}")
                # 본문 컨테이너 후보
                print("  본문 컨테이너 후보:")
                body_seen = set()
                for tag in detail_soup.find_all(["div", "article", "section"]):
                    cls = " ".join(tag.get("class") or [])
                    tid = tag.get("id") or ""
                    attr_text = (cls + " " + tid).lower()
                    if not any(k in attr_text for k in ("view", "cont", "body", "article", "detail")):
                        continue
                    sig = f"{tag.name}:{cls}:{tid}"
                    if sig in body_seen:
                        continue
                    body_seen.add(sig)
                    text_len = len(tag.get_text(" ", strip=True))
                    if text_len < 50:
                        continue
                    print(f"    <{tag.name} class={cls!r} id={tid!r}> 텍스트 {text_len}자")


def main() -> int:
    session = make_session()
    needs_js = any(s.requires_js for s in SITES)
    js_ctx = None
    if needs_js:
        try:
            from .js_fetcher import JsRenderer
            js_ctx = JsRenderer()
            js_ctx.__enter__()
            print("(JS 렌더러 준비 완료 — Playwright Chromium)")
        except Exception as exc:  # noqa: BLE001
            print(f"(JS 렌더러 초기화 실패: {type(exc).__name__}: {exc} — JS 사이트는 스킵됨)")
            js_ctx = None

    try:
        for site in SITES:
            try:
                renderer = js_ctx if site.requires_js else None
                inspect_site(session, site, js_renderer=renderer)
            except Exception as exc:  # noqa: BLE001
                print(f"[{site.name}] 진단 중 예외: {type(exc).__name__}: {exc}")
    finally:
        if js_ctx is not None:
            js_ctx.__exit__(None, None, None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
