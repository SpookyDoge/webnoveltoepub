"""Orchestration: URL -> parser -> chapters -> EPUB.

The code is synchronous; the HTTP layer runs it through `asyncio.to_thread`
so the event loop is not blocked (and so the synchronous Playwright API works).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .config import Settings, get_settings
from .epub_builder import build_epub, slugify
from .fetcher import Fetcher, FetchError
from .models import (
    ChapterContent,
    ChapterRef,
    ConvertRequest,
    NovelMetadata,
    PreviewResponse,
)
from .parsers import BaseParser, ParserError, get_parser_class

log = logging.getLogger(__name__)


class UnsupportedSiteError(RuntimeError):
    """No parser handles this domain."""


@dataclass
class ConversionResult:
    file_name: str
    content: bytes
    metadata: NovelMetadata
    chapter_count: int
    warnings: list[str] = field(default_factory=list)
    #: Set when a copy was written to disk (WNE_SAVE_TO_DISK).
    saved_path: Path | None = None


def _make_parser(url: str, settings: Settings) -> tuple[BaseParser, Fetcher]:
    parser_cls = get_parser_class(url)
    if parser_cls is None:
        raise UnsupportedSiteError(url)
    fetcher = Fetcher(settings, use_playwright=parser_cls.requires_playwright)
    return parser_cls(fetcher), fetcher


def preview(url: str, settings: Settings | None = None) -> PreviewResponse:
    settings = settings or get_settings()
    parser, fetcher = _make_parser(url, settings)
    try:
        metadata = parser.get_metadata(url)
        chapters = parser.get_chapter_list(url)
    finally:
        fetcher.close()

    return PreviewResponse(
        parser=parser.name,
        metadata=metadata,
        chapters=chapters,
        max_chapters=settings.max_chapters,
    )


def convert(request: ConvertRequest, settings: Settings | None = None) -> ConversionResult:
    settings = settings or get_settings()
    parser, fetcher = _make_parser(request.url, settings)
    warnings: list[str] = []

    try:
        metadata = parser.get_metadata(request.url)
        if request.language:
            metadata.language = request.language

        all_chapters = parser.get_chapter_list(request.url)
        selected = select_chapters(all_chapters, request)
        if not selected:
            raise ParserError("The chapter selection is empty")

        if len(selected) > settings.max_chapters:
            warnings.append(
                f"Limited to {settings.max_chapters} chapters "
                f"(out of {len(selected)} selected)"
            )
            selected = selected[: settings.max_chapters]

        contents: list[ChapterContent] = []
        for chapter in selected:
            try:
                contents.append(parser.get_chapter_content(chapter))
            except (FetchError, ParserError) as exc:
                log.warning("Skipping chapter %s (%s): %s", chapter.index, chapter.url, exc)
                warnings.append(f"#{chapter.index} {chapter.title}: {exc}")
                contents.append(
                    ChapterContent(
                        title=chapter.title,
                        html=(
                            "<p><em>[webnoveltoepub] This chapter could not be "
                            f"fetched. Source: <a href=\"{chapter.url}\">"
                            f"{chapter.url}</a></em></p>"
                        ),
                    )
                )

        cover = parser.get_cover_image(metadata) if request.include_cover else None
        payload = build_epub(metadata, contents, cover)
    finally:
        fetcher.close()

    file_name = f"{slugify(metadata.title)}.epub"
    return ConversionResult(
        file_name=file_name,
        content=payload,
        metadata=metadata,
        chapter_count=len(contents),
        warnings=warnings,
        saved_path=save_epub_to_disk(file_name, payload, settings),
    )


def save_epub_to_disk(file_name: str, payload: bytes, settings: Settings) -> Path | None:
    """Writes a copy of the EPUB into `settings.output_dir` when saving is enabled.

    A disk problem (no write permission on the bind mount, a full volume) must
    not bring the conversion down - the user still gets the file over HTTP.
    """
    if not settings.save_to_disk:
        return None

    try:
        directory = settings.output_dir
        directory.mkdir(parents=True, exist_ok=True)
        target = _free_path(directory / file_name)
        target.write_bytes(payload)
    except OSError as exc:
        log.warning(
            "Could not save the EPUB in %s: %s. "
            "With a bind mount, check write permissions for the container user.",
            settings.output_dir,
            exc,
        )
        return None

    log.info("Saved %s", target)
    return target


def _free_path(path: Path) -> Path:
    """We never overwrite someone's file - later conversions get a -2, -3 suffix.

    The same novel converted over a different chapter range produces the same
    file name, and silently replacing a file is losing the user's data.
    """
    if not path.exists():
        return path
    for counter in range(2, 1000):
        candidate = path.with_name(f"{path.stem}-{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise OSError(f"Too many files named {path.name}")


def select_chapters(chapters: list[ChapterRef], request: ConvertRequest) -> list[ChapterRef]:
    """Filters the chapter list by `selected` (wins) or by the start/end range."""
    if request.selected:
        wanted = set(request.selected)
        return [chapter for chapter in chapters if chapter.index in wanted]

    start = request.start or 1
    end = request.end or len(chapters)
    return [chapter for chapter in chapters if start <= chapter.index <= end]
