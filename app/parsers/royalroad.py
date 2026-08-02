"""Parser dla RoyalRoad.com.

Sluzy jednoczesnie za referencyjny przyklad dla kolejnych serwisow -
kolejnosc metod i sposob budowania fallbackow warto skopiowac.
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import ChapterContent, ChapterRef, NovelMetadata
from ..sanitize import html_to_text, sanitize_html, strip_css_hidden
from .base import BaseParser, ParserError

log = logging.getLogger(__name__)

BASE_URL = "https://www.royalroad.com"

#: Lista rozdzialow siedzi w inline'owym skrypcie jako JSON - to najpewniejsze
#: zrodlo. Tabela HTML jest fallbackiem na wypadek zmiany layoutu.
_CHAPTERS_JSON_RE = re.compile(r"window\.chapters\s*=\s*(\[.*?\])\s*;", re.S)
_FICTION_URL_RE = re.compile(r"(https?://[^/]+/fiction/\d+(?:/[^/?#]+)?)")


class RoyalRoadParser(BaseParser):
    name = "royalroad"
    label = "RoyalRoad"
    domains = ("royalroad.com",)
    requires_playwright = False

    # -- Metadane -----------------------------------------------------------

    def get_metadata(self, url: str) -> NovelMetadata:
        url = self.normalize_url(url)
        soup = self.soup(url)

        title = (
            self.first_text(soup, "div.fic-title h1", "h1.font-white")
            or self.meta_content(soup, "og:title", "twitter:title")
            or "Unknown title"
        )
        author = (
            self.first_text(soup, "div.fic-title h4 a", "h4.font-white a")
            or self.meta_content(soup, "books:author", "author")
            or "Unknown"
        )

        description_el = soup.select_one("div.description, div.hidden-content")
        description = (
            html_to_text(description_el, limit=2000)
            if description_el
            else (self.meta_content(soup, "og:description", "description") or "")
        )

        cover_url = self._find_cover_url(soup, url)
        tags = [
            tag.get_text(strip=True)
            for tag in soup.select("span.tags a.fiction-tag, a.label.tags")
            if tag.get_text(strip=True)
        ]

        return NovelMetadata(
            title=title,
            author=author,
            description=description,
            language="en",
            cover_url=cover_url,
            source_url=url,
            tags=tags,
            publisher="RoyalRoad",
        )

    # -- Lista rozdzialow ---------------------------------------------------

    def get_chapter_list(self, url: str) -> list[ChapterRef]:
        url = self.normalize_url(url)
        html = self.fetcher.get_text(url)

        chapters = self._chapters_from_json(html) or self._chapters_from_table(
            BeautifulSoup(html, "html.parser")
        )
        if not chapters:
            raise ParserError(
                "Nie znalazlem listy rozdzialow. Sprawdz, czy URL wskazuje na "
                "strone glowna powiesci (np. https://www.royalroad.com/fiction/12345/slug)."
            )
        return chapters

    def _chapters_from_json(self, html: str) -> list[ChapterRef]:
        match = _CHAPTERS_JSON_RE.search(html)
        if not match:
            return []
        try:
            raw = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            log.warning("window.chapters nie jest poprawnym JSON-em: %s", exc)
            return []

        chapters: list[ChapterRef] = []
        for entry in raw:
            href = entry.get("url")
            if not href:
                continue
            chapters.append(
                ChapterRef(
                    index=len(chapters) + 1,
                    title=(entry.get("title") or f"Chapter {len(chapters) + 1}").strip(),
                    url=urljoin(BASE_URL, href),
                )
            )
        return chapters

    def _chapters_from_table(self, soup: BeautifulSoup) -> list[ChapterRef]:
        rows = soup.select("table#chapters tbody tr, table.chapter-list tbody tr")
        chapters: list[ChapterRef] = []
        for row in rows:
            link = row.find("a", href=True)
            if not link:
                continue
            chapters.append(
                ChapterRef(
                    index=len(chapters) + 1,
                    title=link.get_text(" ", strip=True)
                    or f"Chapter {len(chapters) + 1}",
                    url=urljoin(BASE_URL, link["href"]),
                )
            )
        return chapters

    # -- Tresc rozdzialu ----------------------------------------------------

    def get_chapter_content(self, chapter: ChapterRef) -> ChapterContent:
        soup = self.soup(chapter.url)

        # RoyalRoad wstrzykuje akapity-pulapki ukryte regulami CSS z <head>;
        # trzeba je wyciac na pelnej stronie, zanim wyjmiemy sam div z trescia.
        strip_css_hidden(soup)

        content = self.select_first(soup, "div.chapter-content", "div.chapter-inner")
        if content is None:
            raise ParserError(f"Brak tresci rozdzialu pod adresem {chapter.url}")

        title = (
            self.first_text(soup, "h1.font-white", "div.fic-header h1", "h1.chapter-title")
            or chapter.title
        )
        html = sanitize_html(content, base_url=chapter.url)
        if not html_to_text(html):
            raise ParserError(f"Rozdzial {chapter.url} jest pusty po oczyszczeniu")

        return ChapterContent(title=title, html=html)

    # -- Pomocnicze ---------------------------------------------------------

    def normalize_url(self, url: str) -> str:
        """Sprowadza URL rozdzialu do URL-a strony glownej powiesci."""
        url = url.split("#")[0].split("?")[0].rstrip("/")
        match = _FICTION_URL_RE.match(url)
        return match.group(1) if match else url

    def _find_cover_url(self, soup: BeautifulSoup, page_url: str) -> str | None:
        image = soup.select_one("div.cover-art-container img, img.thumbnail")
        src = image.get("src") if image else None
        src = src or self.meta_content(soup, "og:image", "twitter:image")
        if not src or "nocover" in src:
            return None
        return urljoin(page_url, src)
