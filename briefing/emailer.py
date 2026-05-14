from __future__ import annotations

import logging
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

log = logging.getLogger(__name__)


# 발신 본문/헤더에서 GitHub 식별자(repo URL, raw.githubusercontent, github.io 등)가
# 새어나가지 않도록 차단하기 위한 패턴.
_GITHUB_PATTERN = re.compile(
    r"https?://[\w.-]*github(?:usercontent)?\.(?:com|io)/[^\s\"'<>)]*",
    re.IGNORECASE,
)


def _strip_github_references(text: str) -> str:
    """본문에 우연히 박힌 github.com/github.io URL을 제거.

    수신자에게 워크플로우의 GitHub 저장소 위치가 노출되지 않도록 하기 위함.
    """
    return _GITHUB_PATTERN.sub("(링크 제거됨)", text)


def _render_html(markdown_body: str) -> str:
    """Markdown → HTML. 헤딩/링크/인용블록/리스트만 깔끔하게 렌더링."""
    try:
        import markdown as md
    except ImportError:
        log.warning("markdown 라이브러리 미설치 — plain text 만으로 전송")
        return "<pre>" + markdown_body.replace("<", "&lt;").replace(">", "&gt;") + "</pre>"

    body_html = md.markdown(
        markdown_body,
        extensions=["extra", "sane_lists", "nl2br"],
    )
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
         color: #222; line-height: 1.55; max-width: 720px; margin: 24px auto; padding: 0 16px; }}
  h1 {{ font-size: 22px; border-bottom: 2px solid #333; padding-bottom: 8px; }}
  h2 {{ font-size: 18px; margin-top: 32px; padding-bottom: 6px; border-bottom: 1px solid #ddd; }}
  h3 {{ font-size: 16px; margin-top: 20px; color: #1a1a1a; }}
  blockquote {{ border-left: 3px solid #2563eb; background: #f5f8ff; margin: 8px 0;
                padding: 10px 14px; border-radius: 0 4px 4px 0; }}
  a {{ color: #2563eb; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  hr {{ border: none; border-top: 1px solid #ddd; margin: 20px 0; }}
  ol, ul {{ padding-left: 22px; }}
  li {{ margin: 3px 0; }}
  code {{ background: #f3f3f3; padding: 1px 4px; border-radius: 3px; font-size: 90%; }}
</style>
</head>
<body>
{body_html}
</body>
</html>
"""


def _sender() -> str | None:
    """Sender 주소 — 기존 EMAIL_SENDER 우선, 새 네이밍(SMTP_FROM/SMTP_USER) fallback."""
    return os.getenv("EMAIL_SENDER") or os.getenv("SMTP_FROM") or os.getenv("SMTP_USER")


def _password() -> str | None:
    return os.getenv("EMAIL_PASSWORD") or os.getenv("SMTP_PASSWORD")


def _recipient() -> str | None:
    """수신자 — workflow_dispatch 등에서 1회성으로 덮어쓰기 위한 BRIEFING_RECIPIENT_EMAIL 우선."""
    return os.getenv("BRIEFING_RECIPIENT_EMAIL") or os.getenv("EMAIL_RECEIVER")


def is_configured() -> bool:
    """이메일 발송에 필요한 최소 환경변수가 모두 설정됐는지 확인.

    기존 운영 시 사용하던 EMAIL_SENDER / EMAIL_PASSWORD / EMAIL_RECEIVER 그대로 동작하며,
    새 네이밍(SMTP_USER / SMTP_PASSWORD / BRIEFING_RECIPIENT_EMAIL)도 fallback 으로 지원.
    """
    return bool(_sender() and _password() and _recipient())


def send(*, subject: str, markdown_body: str) -> bool:
    """SMTP로 브리핑 이메일 발송.

    필수 env (택1):
      - 레거시: EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER
      - 신규  : SMTP_USER, SMTP_PASSWORD, BRIEFING_RECIPIENT_EMAIL (+ 선택 SMTP_FROM)
    공통: SMTP_HOST(기본 smtp.gmail.com), SMTP_PORT(기본 587), SMTP_USE_SSL("1"이면 465 SMTPS)
    선택: SMTP_FROM_NAME (발신자 표시명)

    수신자에게 GitHub 저장소 위치가 노출되지 않도록:
      - From/Reply-To 헤더에 github 도메인을 쓰지 않음
      - Message-ID 도메인을 sender 도메인으로 고정
      - 본문/제목에서 github.com/github.io URL을 자동으로 제거
    """
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = _sender()
    password = _password()
    raw_recipients = _recipient()
    if not (user and password and raw_recipients):
        log.error(
            "이메일 발송 자격 증명 누락 — EMAIL_SENDER/EMAIL_PASSWORD/EMAIL_RECEIVER "
            "(또는 SMTP_USER/SMTP_PASSWORD/BRIEFING_RECIPIENT_EMAIL) 를 설정하세요."
        )
        return False
    use_ssl = os.getenv("SMTP_USE_SSL", "0") == "1"

    sender_addr = os.getenv("SMTP_FROM") or user
    sender_name = os.getenv("SMTP_FROM_NAME") or "이민·비자 정책 브리핑"
    recipients = [r.strip() for r in raw_recipients.split(",") if r.strip()]
    if not recipients:
        log.error("수신자 주소가 비어 있습니다.")
        return False

    safe_markdown = _strip_github_references(markdown_body)
    safe_subject = _strip_github_references(subject)
    html_body = _render_html(safe_markdown)

    msg = EmailMessage()
    msg["Subject"] = safe_subject
    msg["From"] = formataddr((sender_name, sender_addr))
    msg["To"] = ", ".join(recipients)
    # Reply-To 를 발신자와 동일하게 설정해 두지 않으면 일부 클라이언트가 자동 추론
    # 과정에서 시스템 도메인(노출 위험)을 채울 수 있다.
    msg["Reply-To"] = sender_addr
    # Message-ID 의 도메인을 발신 주소 도메인으로 고정해 헤더에 github 흔적이 남지 않게 함.
    sender_domain = sender_addr.split("@", 1)[-1] if "@" in sender_addr else "localhost"
    msg["Message-ID"] = make_msgid(domain=sender_domain)

    msg.set_content(safe_markdown)  # text/plain fallback
    msg.add_alternative(html_body, subtype="html")

    try:
        if use_ssl:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as smtp:
                smtp.login(user, password)
                smtp.send_message(msg, from_addr=sender_addr, to_addrs=recipients)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
                smtp.login(user, password)
                smtp.send_message(msg, from_addr=sender_addr, to_addrs=recipients)
    except (smtplib.SMTPException, OSError) as exc:
        log.exception("SMTP 전송 실패: %s", exc)
        return False

    log.info(
        "브리핑 이메일 전송 완료: to=%s, subject=%s",
        ", ".join(recipients),
        safe_subject,
    )
    return True
