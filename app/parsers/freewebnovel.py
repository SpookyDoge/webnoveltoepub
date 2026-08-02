"""Parser for freewebnovel.com.

Unlike RoyalRoad, this site embeds no JSON with the chapters (verified: no
window.chapters, no ld+json, no __NEXT_DATA__) - the HTML is the only source
for the list. On the other hand the metadata lives in a rich set of
<meta og:novel:*> tags, far more stable than CSS selectors, so that is the
source of first choice.

The chapter list is paginated 40 entries at a time via ?page=N.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import ChapterContent, ChapterRef, NovelMetadata
from ..sanitize import html_to_text, sanitize_html, strip_css_hidden
from .base import BaseParser, ParserError

log = logging.getLogger(__name__)

BASE_URL = "https://freewebnovel.com"

_NOVEL_URL_RE = re.compile(r"(https?://[^/]+/novel/[^/?#]+)")

#: Safety valve against looping if pagination goes haywire. Real novels end
#: well below this threshold (4400 chapters = 111 pages).
MAX_LIST_PAGES = 400

#: Ad blocks injected into the middle of the chapter content.
AD_SELECTORS = (
    ".reader-ad-skip",
    "[id^=bg-ssp]",
    "[id^=pf-]",
    ".comments-widget",
)


class FreeWebNovelParser(BaseParser):
    name = "freewebnovel"
    label = "FreeWebNovel"
    domains = ("freewebnovel.com",)
    #: The content is server-rendered - the lightweight mode is enough.
    requires_playwright = False

    # -- Metadata -----------------------------------------------------------

    def get_metadata(self, url: str) -> NovelMetadata:
        url = self.normalize_url(url)
        soup = self.soup(url)

        title = (
            self.meta_content(soup, "og:novel:novel_name", "og:title")
            or self.first_text(soup, "h1.tit")
            or "Unknown title"
        )
        author = (
            self.meta_content(soup, "og:novel:author")
            or self.first_text(soup, "div.m-book1 div.txt div.item a[href^='/author/']")
            or "Unknown"
        )

        description_el = soup.select_one("div.m-desc div.txt div.inner, div.m-desc div.txt")
        description = (
            html_to_text(description_el, limit=2000)
            if description_el
            else (self.meta_content(soup, "og:description", "description") or "")
        )

        return NovelMetadata(
            title=title,
            author=author,
            description=description,
            language="en",
            cover_url=self._find_cover_url(soup, url),
            source_url=url,
            tags=self._find_tags(soup),
            publisher="FreeWebNovel",
        )

    # -- Chapter list -------------------------------------------------------

    def get_chapter_list(self, url: str) -> list[ChapterRef]:
        url = self.normalize_url(url)
        soup = self.soup(url)

        entries = self._chapter_entries(soup, url)
        if not entries:
            raise ParserError(
                "Could not find the chapter list. Check that the URL points at the "
                "novel's main page (e.g. https://freewebnovel.com/novel/slug)."
            )

        total_pages = min(self._count_pages(soup), MAX_LIST_PAGES)
        seen = {entry[1] for entry in entries}

        for page in range(2, total_pages + 1):
            page_soup = self.fetcher.get_soup(f"{url}?page={page}")
            fresh = [e for e in self._chapter_entries(page_soup, url) if e[1] not in seen]
            if not fresh:
                # The site may serve the same page instead of a 404 - that is
                # our end of the list.
                log.debug("Pagination for %s stopped at page %s", url, page)
                break
            seen.update(entry[1] for entry in fresh)
            entries.extend(fresh)

        return [
            ChapterRef(index=i, title=title, url=chapter_url)
            for i, (title, chapter_url) in enumerate(entries, start=1)
        ]

    def _chapter_entries(self, soup: BeautifulSoup, base: str) -> list[tuple[str, str]]:
        """(title, url) from one list page - unnumbered, numbering happens at the end."""
        # Careful: ul.ul-list5 appears on the page several times - among others
        # in the "latest chapters" block, which would break the ordering. So we
        # first narrow down to the right container and only then look for links.
        container = soup.select_one("#idData") or soup.select_one("div.m-newest2 ul.ul-list5")
        if container is None:
            return []

        entries: list[tuple[str, str]] = []
        for link in container.select("li a[href]"):
            href = link.get("href")
            if not href or "/chapter-" not in href:
                continue
            title = (link.get("title") or link.get_text(" ", strip=True)).strip()
            entries.append((title or "Chapter", urljoin(base, href)))
        return entries

    @staticmethod
    def _count_pages(soup: BeautifulSoup) -> int:
        """Number of list pages = number of entries in the pagination <select>.

        The <option> values themselves are useless (each points at the main
        page, JavaScript fills in the real addresses), but their count is
        trustworthy.
        """
        options = soup.select("#indexselect option")
        return max(len(options), 1)

    # -- Chapter content ----------------------------------------------------

    def get_chapter_content(self, chapter: ChapterRef) -> ChapterContent:
        soup = self.soup(chapter.url)

        # Ads sit inside #article; sanitize_html would drop the scripts alone,
        # but the wrappers can carry text ("Advertisement"), so they go whole.
        for selector in AD_SELECTORS:
            for element in soup.select(selector):
                element.decompose()
        strip_css_hidden(soup)

        # Order matters: #article sits inside div.m-read div.txt, and that
        # wrapper holds additional ad blocks.
        content = self.select_first(soup, "#article", "div.m-read div.txt")
        if content is None:
            raise ParserError(f"No chapter content at {chapter.url}")

        title = (
            self.meta_content(soup, "og:novel:chapter_name")
            or self.first_text(soup, "span.chapter")
            or chapter.title
        )
        html = sanitize_html(content, base_url=chapter.url)
        if not html_to_text(html):
            raise ParserError(f"Chapter {chapter.url} is empty after cleaning")

        return ChapterContent(title=title, html=html)

    # -- Helpers ------------------------------------------------------------

    def normalize_url(self, url: str) -> str:
        """Reduces a chapter or pagination URL to the novel's address."""
        url = url.split("#")[0].split("?")[0].rstrip("/")
        match = _NOVEL_URL_RE.match(url)
        return match.group(1) if match else url

    def _find_cover_url(self, soup: BeautifulSoup, page_url: str) -> str | None:
        image = soup.select_one("div.m-imgtxt img[src], div.pic img[src]")
        src = image.get("src") if image else None
        src = src or self.meta_content(soup, "og:image", "image")
        return urljoin(page_url, src) if src else None

    @staticmethod
    def _find_tags(soup: BeautifulSoup) -> list[str]:
        genres = FreeWebNovelParser.meta_content(soup, "og:novel:genre")
        if genres:
            return [tag.strip() for tag in genres.split(",") if tag.strip()]
        return [
            link.get_text(strip=True)
            for link in soup.select("a[href^='/genre/']")
            if link.get_text(strip=True)
        ]
