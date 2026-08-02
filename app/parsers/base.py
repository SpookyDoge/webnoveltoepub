"""Wspolny interfejs parserow.

Kazdy obslugiwany serwis to jedna klasa dziedziczaca po `BaseParser`, w osobnym
pliku w tym katalogu. Rejestracja dzieje sie automatycznie (`__init_subclass__`)
- nie ma zadnej centralnej listy, ktora trzeba pamietac o aktualizacji.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from ..fetcher import Fetcher, FetchError
from ..models import ChapterContent, ChapterRef, CoverImage, NovelMetadata

log = logging.getLogger(__name__)

#: Wypelniane automatycznie przez __init_subclass__.
_REGISTRY: list[type[BaseParser]] = []


class ParserError(RuntimeError):
    """Parser nie poradzil sobie ze strona (zmiana layoutu, blokada, 404...)."""


class BaseParser(ABC):
    """Kontrakt, ktory musi spelnic parser jednego serwisu."""

    #: Stabilny identyfikator (uzywany w API i logach).
    name: str = "base"
    #: Nazwa pokazywana uzytkownikowi.
    label: str = "Base"
    #: Domeny obslugiwane przez parser; dopasowanie obejmuje subdomeny.
    domains: tuple[str, ...] = ()
    #: True => strona wymaga renderowania JS (ciezki tryb).
    requires_playwright: bool = False
    #: Wyzszy priorytet wygrywa, gdy kilka parserow pasuje do URL-a.
    priority: int = 0

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        _REGISTRY.append(cls)

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    # -- Dopasowanie URL-a --------------------------------------------------

    @classmethod
    def matches(cls, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return any(host == d or host.endswith(f".{d}") for d in cls.domains)

    # -- Kontrakt do zaimplementowania --------------------------------------

    @abstractmethod
    def get_metadata(self, url: str) -> NovelMetadata:
        """Tytul, autor, opis, okladka - z URL-a strony glownej powiesci."""

    @abstractmethod
    def get_chapter_list(self, url: str) -> list[ChapterRef]:
        """Rozdzialy w kolejnosci czytania, indeksowane od 1."""

    @abstractmethod
    def get_chapter_content(self, chapter: ChapterRef) -> ChapterContent:
        """Tresc jednego rozdzialu jako oczyszczony fragment XHTML."""

    # -- Implementacje domyslne (mozna nadpisac) ----------------------------

    def get_cover_image(self, metadata: NovelMetadata) -> CoverImage | None:
        """Pobiera okladke z `metadata.cover_url`. Brak okladki nie jest bledem."""
        if not metadata.cover_url:
            return None
        try:
            data, media_type = self.fetcher.get_bytes(metadata.cover_url)
        except FetchError as exc:
            log.warning("Nie udalo sie pobrac okladki %s: %s", metadata.cover_url, exc)
            return None

        if not media_type.startswith("image/"):
            log.warning("Okladka %s ma typ %s - pomijam", metadata.cover_url, media_type)
            return None

        extension = {"image/png": "png", "image/webp": "webp", "image/gif": "gif"}.get(
            media_type, "jpg"
        )
        return CoverImage(
            data=data, media_type=media_type, file_name=f"cover.{extension}"
        )

    def normalize_url(self, url: str) -> str:
        """Szansa na sprowadzenie URL-a rozdzialu do adresu strony glownej."""
        return url.split("#")[0].rstrip("/")

    # -- Pomocnicze ---------------------------------------------------------

    def soup(self, url: str) -> BeautifulSoup:
        return self.fetcher.get_soup(url)

    @staticmethod
    def meta_content(soup: BeautifulSoup, *names: str) -> str | None:
        """Pierwsza pasujaca wartosc z <meta property|name=...>."""
        for name in names:
            for attr in ("property", "name", "itemprop"):
                tag = soup.find("meta", attrs={attr: name})
                if tag and tag.get("content"):
                    return tag["content"].strip()
        return None

    @staticmethod
    def select_first(soup: BeautifulSoup, *selectors: str) -> Tag | None:
        """Pierwszy trafiony element wedlug KOLEJNOSCI SELEKTOROW.

        Nie uzywaj `soup.select_one("#a, .b")` do wyrazania priorytetu: lista
        selektorow CSS zwraca element wystepujacy wczesniej w *dokumencie*,
        wiec przy zagniezdzonych kontenerach wybierze szerszy wrapper razem
        z jego smieciami (reklamy, nawigacja) zamiast wlasciwej tresci.
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
