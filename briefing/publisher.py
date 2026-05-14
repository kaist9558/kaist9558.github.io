from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime

import requests

from .config import KST, SITES

log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


@dataclass
class ArticleBriefing:
    site: str
    title: str
    url: str
    summary: str
    published: datetime | None


@dataclass
class HikoreaBriefing:
    target_label: str
    file_name: str
    page_url: str
    change_summary: str
    is_new_file: bool


def _site_order() -> list[str]:
    return [s.name for s in SITES]


def _site_list_urls() -> dict[str, str]:
    return {s.name: s.list_url for s in SITES}


def render_markdown(
    *,
    articles: list[ArticleBriefing],
    all_new_titles: dict[str, list[tuple[str, str]]] | None = None,
    scrape_errors: list[tuple[str, str]] | None = None,
) -> tuple[str, str]:
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    title = f"[일일 브리핑] 이민·비자 정책 동향 ({today})"

    site_order = _site_order()
    # 출처 표기는 도메인명만(서비스명) — 본문 어디서도 표시 텍스트와 href가
    # 어긋난 anchor (기업 메일 필터의 피싱 휴리스틱 트리거)를 만들지 않는다.
    sources_line = " · ".join(site_order)

    lines: list[str] = [
        "# 일일 이민·비자 정책 브리핑",
        "",
        f"- **날짜**: {today}",
        f"- **수집 시각**: {now.strftime('%Y-%m-%d %H:%M KST')}",
        f"- **출처**: {sources_line}",
        "",
        "---",
        "",
        "## 📌 오늘의 핵심",
        "",
    ]

    articles_by_site: dict[str, list[ArticleBriefing]] = {name: [] for name in site_order}
    for a in articles:
        articles_by_site.setdefault(a.site, []).append(a)

    # 모든 링크는 Markdown autolink 문법(<url>)으로 통일 →
    # 렌더링 결과의 visible text 와 href 가 동일해, 기업 메일 필터의
    # "anchor text != href" 미스매치 휴리스틱에 걸리지 않는다.
    for name in site_order:
        lines.append(f"### {name}")
        lines.append("")
        site_articles = articles_by_site.get(name, [])
        if site_articles:
            for a in site_articles:
                summary = (a.summary or "").strip() or "(요약 없음)"
                lines.append(f"> **{a.title}**")
                lines.append(">")
                lines.append(f"> <{a.url}>")
                lines.append(">")
                for sline in summary.splitlines():
                    sline = sline.strip()
                    if sline:
                        lines.append(f"> {sline}")
                lines.append("")
        else:
            lines.append("> 오늘 관련 게시물 없음")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 📰 그날 올라온 새 글 전체")
    lines.append("")

    all_new_titles = all_new_titles or {}
    for name in site_order:
        entries = all_new_titles.get(name, [])
        lines.append(f"### {name} ({len(entries)}건)")
        lines.append("")
        if entries:
            for idx, (t, u) in enumerate(entries, start=1):
                lines.append(f"{idx}. {t}")
                lines.append(f"   <{u}>")
                lines.append("")
        else:
            lines.append("_새 글 없음_")
        lines.append("")

    if scrape_errors:
        lines.append("---")
        lines.append("")
        lines.append("## ⚠️ 모니터링 경고")
        lines.append("")
        for site, msg in scrape_errors:
            lines.append(f"- **{site}**: {msg}")
        lines.append("")

    return title, "\n".join(lines).rstrip() + "\n"


def publish(
    *,
    articles: list[ArticleBriefing],
    all_new_titles: dict[str, list[tuple[str, str]]] | None = None,
    scrape_errors: list[tuple[str, str]] | None = None,
) -> bool:
    repo = os.getenv("GITHUB_REPOSITORY")
    token = os.getenv("GITHUB_TOKEN")

    if not repo or not token:
        log.error(
            "GITHUB_REPOSITORY / GITHUB_TOKEN 환경변수가 설정되지 않았습니다. "
            "GitHub Actions에서는 자동 주입되며, 로컬 테스트는 --dry-run을 사용하세요."
        )
        return False

    title, body = render_markdown(
        articles=articles,
        all_new_titles=all_new_titles,
        scrape_errors=scrape_errors,
    )

    url = f"{GITHUB_API}/repos/{repo}/issues"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload: dict = {"title": title, "body": body}

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=30)
        res.raise_for_status()
    except requests.RequestException as exc:
        log.exception("GitHub Issue 생성 실패: %s", exc)
        if exc.response is not None:
            log.error("응답 본문: %s", exc.response.text[:500])
        return False

    issue = res.json()
    log.info(
        "GitHub Issue 생성 완료: #%s %s",
        issue.get("number"),
        issue.get("html_url"),
    )
    return True
