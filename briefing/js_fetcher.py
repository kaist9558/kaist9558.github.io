"""JS 렌더링 사이트용 헤드리스 브라우저 페치 (Playwright Chromium).

`Site.requires_js=True` 인 사이트는 정적 HTTP로 글 목록이 안 잡히므로
Playwright로 페이지를 렌더링한 뒤 `page.content()` 의 결과 HTML을 사용한다.

봇 차단 우회 — 한국 정부 사이트는 일부 anti-bot 검사를 수행하므로:
1) 진짜 Chrome User-Agent로 위장 (커스텀 봇 UA 미사용)
2) `navigator.webdriver` 플래그 숨기기 (Playwright의 기본 노출 차단)
3) goto 타임아웃을 60초로 (러너가 비-한국 IP라 느릴 수 있음)
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)

# 진짜 Chrome처럼 보이는 UA — Playwright의 기본 'HeadlessChrome' 문자열을 덮어씀.
REAL_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# navigator.webdriver를 undefined로 만들고, 일부 자동화 탐지 신호 제거.
STEALTH_INIT_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['ko-KR', 'ko', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
"""

DEFAULT_GOTO_TIMEOUT_MS = 60_000
NETWORK_IDLE_TIMEOUT_MS = 40_000  # 추가 AJAX가 늦게 오는 KR gov SPA 대응
WAIT_SELECTOR_TIMEOUT_MS = 10_000
POST_IDLE_GRACE_MS = 3_000  # networkidle 후에도 다음 XHR 한 번 더 기다림


class JsRenderer:
    """Headless Chromium 컨텍스트. with 문으로 사용."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._context = None
        self.last_error: Optional[str] = None

    def __enter__(self) -> "JsRenderer":
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        self._context = self._browser.new_context(
            user_agent=REAL_BROWSER_UA,
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 1280, "height": 1024},
            extra_http_headers={
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,*/*;q=0.8"
                ),
            },
        )
        self._context.add_init_script(STEALTH_INIT_JS)
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
        """렌더링된 페이지 HTML 반환. 실패 시 None (last_error에 사유 기록).

        부수 효과: self.last_final_url에 최종 URL(리다이렉트 후) 기록.
        """
        if self._context is None:
            raise RuntimeError("JsRenderer must be used as a context manager")

        self.last_error = None
        self.last_final_url: Optional[str] = None
        page = self._context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=DEFAULT_GOTO_TIMEOUT_MS)
            try:
                page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT_MS)
            except Exception:  # noqa: BLE001
                log.debug("networkidle timeout for %s — proceeding anyway", url)
            # networkidle 후 한 번 더 grace — 마지막 XHR이 살짝 늦게 시작했을 때 대비
            try:
                page.wait_for_timeout(POST_IDLE_GRACE_MS)
            except Exception:  # noqa: BLE001
                pass
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=WAIT_SELECTOR_TIMEOUT_MS)
                except Exception:  # noqa: BLE001
                    log.warning("wait_selector %r not found on %s", wait_selector, url)
            self.last_final_url = page.url
            return page.content()
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
            self.last_error = err
            log.warning("[js_fetcher] %s 실패: %s", url, err)
            return None
        finally:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass
