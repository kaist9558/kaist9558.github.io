from __future__ import annotations

import logging
import os
from functools import lru_cache

import anthropic

from .config import CLAUDE_MAX_TOKENS, CLAUDE_MODEL

log = logging.getLogger(__name__)

ARTICLE_SYSTEM = """당신은 한국 이민·비자·외국인 정책을 추적하는 정책 연구원의 일일 브리핑을 돕는 보조원입니다.
정부 부처 보도자료를 받아 다음 작업을 수행하십시오.

작업
1) 분류: 이 보도자료가 이민·비자·외국인·국적·체류·재외동포·외국인 인재 정책과 직접 관련 있는지 판단하십시오.
2) 요약: 관련 있다면, 정책 연구원이 30초 안에 핵심을 파악할 수 있도록 한국어로 2~3문장 요약을 작성하십시오.
   - 사실 위주, 과장·추측 금지
   - 시행 시점·대상·달라진 점이 있으면 우선 포함
   - 출처 인용 금지(메일에서 별도 링크로 표시됨)

출력 형식 (반드시 이 두 줄만, 다른 텍스트 금지)
RELEVANT: yes|no
SUMMARY: <2~3문장 요약 또는 'N/A'>
"""


@lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=api_key)


def _system_with_cache(text: str) -> list[dict]:
    # Single text block with cache_control so the persona stays cached across calls.
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def _extract_text(message) -> str:
    return "".join(b.text for b in message.content if getattr(b, "type", None) == "text")


def classify_and_summarize(title: str, body: str) -> tuple[bool, str]:
    """Returns (is_relevant, summary)."""
    snippet = (body or "").strip()[:3500]
    user = f"제목: {title}\n\n본문:\n{snippet or '(본문 없음)'}"
    try:
        msg = _client().messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            system=_system_with_cache(ARTICLE_SYSTEM),
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.APIError:
        log.exception("Claude classify_and_summarize failed for: %s", title)
        return True, "(요약 생성 실패 — 원문 링크를 확인하세요.)"

    text = _extract_text(msg).strip()
    relevant = False
    summary = ""
    for line in text.splitlines():
        line = line.strip()
        if line.upper().startswith("RELEVANT:"):
            relevant = "yes" in line.lower()
        elif line.upper().startswith("SUMMARY:"):
            summary = line.split(":", 1)[1].strip()
    if not summary:
        summary = text  # fallback to whole response
    return relevant, summary
