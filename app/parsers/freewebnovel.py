"""Parser dla freewebnovel.com.

W przeciwienstwie do RoyalRoada strona nie osadza zadnego JSON-a z rozdzialami
(sprawdzone: brak window.chapters, ld+json, __NEXT_DATA__) - jedynym zrodlem
listy jest HTML. Za to metadane siedza w bogatym zestawie <meta og:novel:*>,
ktory jest znacznie stabilniejszy niz selektory CSS, wiec to on jest zrodlem
pierwszego wyboru.

Lista rozdzialow jest paginowana po 40 pozycji przez ?page=N.
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

#: Bezpiecznik przed zapetleniem, gdyby paginacja zwariowala. Realne powiesci
#: konczą się dobrze ponizej tego progu (4400 rozdzialow = 111 stron).
MAX_LIST_PAGES = 400

#: Bloki reklamowe wstrzykniete w srodek tresci rozdzialu.
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
    #: Tresc jest renderowana po stronie serwera - lekki tryb wystarcza.
    requires_playwright = False

    # -- Metadane -----------------------------------------------------------

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

    # -- Lista rozdzialow ---------------------------------------------------

    def get_chapter_list(self, url: str) -> list[ChapterRef]:
        url = self.normalize_url(url)
        soup = self.soup(url)

        entries = self._chapter_entries(soup, url)
        if not entries:
            raise ParserError(
                "Nie znalazlem listy rozdzialow. Sprawdz, czy URL wskazuje na "
                "strone glowna powiesci (np. https://freewebnovel.com/novel/slug)."
            )

        total_pages = min(self._count_pages(soup), MAX_LIST_PAGES)
        seen = {entry[1] for entry in entries}

        for page in range(2, total_pages + 1):
            page_soup = self.fetcher.get_soup(f"{url}?page={page}")
            fresh = [e for e in self._chapter_entries(page_soup, url) if e[1] not in seen]
            if not fresh:
                # Serwis potrafi oddac te sama strone zamiast 404 - to nasz koniec listy.
                log.debug("Paginacja %s zatrzymana na stronie %s", url, page)
                break
            seen.update(entry[1] for entry in fresh)
            entries.extend(fresh)

        return [
            ChapterRef(index=i, title=title, url=chapter_url)
            for i, (title, chapter_url) in enumerate(entries, start=1)
        ]

    def _chapter_entries(self, soup: BeautifulSoup, base: str) -> list[tuple[str, str]]:
        """(tytul, url) z jednej strony listy - bez numeracji, ta powstaje na koncu."""
        # Uwaga: ul.ul-list5 wystepuje na stronie kilka razy - m.in. w bloku
        # "najnowsze rozdzialy", ktory zaburzylby kolejnosc. Dlatego najpierw
        # zawezamy sie do wlasciwego kontenera, a dopiero w nim szukamy linkow.
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
        """Liczba stron listy = liczba pozycji w <select> paginacji.

        Same wartosci <option> sa bezuzyteczne (kazda wskazuje na strone glowna,
        prawdziwe adresy dokleja JavaScript), ale ich liczba jest wiarygodna.
        """
        options = soup.select("#indexselect option")
        return max(len(options), 1)

    # -- Tresc rozdzialu ----------------------------------------------------

    def get_chapter_content(self, chapter: ChapterRef) -> ChapterContent:
        soup = self.soup(chapter.url)

        # Reklamy siedza w srodku #article; sanitize_html usunelby same skrypty,
        # ale wrappery potrafia zawierac tekst ("Advertisement"), wiec lecą cale.
        for selector in AD_SELECTORS:
            for element in soup.select(selector):
                element.decompose()
        strip_css_hidden(soup)

        # Kolejnosc ma znaczenie: #article siedzi wewnatrz div.m-read div.txt,
        # a ten wrapper zawiera dodatkowe bloki reklamowe.
        content = self.select_first(soup, "#article", "div.m-read div.txt")
        if content is None:
            raise ParserError(f"Brak tresci rozdzialu pod adresem {chapter.url}")

        title = (
            self.meta_content(soup, "og:novel:chapter_name")
            or self.first_text(soup, "span.chapter")
            or chapter.title
        )
        html = sanitize_html(content, base_url=chapter.url)
        if not html_to_text(html):
            raise ParserError(f"Rozdzial {chapter.url} jest pusty po oczyszczeniu")

        return ChapterContent(title=title, html=html)

    # -- Pomocnicze ---------------------------------------------------------

    def normalize_url(self, url: str) -> str:
        """Sprowadza URL rozdzialu albo strony paginacji do adresu powiesci."""
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
