"""The shared parser interface.

Every supported site is one class deriving from `BaseParser`, in its own file
in this directory. Registration happens automatically (`__init_subclass__`)
- there is no central list anyone has to remember to update.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from ..fetcher import Fetcher, FetchError
from ..models import ChapterContent, ChapterRef, CoverImage, NovelMetadata

log = logging.getLogger(__name__)

#: Filled in automatically by __init_subclass__.
_REGISTRY: list[type[BaseParser]] = []


class ParserError(RuntimeError):
    """The parser could not handle the page (layout change, block, 404...)."""


class BaseParser(ABC):
    """The contract a single-site parser has to fulfil."""

    #: Stable identifier (used in the API and in logs).
    name: str = "base"
    #: Name shown to the user.
    label: str = "Base"
    #: Domains handled by the parser; matching covers subdomains too.
    domains: tuple[str, ...] = ()
    #: True => the site needs JS rendering (heavy mode).
    requires_playwright: bool = False
    #: Higher priority wins when several parsers match a URL.
    priority: int = 0

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        _REGISTRY.append(cls)

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    # -- URL matching -------------------------------------------------------

    @classmethod
    def matches(cls, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return any(host == d or host.endswith(f".{d}") for d in cls.domains)

    # -- The contract to implement ------------------------------------------

    @abstractmethod
    def get_metadata(self, url: str) -> NovelMetadata:
        """Title, author, description, cover - from the novel's main page URL."""

    @abstractmethod
    def get_chapter_list(self, url: str) -> list[ChapterRef]:
        """Chapters in reading order, indexed from 1."""

    @abstractmethod
    def get_chapter_content(self, chapter: ChapterRef) -> ChapterContent:
        """One chapter's content as a cleaned XHTML fragment."""

    # -- Default implementations (overridable) ------------------------------

    def get_cover_image(self, metadata: NovelMetadata) -> CoverImage | None:
        """Downloads the cover from `metadata.cover_url`. A missing cover is fine."""
        if not metadata.cover_url:
            return None
        try:
            data, media_type = self.fetcher.get_bytes(metadata.cover_url)
        except FetchError as exc:
            log.warning("Could not fetch cover %s: %s", metadata.cover_url, exc)
            return None

        if not media_type.startswith("image/"):
            log.warning("Cover %s has type %s - skipping", metadata.cover_url, media_type)
            return None

        extension = {"image/png": "png", "image/webp": "webp", "image/gif": "gif"}.get(
            media_type, "jpg"
        )
        return CoverImage(
            data=data, media_type=media_type, file_name=f"cover.{extension}"
        )

    def normalize_url(self, url: str) -> str:
        """A chance to reduce a chapter URL to the novel's main page address."""
        return url.split("#")[0].rstrip("/")

    # -- Helpers ------------------------------------------------------------

    def soup(self, url: str) -> BeautifulSoup:
        return self.fetcher.get_soup(url)

    @staticmethod
    def meta_content(soup: BeautifulSoup, *names: str) -> str | None:
        """First matching value from <meta property|name=...>."""
        for name in names:
            for attr in ("property", "name", "itemprop"):
                tag = soup.find("meta", attrs={attr: name})
                if tag and tag.get("content"):
                    return tag["content"].strip()
        return None

    @staticmethod
    def select_first(soup: BeautifulSoup, *selectors: str) -> Tag | None:
        """First element found, following the ORDER OF THE SELECTORS.

        Do not use `soup.select_one("#a, .b")` to express priority: a CSS
        selector list returns whichever element comes first in the *document*,
        so with nested containers it picks the wider wrapper along with its
        junk (ads, navigation) instead of the actual content.
        """
        for selector in selectors:
            element = soup.select_one(selector)
            if element is not None:
                return element
        return None

    @staticmethod
    def first_text(soup: BeautifulSoup, *selectors: str) -> str | None:
        for selector in selectors:
            element = soup.select_one(selector)
            if element:
                text = element.get_text(" ", strip=True)
                if text:
                    return text
        return None
