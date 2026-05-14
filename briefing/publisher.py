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


def _site_order() -> list[str]:
    return [s.name for s in SITES]


def _site_list_urls() -> dict[str, str]:
    return {s.name: s.list_url for s in SITES}


def _site_header(name: str, url: str | None) -> str:
    """### 섹션 헤더 — 사이트 목록 URL 이 있으면 markdown 링크로 감싼다.
    상세 article URL과 달리 list URL 은 게시판 첫 페이지라 기업 메일 보안 게이트
    웨이의 평판 검사에 잘 걸리지 않음. 사용자가 직접 클릭해 "정말 관련 글이 없는지"
    크로스체크 가능."""
    return f"### [{name}]({url})" if url else f"### {name}"


def render_markdown(
    *,
    articles: list[ArticleBriefing],
    all_new_titles: dict[str, list[tuple[str, str]]] | None = None,
    scrape_errors: list[tuple[str, str]] | None = None,
    tracked_changes: list | None = None,
) -> tuple[str, str]:
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    title = f"[일일 브리핑] 이민·비자 정책 동향 ({today})"

    site_order = _site_order()
    site_urls = _site_list_urls()
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

    # 각 항목 바로 아래에 URL 을 plain text 줄로 표기 → 수신자가 복사·붙여넣기로
    # 즉시 열 수 있음. Markdown 링크 문법은 쓰지 않아 "anchor 미스매치" 휴리스틱은
    # 회피 (visible text == href). 메일 클라이언트는 plain URL 을 자동 인식해
    # 클릭 가능하게 렌더하는 경우가 많지만, 보안 gateway 가 본문 링크를 차단해도
    # 텍스트로는 그대로 보이므로 복사 경로는 항상 유효.
    for name in site_order:
        lines.append(_site_header(name, site_urls.get(name)))
        lines.append("")
        site_articles = articles_by_site.get(name, [])
        if site_articles:
            for a in site_articles:
                summary = (a.summary or "").strip() or "(요약 없음)"
                lines.append(f"> **{a.title}**")
                lines.append(">")
                lines.append(f"> {a.url}")
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
        # 섹션 헤더에 사이트 list URL 하이퍼링크 + 건수 표기.
        url = site_urls.get(name)
        header_label = f"{name} ({len(entries)}건)"
        if url:
            lines.append(f"### [{header_label}]({url})")
        else:
            lines.append(f"### {header_label}")
        lines.append("")
        if entries:
            for idx, (t, u) in enumerate(entries, start=1):
                lines.append(f"{idx}. {t}")
                lines.append(f"   {u}")
                lines.append("")
        else:
            lines.append("_새 글 없음_")
        lines.append("")

    # 추적 페이지(고정 URL 단일 글) 의 첨부파일 갱신 알림.
    if tracked_changes:
        lines.append("---")
        lines.append("")
        lines.append("## 🔔 추적 페이지 갱신")
        lines.append("")
        for tc in tracked_changes:
            tag = "🆕 첫 추적" if tc.is_first else "✏️ 변경 감지"
            lines.append(f"### {tag} · [{tc.label}]({tc.url})")
            lines.append("")
            if tc.attachments:
                lines.append("> 첨부 파일:")
                for fname in tc.attachments:
                    lines.append(f"> - {fname}")
            else:
                lines.append("> (첨부 파일 메타 추출 실패 — 페이지 직접 확인 권장)")
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
    tracked_changes: list | None = None,
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
        tracked_changes=tracked_changes,
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
