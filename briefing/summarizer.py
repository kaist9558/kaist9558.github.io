from __future__ import annotations

import difflib
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

DIFF_SYSTEM = """당신은 한국 이민·비자·외국인 정책 변경을 추적하는 정책 연구원을 돕는 보조원입니다.
같은 행정 문서의 두 버전(이전본/신규본)을 비교한 결과를 받아, 정책 연구원이 즉시 활용할 수 있는 한국어 변경 요약을 작성하십시오.

작성 원칙
- 추가/삭제/수정된 핵심 조항을 누락 없이 정리하십시오.
- 단순 표현 변경(맞춤법·줄바꿈 등)은 제외하고 의미 있는 변경만 포함하십시오.
- 항목별 불릿(- )으로 작성하고, 항목당 한 문장으로 압축하십시오.
- 불확실한 부분은 '확인 필요'로 명시하십시오.
- 출력은 변경 요약 본문만 포함하십시오. 머리말·맺음말 금지.
"""

KEYWORD_SUGGEST_SYSTEM = """당신은 한국 이민·비자·외국인 정책 연구원의 키워드 사전 관리를 돕는 보조원입니다.
정부 부처 보도자료 제목 목록을 받습니다. 이 중 **이민·비자·외국인·국적·체류·재외동포·외국인 인재 정책과 직접 관련 있다고 판단되는 제목만** 골라내십시오.

판단 기준
- 핵심 정책 (출입국·체류·국적·외국인 행정·재외동포·외국인 노동·외국인 학생 등): 포함
- 단순 행사·홍보·인사 발령·일반 사회 정책: 제외

출력 형식 (관련 있는 제목 1개당 정확히 한 줄, 다른 텍스트 금지)
- "<제목>" → 추천 키워드: `<단어>` (한 줄 사유)

관련 항목이 하나도 없으면 출력은 정확히 다음 한 줄:
NONE
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


def _build_unified_diff(old_text: str, new_text: str, *, max_chars: int = 12000) -> str:
    diff = difflib.unified_diff(
        old_text.splitlines(),
        new_text.splitlines(),
        fromfile="이전본",
        tofile="신규본",
        n=2,
        lineterm="",
    )
    out = "\n".join(diff)
    return out[:max_chars]


def summarize_diff(*, file_name: str, old_text: str | None, new_text: str | None) -> str:
    if old_text is None and new_text is None:
        return "텍스트 추출이 불가능한 파일 형식입니다(예: HWP). 파일을 직접 확인하세요."
    if old_text is None:
        # First time we have text; just summarize new content.
        snippet = (new_text or "")[:8000]
        user = (
            f"파일명: {file_name}\n\n"
            "이전본은 보관되어 있지 않습니다. 신규본의 핵심 조항을 한국어 불릿으로 요약하십시오.\n\n"
            f"--- 신규본 본문 ---\n{snippet}"
        )
    elif new_text is None:
        return "신규본의 텍스트 추출에 실패했습니다. 파일을 직접 확인하세요."
    else:
        diff_text = _build_unified_diff(old_text, new_text)
        if not diff_text.strip():
            return "텍스트상 의미 있는 변경이 감지되지 않았습니다(파일 메타데이터만 변경됐을 가능성)."
        user = (
            f"파일명: {file_name}\n\n"
            "아래는 이전본과 신규본의 unified diff 결과입니다. 의미 있는 변경만 한국어 불릿으로 정리하십시오.\n\n"
            f"--- DIFF ---\n{diff_text}"
        )

    try:
        msg = _client().messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            system=_system_with_cache(DIFF_SYSTEM),
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.APIError:
        log.exception("Claude summarize_diff failed for: %s", file_name)
        return "(변경 요약 생성 실패 — 파일을 직접 비교하세요.)"
    return _extract_text(msg).strip()


def suggest_keywords(candidates: list[tuple[str, str, str]], *, max_titles: int = 30) -> str:
    """키워드 미매칭 제목들 중 정책 관련성 있는 후보를 식별.

    candidates: list of (site_name, title, url)
    Returns: Markdown 불릿 형식 문자열 (관련 항목 없으면 빈 문자열).
    """
    if not candidates:
        return ""
    sample = candidates[:max_titles]
    lines = [f"- [{site}] {title}" for site, title, _ in sample]
    user = (
        "다음은 부처 보도자료 중 현재 키워드 사전(`이민/비자/외국인/...`)에는 안 걸렸지만 "
        "윈도우 안에 게시된 제목 목록입니다. 정책 관련성을 평가해주세요.\n\n"
        + "\n".join(lines)
    )
    try:
        msg = _client().messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=_system_with_cache(KEYWORD_SUGGEST_SYSTEM),
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.APIError:
        log.exception("Claude suggest_keywords failed")
        return ""
    text = _extract_text(msg).strip()
    if text == "NONE" or not text:
        return ""
    return text
