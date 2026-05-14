from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from . import cleanup, emailer, publisher, scraper, storage, summarizer  # noqa: E402
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

    log.info(
        "Step 3/3: publishing GitHub Issue (relevant=%d, total_new=%d, errors=%d)",
        len(article_briefings),
        sum(len(v) for v in all_new_titles.values()),
        len(scrape_result.errors),
    )

    title, body = publisher.render_markdown(
        articles=article_briefings,
        all_new_titles=all_new_titles,
        scrape_errors=scrape_result.errors,
    )

    if dry_run:
        print("=" * 60)
        print("TITLE:", title)
        print("=" * 60)
        print(body)
        return 0

    # 채널 선택:
    #   BRIEFING_RECIPIENT_EMAIL + SMTP_* 가 모두 설정되면 이메일로 발송 (GitHub 식별자 미노출).
    #   BRIEFING_PUBLISH_ISSUE 기본값: 이메일이 설정돼 있으면 "0"(Issue 미생성),
    #   아니면 "1"(기존 동작 그대로 Issue 생성). 명시적 지정이 우선.
    email_enabled = emailer.is_configured()
    publish_issue_default = "0" if email_enabled else "1"
    publish_issue = os.getenv("BRIEFING_PUBLISH_ISSUE", publish_issue_default) == "1"

    delivered_any = False
    issue_ok = True
    email_ok = True

    if email_enabled:
        email_ok = emailer.send(subject=title, markdown_body=body)
        delivered_any = delivered_any or email_ok

    if publish_issue:
        issue_ok = publisher.publish(
            articles=article_briefings,
            all_new_titles=all_new_titles,
            scrape_errors=scrape_result.errors,
        )
        delivered_any = delivered_any or issue_ok

        # 오래된 브리핑 Issue 자동 close (기본 30일) — Issue 채널을 쓸 때만 의미가 있음.
        if issue_ok:
            try:
                keep_days = int(os.getenv("ISSUE_KEEP_DAYS", "30"))
                n_closed = cleanup.close_old_briefings(days=keep_days)
                if n_closed:
                    log.info("auto-closed %d old briefing issue(s)", n_closed)
            except Exception:  # noqa: BLE001
                log.exception("issue cleanup failed (non-fatal)")

    if not (email_enabled or publish_issue):
        log.error(
            "전송 채널이 하나도 활성화되지 않았습니다. "
            "BRIEFING_RECIPIENT_EMAIL + SMTP_* 또는 BRIEFING_PUBLISH_ISSUE=1 중 하나 이상을 설정하세요."
        )
        return 1

    return 0 if (issue_ok and email_ok and delivered_any) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="이민·비자 정책 일일 브리핑")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="GitHub Issue를 생성하지 않고 본문만 출력",
    )
    args = parser.parse_args()
    try:
        return run(dry_run=args.dry_run)
    except Exception:  # noqa: BLE001
        log.exception("브리핑 작업이 예외로 종료되었습니다.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
