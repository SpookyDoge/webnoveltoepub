"""Domain models (used by parsers) and API schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# Domain models - this is the contract between a parser and the rest of the app.
# --------------------------------------------------------------------------


class NovelMetadata(BaseModel):
    """Metadata for a whole novel."""

    title: str
    author: str = "Unknown"
    description: str = ""
    #: Content language code (BCP-47), ends up in <dc:language> in the EPUB.
    language: str = "en"
    cover_url: str | None = None
    source_url: str
    tags: list[str] = Field(default_factory=list)
    publisher: str | None = None


class ChapterRef(BaseModel):
    """An entry in the chapter list (no content yet)."""

    index: int
    title: str
    url: str


class ChapterContent(BaseModel):
    """Fetched and cleaned chapter content."""

    title: str
    #: XHTML fragment (no <html>/<body>) - ebooklib wraps it in a template.
    html: str


class CoverImage(BaseModel):
    data: bytes
    media_type: str = "image/jpeg"
    file_name: str = "cover.jpg"


# --------------------------------------------------------------------------
# API schemas
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
    #: The configured cap - the frontend warns when the list is longer.
    max_chapters: int


class ConvertRequest(BaseModel):
    url: str
    #: 1-based range, inclusive. Ignored when `selected` is given.
    start: int | None = None
    end: int | None = None
    #: Explicit chapter indices (1-based) - takes precedence over the range.
    selected: list[int] | None = None
    include_cover: bool = True
    #: Overrides the language detected by the parser (e.g. "pl").
    language: str | None = None


class ErrorResponse(BaseModel):
    detail: str
