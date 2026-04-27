from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from html import escape

from .config import (
    EMAIL_PASSWORD,
    EMAIL_RECEIVER,
    EMAIL_SENDER,
    KST,
    SMTP_HOST,
    SMTP_PORT,
)

log = logging.getLogger(__name__)


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


def _articles_html(articles: list[ArticleBriefing]) -> str:
    if not articles:
        return "<p style='color:#666'>오늘 새로 감지된 관련 보도자료가 없습니다.</p>"
    parts = ["<ul style='padding-left:18px'>"]
    for a in articles:
        parts.append(
            "<li style='margin-bottom:14px'>"
            f"<div><strong>[{escape(a.site)}]</strong> "
            f"<a href='{escape(a.url)}'>{escape(a.title)}</a> "
            f"<span style='color:#999;font-size:12px'>({_format_date(a.published)})</span></div>"
            f"<div style='margin-top:4px;color:#333'>{escape(a.summary)}</div>"
            "</li>"
        )
    parts.append("</ul>")
    return "".join(parts)


def _hikorea_html(changes: list[HikoreaBriefing]) -> str:
    if not changes:
        return "<p style='color:#666'>하이코리아 추적 게시글에 변동 사항이 없습니다.</p>"
    parts = ["<ul style='padding-left:18px'>"]
    for c in changes:
        tag = "신규 파일" if c.is_new_file else "변경 감지"
        parts.append(
            "<li style='margin-bottom:14px'>"
            f"<div><strong>[하이코리아 · {escape(c.target_label)}]</strong> "
            f"<span style='color:#c0392b'>({tag})</span> "
            f"<a href='{escape(c.page_url)}'>게시글 열기</a></div>"
            f"<div style='color:#555;font-size:13px;margin-top:2px'>파일: {escape(c.file_name)}</div>"
            f"<pre style='white-space:pre-wrap;background:#f6f8fa;padding:10px;"
            f"border-radius:4px;margin-top:6px'>{escape(c.change_summary)}</pre>"
            "</li>"
        )
    parts.append("</ul>")
    return "".join(parts)


def render_email(
    *,
    articles: list[ArticleBriefing],
    hikorea_changes: list[HikoreaBriefing],
) -> tuple[str, str, str]:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    subject = f"[일일 브리핑] 이민·비자 정책 동향 ({today})"

    plain_lines = [f"이민·비자 정책 일일 브리핑 ({today})", "", "■ 부처 보도자료"]
    if articles:
        for a in articles:
            plain_lines.append(f"- [{a.site}] {a.title} ({_format_date(a.published)})")
            plain_lines.append(f"  {a.summary}")
            plain_lines.append(f"  {a.url}")
    else:
        plain_lines.append("(없음)")
    plain_lines += ["", "■ 하이코리아 공지"]
    if hikorea_changes:
        for c in hikorea_changes:
            tag = "신규 파일" if c.is_new_file else "변경 감지"
            plain_lines.append(f"- [{c.target_label}] {c.file_name} ({tag})")
            plain_lines.append(f"  {c.page_url}")
            plain_lines.append(c.change_summary)
    else:
        plain_lines.append("(변동 없음)")

    body_text = "\n".join(plain_lines)

    body_html = f"""<!doctype html>
<html><body style="font-family:-apple-system,Segoe UI,Roboto,'Apple SD Gothic Neo',sans-serif;
                   color:#222;max-width:760px;margin:0 auto;padding:20px">
  <h2 style="border-bottom:2px solid #2c3e50;padding-bottom:6px">
    이민·비자 정책 일일 브리핑
    <span style="font-size:14px;color:#888;font-weight:normal">({today})</span>
  </h2>
  <h3 style="color:#2c3e50;margin-top:24px">부처 보도자료</h3>
  {_articles_html(articles)}
  <h3 style="color:#2c3e50;margin-top:24px">하이코리아 공지 변경</h3>
  {_hikorea_html(hikorea_changes)}
  <p style="color:#aaa;font-size:11px;margin-top:30px">
    자동 생성 — kaist9558/kaist9558.github.io · briefing
  </p>
</body></html>"""

    return subject, body_text, body_html


def send(subject: str, body_text: str, body_html: str) -> bool:
    if not (EMAIL_SENDER and EMAIL_PASSWORD and EMAIL_RECEIVER):
        log.error("이메일 환경변수가 설정되지 않았습니다.")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    msg.set_content(body_text)
    msg.add_alternative(body_html, subtype="html")

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls(context=context)
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
    except smtplib.SMTPException:
        log.exception("이메일 발송 실패")
        return False
    log.info("이메일 발송 성공: %s", EMAIL_RECEIVER)
    return True
