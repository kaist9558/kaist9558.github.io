"""JS 렌더링 사이트용 헤드리스 브라우저 페치 (Playwright Chromium).

`Site.requires_js=True` 인 사이트는 정적 HTTP로 글 목록이 안 잡히므로
Playwright로 페이지를 렌더링한 뒤 `page.content()` 의 결과 HTML을 사용한다.
브라우저는 with 블록 동안 한 번만 띄워서 여러 URL에 재사용한다.
"""
from __future__ import annotations

import logging
from typing import Optional

from .config import USER_AGENT

log = logging.getLogger(__name__)

DEFAULT_GOTO_TIMEOUT_MS = 30_000
NETWORK_IDLE_TIMEOUT_MS = 15_000
WAIT_SELECTOR_TIMEOUT_MS = 10_000


class JsRenderer:
    """Headless Chromium 컨텍스트. with 문으로 사용한다.

    Example:
        with JsRenderer() as renderer:
            html = renderer.fetch("https://...")
    """

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._context = None

    def __enter__(self) -> "JsRenderer":
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            user_agent=USER_AGENT,
            locale="ko-KR",
            extra_http_headers={"Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"},
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        for closer in (self._context, self._browser):
            if closer is not None:
                try:
                    closer.close()
                except Exception:  # noqa: BLE001
                    pass
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:  # noqa: BLE001
                pass

    def fetch(self, url: str, *, wait_selector: Optional[str] = None) -> Optional[str]:
        """렌더링된 페이지 HTML 반환. 실패 시 None."""
        if self._context is None:
            raise RuntimeError("JsRenderer must be used as a context manager")

        page = self._context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=DEFAULT_GOTO_TIMEOUT_MS)
            try:
                page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT_MS)
            except Exception:  # noqa: BLE001
                # networkidle 도달 실패해도 렌더링된 만큼은 사용
                log.debug("networkidle timeout for %s — proceeding anyway", url)
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=WAIT_SELECTOR_TIMEOUT_MS)
                except Exception:  # noqa: BLE001
                    log.warning("wait_selector %r not found on %s", wait_selector, url)
            return page.content()
        except Exception as exc:  # noqa: BLE001
            log.warning("[js_fetcher] %s 실패: %s", url, exc)
            return None
        finally:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass
