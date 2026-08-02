"""Modele domenowe (uzywane przez parsery) i schematy API."""

from __future__ import annotations

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# Modele domenowe - to jest kontrakt miedzy parserem a reszta aplikacji.
# --------------------------------------------------------------------------


class NovelMetadata(BaseModel):
    """Metadane calej powiesci."""

    title: str
    author: str = "Unknown"
    description: str = ""
    #: Kod jezyka tresci (BCP-47), trafia do <dc:language> w EPUB-ie.
    language: str = "en"
    cover_url: str | None = None
    source_url: str
    tags: list[str] = Field(default_factory=list)
    publisher: str | None = None


class ChapterRef(BaseModel):
    """Pozycja na liscie rozdzialow (jeszcze bez tresci)."""

    index: int
    title: str
    url: str


class ChapterContent(BaseModel):
    """Pobrana i oczyszczona tresc rozdzialu."""

    title: str
    #: Fragment XHTML (bez <html>/<body>) - ebooklib owija go szablonem.
    html: str


class CoverImage(BaseModel):
    data: bytes
    media_type: str = "image/jpeg"
    file_name: str = "cover.jpg"


# --------------------------------------------------------------------------
# Schematy API
# --------------------------------------------------------------------------


class ParserInfo(BaseModel):
    name: str
    label: str
    domains: list[str]
    requires_playwright: bool


class PreviewRequest(BaseModel):
    url: str


class PreviewResponse(BaseModel):
    parser: str
    metadata: NovelMetadata
    chapters: list[ChapterRef]
    #: Limit z konfiguracji - front pokazuje ostrzezenie, gdy lista jest dluzsza.
    max_chapters: int


class ConvertRequest(BaseModel):
    url: str
    #: Zakres 1-based, wlacznie. Ignorowany, gdy podano `selected`.
    start: int | None = None
    end: int | None = None
    #: Konkretne indeksy rozdzialow (1-based) - wygrywa z zakresem.
    selected: list[int] | None = None
    include_cover: bool = True
    #: Nadpisuje jezyk wykryty przez parser (np. "pl").
    language: str | None = None


class ErrorResponse(BaseModel):
    detail: str
