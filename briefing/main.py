from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from . import cleanup, hikorea, publisher, scraper, storage, summarizer  # noqa: E402
from .config import ensure_dirs  # noqa: E402

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("briefing")


def run(*, dry_run: bool = False) -> int:
    ensure_dirs()

    article_briefings: list[publisher.ArticleBriefing] = []
    seen_urls: set[tuple[str, str]] = set()

    log.info("Step 1/4: scraping press releases")
    scrape_result = scraper.fetch_all()
    log.info(
        "  fetched %d matched / %d unmatched candidates / %d errors",
        len(scrape_result.articles),
        len(scrape_result.unmatched_candidates),
        len(scrape_result.errors),
    )

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

        log.info("Step 2/4: monitoring HiKorea attachments")
        hikorea_briefings: list[publisher.HikoreaBriefing] = []
        changes = hikorea.check_all(conn)
        log.info("  detected %d file changes", len(changes))

        for ch in changes:
            change_summary = summarizer.summarize_diff(
                file_name=ch.file_name,
                old_text=ch.old_text,
                new_text=ch.new_text,
            )
            hikorea_briefings.append(
                publisher.HikoreaBriefing(
                    target_label=ch.target_label,
                    file_name=ch.file_name,
                    page_url=ch.page_url,
                    change_summary=change_summary,
                    is_new_file=ch.old_path is None,
                )
            )

    log.info("Step 3/4: scanning unmatched titles for keyword candidates")
    keyword_candidates_md = ""
    if scrape_result.unmatched_candidates:
        keyword_candidates_md = summarizer.suggest_keywords(
            scrape_result.unmatched_candidates
        )
        log.info(
            "  keyword suggestions: %s",
            "found" if keyword_candidates_md else "none",
        )

    log.info(
        "Step 4/4: publishing GitHub Issue (articles=%d, hikorea=%d, errors=%d, candidates=%s)",
        len(article_briefings),
        len(hikorea_briefings),
        len(scrape_result.errors),
        "yes" if keyword_candidates_md else "no",
    )

    if dry_run:
        title, body = publisher.render_markdown(
            articles=article_briefings,
            hikorea_changes=hikorea_briefings,
            scrape_errors=scrape_result.errors,
            keyword_candidates_md=keyword_candidates_md,
        )
        print("=" * 60)
        print("TITLE:", title)
        print("=" * 60)
        print(body)
        return 0

    ok = publisher.publish(
        articles=article_briefings,
        hikorea_changes=hikorea_briefings,
        scrape_errors=scrape_result.errors,
        keyword_candidates_md=keyword_candidates_md,
    )

    # 오래된 브리핑 Issue 자동 close (기본 30일)
    if ok:
        try:
            keep_days = int(os.getenv("ISSUE_KEEP_DAYS", "30"))
            n_closed = cleanup.close_old_briefings(days=keep_days)
            if n_closed:
                log.info("auto-closed %d old briefing issue(s)", n_closed)
        except Exception:  # noqa: BLE001
            log.exception("issue cleanup failed (non-fatal)")

    return 0 if ok else 1


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
