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


# --------------------------------------------------------------------------
# Library
# --------------------------------------------------------------------------


class LibraryEntry(BaseModel):
    """One novel remembered by the app, so it can be topped up later."""

    #: Derived from source_url (uuid5), so the same novel always lands on the
    #: same entry no matter how many times it is converted.
    id: str
    source_url: str
    parser: str
    title: str
    author: str = "Unknown"
    language: str = "en"
    cover_url: str | None = None
    #: Absolute path of the EPUB on disk. None when WNE_SAVE_TO_DISK was off -
    #: the entry still exists, but there is nothing to append new chapters to.
    file_path: str | None = None
    #: How many chapters the stored EPUB holds.
    chapter_count: int = 0
    #: URL of the last stored chapter. Lets an update notice that the source
    #: list was reordered rather than merely extended.
    last_chapter_url: str | None = None
    created_at: str
    updated_at: str


class LibraryUpdateResult(BaseModel):
    """Outcome of updating a single library entry."""

    id: str
    title: str
    #: "updated" | "up_to_date" | "no_file" | "error"
    status: str
    added_chapters: int = 0
    chapter_count: int = 0
    detail: str | None = None


class LibraryUpdateAllResponse(BaseModel):
    results: list[LibraryUpdateResult]
    updated: int
    failed: int


class LibraryImportResult(BaseModel):
    """One novel taken from a WebToEpub export."""

    title: str
    source_url: str
    #: "imported" | "skipped" | "error"
    status: str
    chapter_count: int = 0
    detail: str | None = None


class LibraryImportResponse(BaseModel):
    results: list[LibraryImportResult]
    imported: int
    skipped: int
    failed: int


# --------------------------------------------------------------------------
# Automatic updates
# --------------------------------------------------------------------------

#: Anything below an hour hammers source sites for nothing: web novels publish
#: a few chapters a day at most, and every check walks the whole library.
MIN_INTERVAL_HOURS = 1


class AppSettings(BaseModel):
    """User-facing configuration that persists across restarts."""

    #: Off by default - nothing reaches out to the internet unless asked.
    auto_update_enabled: bool = False
    auto_update_interval_hours: int = Field(default=24, ge=MIN_INTERVAL_HOURS)
    #: Run one check shortly after the app starts, on top of the interval.
    check_on_startup: bool = False


class AutoUpdateRun(BaseModel):
    """One automatic pass over the library, for the history log."""

    started_at: str
    finished_at: str
    #: "startup" | "interval" | "manual"
    trigger: str
    checked: int = 0
    updated: int = 0
    failed: int = 0


class SettingsResponse(AppSettings):
    """Settings plus the scheduler's view of them."""

    last_run_at: str | None = None
    next_run_at: str | None = None
    #: False in the .exe build, where the app only runs while its window is open.
    runs_in_background: bool = True
    recent_runs: list[AutoUpdateRun] = Field(default_factory=list)
