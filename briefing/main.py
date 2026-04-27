from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from . import hikorea, publisher, scraper, storage, summarizer  # noqa: E402
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

    log.info("Step 1/3: scraping press releases")
    articles = scraper.fetch_all()
    log.info("  fetched %d candidate articles (after keyword filter)", len(articles))

    with storage.connect() as conn:
        for art in articles:
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

        log.info("Step 2/3: monitoring HiKorea attachments")
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

    log.info(
        "Step 3/3: publishing GitHub Issue (articles=%d, hikorea=%d)",
        len(article_briefings),
        len(hikorea_briefings),
    )
    if not article_briefings and not hikorea_briefings:
        log.info("새 업데이트가 없지만, 모니터링 정상 동작 확인용으로 빈 브리핑을 게시합니다.")

    if dry_run:
        title, body = publisher.render_markdown(
            articles=article_briefings,
            hikorea_changes=hikorea_briefings,
        )
        print("=" * 60)
        print("TITLE:", title)
        print("=" * 60)
        print(body)
        return 0

    ok = publisher.publish(
        articles=article_briefings,
        hikorea_changes=hikorea_briefings,
    )
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
