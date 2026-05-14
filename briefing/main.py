from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from . import cleanup, emailer, publisher, scraper, storage, summarizer, tracked_pages  # noqa: E402
from .config import SITES, ensure_dirs  # noqa: E402

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("briefing")


def run(*, dry_run: bool = False) -> int:
    ensure_dirs()

    site_names = [s.name for s in SITES]
    article_briefings: list[publisher.ArticleBriefing] = []
    all_new_titles: dict[str, list[tuple[str, str]]] = {name: [] for name in site_names}
    seen_urls: set[tuple[str, str]] = set()

    log.info("Step 1/3: scraping press releases")
    scrape_result = scraper.fetch_all()
    log.info(
        "  fetched %d matched / %d unmatched candidates / %d errors",
        len(scrape_result.articles),
        len(scrape_result.unmatched_candidates),
        len(scrape_result.errors),
    )

    # "그날 올라온 새 글 전체" — 관련성 무관하게 윈도우 내 모든 새 글을 사이트별로 모은다.
    for art in scrape_result.articles:
        all_new_titles.setdefault(art.site, []).append((art.title, art.url))
    for site, title, url in scrape_result.unmatched_candidates:
        all_new_titles.setdefault(site, []).append((title, url))

    log.info("Step 2/3: classifying & summarizing immigration-relevant articles")
    tracked_changes: list[tracked_pages.TrackedPageChange] = []
    with storage.connect() as conn:
        for art in scrape_result.articles:
            key = (art.site, art.url)
            if key in seen_urls or storage.is_article_seen(conn, art.site, art.url):
                continue
            seen_urls.add(key)

            relevant, summary = summarizer.classify_and_summarize(art.title, art.content)
            storage.mark_article_seen(conn, art.site, art.url, art.title)
            if not relevant:
                continue

            article_briefings.append(
                publisher.ArticleBriefing(
                    site=art.site,
                    title=art.title,
                    url=art.url,
                    summary=summary,
                    published=art.published,
                )
            )

        # 추적 페이지(단일 글 갱신) 검사 — 같은 connection 안에서 수행해 트랜잭션 일관성.
        tracked_changes = tracked_pages.check_all(conn)
        log.info("  tracked-page changes detected: %d", len(tracked_changes))

    title, body = publisher.render_markdown(
        articles=article_briefings,
        all_new_titles=all_new_titles,
        scrape_errors=scrape_result.errors,
        tracked_changes=tracked_changes,
    )

    if dry_run:
        print("=" * 60)
        print("TITLE:", title)
        print("=" * 60)
        print(body)
        return 0

    # 채널 선택:
    #   - 이메일 자격 증명(EMAIL_SENDER/EMAIL_PASSWORD + 수신자)이 모두 있으면 이메일 발송.
    #   - BRIEFING_PUBLISH_ISSUE 기본값은 이메일 활성화 시 "0", 아니면 "1".
    #     명시 지정이 우선 (예: BRIEFING_PUBLISH_ISSUE=1 로 이메일과 동시 발행 가능).
    email_enabled = emailer.is_configured()
    publish_issue_default = "0" if email_enabled else "1"
    publish_issue = os.getenv("BRIEFING_PUBLISH_ISSUE", publish_issue_default) == "1"

    if not (email_enabled or publish_issue):
        log.error(
            "전송 채널이 하나도 활성화되지 않았습니다. "
            "EMAIL_SENDER/EMAIL_PASSWORD + 수신자 또는 BRIEFING_PUBLISH_ISSUE=1 중 "
            "최소 하나 이상을 설정하세요."
        )
        return 1

    channels = []
    if email_enabled:
        channels.append("email")
    if publish_issue:
        channels.append("github_issue")
    log.info(
        "Step 3/3: delivering briefing via %s (relevant=%d, total_new=%d, errors=%d)",
        "+".join(channels),
        len(article_briefings),
        sum(len(v) for v in all_new_titles.values()),
        len(scrape_result.errors),
    )

    email_ok = emailer.send(subject=title, markdown_body=body) if email_enabled else True
    issue_ok = True
    if publish_issue:
        issue_ok = publisher.publish(
            articles=article_briefings,
            all_new_titles=all_new_titles,
            scrape_errors=scrape_result.errors,
            tracked_changes=tracked_changes,
        )
        # 오래된 브리핑 Issue 자동 close (기본 30일) — Issue 채널을 쓸 때만 의미가 있음.
        if issue_ok:
            try:
                keep_days = int(os.getenv("ISSUE_KEEP_DAYS", "30"))
                n_closed = cleanup.close_old_briefings(days=keep_days)
                if n_closed:
                    log.info("auto-closed %d old briefing issue(s)", n_closed)
            except Exception:  # noqa: BLE001
                log.exception("issue cleanup failed (non-fatal)")

    return 0 if (email_ok and issue_ok) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="이민·비자 정책 일일 브리핑")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="발송하지 않고 본문만 stdout 출력 (이메일/Issue 양쪽 모두 skip)",
    )
    args = parser.parse_args()
    try:
        return run(dry_run=args.dry_run)
    except Exception:  # noqa: BLE001
        log.exception("브리핑 작업이 예외로 종료되었습니다.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
