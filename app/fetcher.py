"""Page fetching layer.

`requests` by default (fast, cheap). Playwright is enabled per parser
(`requires_playwright = True`) or globally via WNE_PLAYWRIGHT_ENABLED, and is
imported lazily - the lightweight Docker image does not ship it.
"""

from __future__ import annotations

import logging
import time

import requests
from bs4 import BeautifulSoup

from .config import Settings, get_settings

log = logging.getLogger(__name__)

#: lxml is faster and more forgiving, but we don't want a hard test dependency.
try:  # pragma: no cover - environment dependent
    import lxml  # noqa: F401

    _BS_PARSER = "lxml"
except ImportError:  # pragma: no cover
    _BS_PARSER = "html.parser"


class FetchError(RuntimeError):
    """Fetching a resource failed after every attempt."""


def make_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, _BS_PARSER)


class Fetcher:
    """HTTP client with throttling, retries and a per-job cache.

    The cache is deliberate: a parser often needs the same table-of-contents
    page in `get_metadata()` and `get_chapter_list()` - no reason to fetch twice.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        use_playwright: bool = False,
    ) -> None:
        self.settings = settings or get_settings()
        self.use_playwright = use_playwright or self.settings.playwright_enabled
        self._cache: dict[str, str] = {}
        self._last_request_at = 0.0
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self.settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self._browser = None
        self._playwright = None

    # -- Public API ---------------------------------------------------------

    def get_text(self, url: str, *, use_cache: bool = True) -> str:
        if use_cache and url in self._cache:
            return self._cache[url]

        html = (
            self._fetch_with_playwright(url)
            if self.use_playwright
            else self._fetch_with_requests(url)
        )
        if use_cache:
            self._cache[url] = html
        return html

    def get_soup(self, url: str, *, use_cache: bool = True) -> BeautifulSoup:
        return make_soup(self.get_text(url, use_cache=use_cache))

    def get_bytes(self, url: str) -> tuple[bytes, str]:
        """Returns (data, content-type) - used for covers and images."""
        self._throttle()
        last_error: Exception | None = None
        for attempt in range(1, self.settings.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=self.settings.request_timeout)
                resp.raise_for_status()
                content_type = resp.headers.get("Content-Type", "application/octet-stream")
                return resp.content, content_type.split(";")[0].strip()
            except Exception as exc:  # noqa: BLE001 - retry on anything
                last_error = exc
                log.warning("Failed to fetch %s (attempt %s): %s", url, attempt, exc)
                self._backoff(attempt)
        raise FetchError(f"Could not fetch {url}: {last_error}")

    def close(self) -> None:
        self._session.close()
        if self._browser is not None:  # pragma: no cover - heavy mode only
            self._browser.close()
            self._browser = None
        if self._playwright is not None:  # pragma: no cover
            self._playwright.stop()
            self._playwright = None

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- Internals ----------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self.settings.request_delay - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def _backoff(self, attempt: int) -> None:
        time.sleep(min(2**attempt * 0.5, 10.0))

    def _fetch_with_requests(self, url: str) -> str:
        self._throttle()
        last_error: Exception | None = None
        for attempt in range(1, self.settings.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=self.settings.request_timeout)
                resp.raise_for_status()
                #: requests sometimes guesses latin-1 for pages with no charset header.
                if resp.encoding and resp.encoding.lower() == "iso-8859-1":
                    resp.encoding = resp.apparent_encoding
                return resp.text
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                log.warning("Failed to fetch %s (attempt %s): %s", url, attempt, exc)
                if attempt < self.settings.max_retries:
                    self._backoff(attempt)
        raise FetchError(f"Could not fetch {url}: {last_error}")

    def _fetch_with_playwright(self, url: str) -> str:  # pragma: no cover
        """Heavy mode - only works in an image built from the `playwright` target."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise FetchError(
                "Playwright is not installed. Run an image built from the "
                "`playwright` target (docker compose --profile playwright up) "
                "or install requirements-playwright.txt."
            ) from exc

        if self._browser is None:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)

        self._throttle()
        page = self._browser.new_page(user_agent=self.settings.user_agent)
        try:
            page.goto(
                url,
                wait_until=self.settings.playwright_wait_until,
                timeout=self.settings.playwright_timeout_ms,
            )
            return page.content()
        except Exception as exc:  # noqa: BLE001
            raise FetchError(f"Playwright failed to fetch {url}: {exc}") from exc
        finally:
            page.close()
