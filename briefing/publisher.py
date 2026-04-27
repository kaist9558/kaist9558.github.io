from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime

import requests

from .config import KST

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


def _format_date(d: datetime | None) -> str:
    return d.strftime("%Y-%m-%d") if d else "날짜 미상"


def render_markdown(
    *,
    articles: list[ArticleBriefing],
    hikorea_changes: list[HikoreaBriefing],
) -> tuple[str, str]:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    title = f"[일일 브리핑] 이민·비자 정책 동향 ({today})"

    lines: list[str] = [
        f"_생성: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}_",
        "",
        "## 부처 보도자료",
    ]
    if articles:
        for a in articles:
            lines.append(f"### [{a.site}] [{a.title}]({a.url})")
            lines.append(f"_{_format_date(a.published)}_")
            lines.append("")
            lines.append(a.summary)
            lines.append("")
    else:
        lines.append("> 오늘 새로 감지된 관련 보도자료가 없습니다.")
        lines.append("")

    lines.append("## 하이코리아 공지 변경")
    if hikorea_changes:
        for c in hikorea_changes:
            tag = "🆕 신규 파일" if c.is_new_file else "✏️ 변경 감지"
            lines.append(f"### {tag} · [{c.target_label}] [{c.file_name}]({c.page_url})")
            lines.append("")
            lines.append("```")
            lines.append(c.change_summary)
            lines.append("```")
            lines.append("")
    else:
        lines.append("> 하이코리아 추적 게시글에 변동 사항이 없습니다.")
        lines.append("")

    lines.append("---")
    lines.append("_자동 생성 — `kaist9558/kaist9558.github.io` · briefing_")

    return title, "\n".join(lines)


def publish(
    *,
    articles: list[ArticleBriefing],
    hikorea_changes: list[HikoreaBriefing],
) -> bool:
    repo = os.getenv("GITHUB_REPOSITORY")  # auto-set in Actions: "owner/repo"
    token = os.getenv("GITHUB_TOKEN")

    if not repo or not token:
        log.error(
            "GITHUB_REPOSITORY / GITHUB_TOKEN 환경변수가 설정되지 않았습니다. "
            "GitHub Actions에서는 자동 주입되며, 로컬 테스트는 --dry-run을 사용하세요."
        )
        return False

    title, body = render_markdown(articles=articles, hikorea_changes=hikorea_changes)

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
