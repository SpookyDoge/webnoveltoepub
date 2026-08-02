"""Orchestration: URL -> parser -> chapters -> EPUB.

The code is synchronous; the HTTP layer runs it through `asyncio.to_thread`
so the event loop is not blocked (and so the synchronous Playwright API works).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import Settings, get_settings
from .epub_builder import append_chapters, build_epub, slugify
from .fetcher import Fetcher, FetchError
from .library import Library, utc_now
from .models import (
    ChapterContent,
    ChapterRef,
    ConvertRequest,
    LibraryEntry,
    LibraryUpdateAllResponse,
    LibraryUpdateResult,
    NovelMetadata,
    PreviewResponse,
)
from .parsers import BaseParser, ParserError, get_parser_class
from .progress import Emitter, JobControl

log = logging.getLogger(__name__)


class UnsupportedSiteError(RuntimeError):
    """No parser handles this domain."""


class LibraryEntryNotFoundError(RuntimeError):
    """No library entry with that id."""


class StoppedBeforeStartError(RuntimeError):
    """Stopped before a single chapter arrived, so there is no book to save.

    Its own type so the UI can say exactly that, instead of blaming the parser
    for a page it never got round to reading.
    """


def _noop(*args: object, **kwargs: object) -> None:
    """Stand-in emitter, so service code never has to check for None."""


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


def preview(
    url: str,
    settings: Settings | None = None,
    emit: Emitter | None = None,
) -> PreviewResponse:
    settings = settings or get_settings()
    emit = emit or _noop
    parser, fetcher = _make_parser(url, settings)

    found = 0

    def on_batch(batch: list[ChapterRef]) -> None:
        # One event per source page rather than per chapter: a page is one
        # HTTP request, so its chapters become known all at once anyway, and
        # 4400 individual frames would buy nothing visually.
        nonlocal found
        found += len(batch)
        emit(
            "chapters_found",
            chapters=[chapter.model_dump() for chapter in batch],
            total=found,
        )

    parser.on_chapters_found = on_batch
    try:
        metadata = parser.get_metadata(url)
        emit("metadata", parser=parser.name, metadata=metadata.model_dump())
        chapters = parser.get_chapter_list(url)
    finally:
        parser.on_chapters_found = None
        fetcher.close()

    return PreviewResponse(
        parser=parser.name,
        metadata=metadata,
        chapters=chapters,
        max_chapters=settings.max_chapters,
    )


def convert(
    request: ConvertRequest,
    settings: Settings | None = None,
    emit: Emitter | None = None,
    control: JobControl | None = None,
) -> ConversionResult:
    settings = settings or get_settings()
    emit = emit or _noop
    parser, fetcher = _make_parser(request.url, settings)
    warnings: list[str] = []

    try:
        metadata = parser.get_metadata(request.url)
        if request.language:
            metadata.language = request.language
        emit("metadata", parser=parser.name, metadata=metadata.model_dump())

        all_chapters = parser.get_chapter_list(request.url)
        selected = select_chapters(all_chapters, request)
        if not selected:
            raise ParserError("The chapter selection is empty")

        # 0 means unlimited; only a positive cap truncates.
        if 0 < settings.max_chapters < len(selected):
            warnings.append(
                f"Limited to {settings.max_chapters} chapters "
                f"(out of {len(selected)} selected)"
            )
            selected = selected[: settings.max_chapters]

        contents = _download_chapters(parser, selected, warnings, emit, control)
        if not contents:
            raise StoppedBeforeStartError("Stopped before any chapter was downloaded")

        # A stop leaves fewer chapters than were asked for; the book is built
        # from what actually arrived so nothing already downloaded is lost.
        included = selected[: len(contents)]
        if len(included) < len(selected):
            warnings.append(
                f"Stopped after {len(included)} of {len(selected)} chapters"
            )

        emit("stage", stage="building")
        cover = parser.get_cover_image(metadata) if request.include_cover else None
        payload = build_epub(metadata, contents, cover)
    finally:
        fetcher.close()

    file_name = f"{slugify(metadata.title)}.epub"
    saved_path = save_epub_to_disk(file_name, payload, settings)

    record_in_library(
        metadata=metadata,
        parser_name=parser.name,
        chapters=included,
        file_path=saved_path,
        settings=settings,
    )

    return ConversionResult(
        file_name=file_name,
        content=payload,
        metadata=metadata,
        chapter_count=len(contents),
        warnings=warnings,
        saved_path=saved_path,
    )


def _download_chapters(
    parser: BaseParser,
    selected: list[ChapterRef],
    warnings: list[str],
    emit: Emitter,
    control: JobControl | None = None,
) -> list[ChapterContent]:
    """Fetches chapter bodies, reporting progress and tolerating failures.

    Returns however many were fetched: a stop request ends the loop early and
    the caller builds a shorter - but complete and valid - book out of it.
    """
    total = len(selected)
    contents: list[ChapterContent] = []

    for position, chapter in enumerate(selected, start=1):
        if control is not None:
            was_paused = control.state == "paused"
            if was_paused:
                emit("status", state="paused")
            # Blocks here while paused; False once a stop is requested.
            if not control.checkpoint():
                emit("stopped", downloaded=len(contents), requested=total)
                break
            if was_paused:
                emit("status", state="running")

        try:
            contents.append(parser.get_chapter_content(chapter))
            failed = False
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
            failed = True

        emit(
            "chapter_downloaded",
            index=position,
            total=total,
            title=chapter.title,
            failed=failed,
        )

    return contents


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


# --------------------------------------------------------------------------
# Library
# --------------------------------------------------------------------------


def record_in_library(
    *,
    metadata: NovelMetadata,
    parser_name: str,
    chapters: list[ChapterRef],
    file_path: Path | None,
    settings: Settings,
) -> LibraryEntry:
    """Remembers the novel after a conversion.

    Recorded even when nothing was written to disk: the entry is still worth
    having as history, it just cannot be topped up later - the update endpoint
    says so explicitly rather than silently rebuilding everything.
    """
    # The last chapter's 1-based position in the source list, not how many were
    # written. After a stop at chapter 40 of 290 that records 40, so a later
    # Update resumes at 41 - which is exactly what update_entry expects.
    last = chapters[-1] if chapters else None
    entry = Library.build_entry(
        source_url=metadata.source_url,
        parser_name=parser_name,
        title=metadata.title,
        author=metadata.author,
        language=metadata.language,
        cover_url=metadata.cover_url,
        file_path=file_path,
        chapter_count=last.index if last else 0,
        last_chapter_url=last.url if last else None,
    )
    return Library(settings).upsert(entry)


def update_entry(
    entry_key: str,
    settings: Settings | None = None,
    emit: Emitter | None = None,
    control: JobControl | None = None,
) -> LibraryUpdateResult:
    """Fetches only the chapters the stored EPUB does not have yet."""
    settings = settings or get_settings()
    emit = emit or _noop
    library = Library(settings)

    entry = library.get(entry_key)
    if entry is None:
        raise LibraryEntryNotFoundError(entry_key)

    emit("entry_started", id=entry.id, title=entry.title)

    if not entry.file_path or not Path(entry.file_path).is_file():
        # Nothing to append to. Rebuilding would mean re-downloading the whole
        # novel behind the user's back, so say what is wrong instead.
        result = LibraryUpdateResult(
            id=entry.id,
            title=entry.title,
            status="no_file",
            chapter_count=entry.chapter_count,
            detail="no_epub_on_disk",
        )
        emit("entry_finished", **result.model_dump())
        return result

    parser, fetcher = _make_parser(entry.source_url, settings)
    warnings: list[str] = []
    try:
        all_chapters = parser.get_chapter_list(entry.source_url)
        new_chapters = all_chapters[entry.chapter_count :]

        if entry.last_chapter_url and len(all_chapters) >= entry.chapter_count > 0:
            stored_last = all_chapters[entry.chapter_count - 1].url
            if stored_last != entry.last_chapter_url:
                # The source list was reordered or had entries removed, so
                # "everything past our count" is no longer the right slice.
                warnings.append("chapter_list_shifted")
                log.warning(
                    "Chapter list for %s no longer matches the stored one "
                    "(expected %s at position %s, found %s)",
                    entry.source_url,
                    entry.last_chapter_url,
                    entry.chapter_count,
                    stored_last,
                )

        if not new_chapters:
            result = LibraryUpdateResult(
                id=entry.id,
                title=entry.title,
                status="up_to_date",
                chapter_count=entry.chapter_count,
            )
            emit("entry_finished", **result.model_dump())
            return result

        emit("update_started", id=entry.id, title=entry.title, new_chapters=len(new_chapters))
        contents = _download_chapters(parser, new_chapters, warnings, emit, control)
        # A stop can land before anything was appended - leave the file alone.
        added = new_chapters[: len(contents)]
        payload = append_chapters(Path(entry.file_path), contents) if contents else None
    finally:
        fetcher.close()

    if payload is None:
        result = LibraryUpdateResult(
            id=entry.id,
            title=entry.title,
            status="stopped",
            chapter_count=entry.chapter_count,
        )
        emit("entry_finished", **result.model_dump())
        return result

    Path(entry.file_path).write_bytes(payload)

    updated = entry.model_copy(
        update={
            "chapter_count": added[-1].index,
            "last_chapter_url": added[-1].url,
            "updated_at": utc_now(),
        }
    )
    library.upsert(updated)

    result = LibraryUpdateResult(
        id=entry.id,
        title=entry.title,
        status="stopped" if len(added) < len(new_chapters) else "updated",
        added_chapters=len(added),
        chapter_count=updated.chapter_count,
        detail="; ".join(warnings) or None,
    )
    emit("entry_finished", **result.model_dump())
    return result


def update_all(
    settings: Settings | None = None,
    emit: Emitter | None = None,
    control: JobControl | None = None,
) -> LibraryUpdateAllResponse:
    """Walks the whole library, pausing between novels.

    A stop ends the whole series, not just the novel in flight - but every
    entry finished before that point is already written to disk and recorded.
    """
    settings = settings or get_settings()
    emit = emit or _noop
    entries = Library(settings).load()

    emit("bulk_started", total=len(entries))
    results: list[LibraryUpdateResult] = []

    for position, entry in enumerate(entries, start=1):
        if control is not None and not control.checkpoint():
            emit("stopped", completed=len(results), total=len(entries))
            break

        if position > 1 and settings.library_update_delay > 0:
            # Each novel gets a fresh Fetcher, so its per-host throttle starts
            # from zero - without this the library would burst on every site.
            time.sleep(settings.library_update_delay)

        emit("bulk_progress", index=position, total=len(entries), title=entry.title)
        try:
            results.append(update_entry(entry.id, settings, emit, control))
        except Exception as exc:  # noqa: BLE001 - one novel must not stop the rest
            log.warning("Updating %s failed: %s", entry.source_url, exc)
            results.append(
                LibraryUpdateResult(
                    id=entry.id,
                    title=entry.title,
                    status="error",
                    chapter_count=entry.chapter_count,
                    detail=str(exc),
                )
            )

    return LibraryUpdateAllResponse(
        results=results,
        updated=sum(1 for r in results if r.status == "updated"),
        failed=sum(1 for r in results if r.status == "error"),
    )


def select_chapters(chapters: list[ChapterRef], request: ConvertRequest) -> list[ChapterRef]:
    """Filters the chapter list by `selected` (wins) or by the start/end range."""
    if request.selected:
        wanted = set(request.selected)
        return [chapter for chapter in chapters if chapter.index in wanted]

    start = request.start or 1
    end = request.end or len(chapters)
    return [chapter for chapter in chapters if start <= chapter.index <= end]
