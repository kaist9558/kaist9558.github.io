from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import requests

log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
BRIEFING_TITLE_PREFIX = "[일일 브리핑]"


def close_old_briefings(*, days: int = 30) -> int:
    """`days`일 이상 지난 브리핑 Issue를 자동 close. 닫은 개수 반환."""
    repo = os.getenv("GITHUB_REPOSITORY")
    token = os.getenv("GITHUB_TOKEN")
    if not repo or not token:
        log.warning("cleanup skipped: GITHUB_REPOSITORY/GITHUB_TOKEN missing")
        return 0

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    closed = 0

    page = 1
    while True:
        list_url = f"{GITHUB_API}/repos/{repo}/issues"
        params = {"state": "open", "per_page": 100, "page": page, "sort": "created", "direction": "asc"}
        try:
            res = requests.get(list_url, headers=headers, params=params, timeout=30)
            res.raise_for_status()
        except requests.RequestException:
            log.exception("cleanup: list issues failed")
            return closed
        items = res.json()
        if not items:
            break

        for issue in items:
            # PR도 issues 엔드포인트로 잡히므로 제외
            if "pull_request" in issue:
                continue
            title = issue.get("title", "")
            if not title.startswith(BRIEFING_TITLE_PREFIX):
                continue
            created_at_str = issue.get("created_at")
            if not created_at_str:
                continue
            try:
                created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            except ValueError:
                continue
            if created_at >= cutoff:
                # sort=created/asc 이므로 이후 항목도 모두 cutoff 이내
                return closed

            number = issue["number"]
            patch_url = f"{GITHUB_API}/repos/{repo}/issues/{number}"
            try:
                res2 = requests.patch(
                    patch_url, headers=headers, json={"state": "closed"}, timeout=30
                )
                res2.raise_for_status()
                closed += 1
                log.info("cleanup: closed issue #%s (%s)", number, title)
            except requests.RequestException:
                log.exception("cleanup: failed to close #%s", number)

        if len(items) < 100:
            break
        page += 1

    return closed
