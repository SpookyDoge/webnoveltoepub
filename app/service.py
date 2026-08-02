"""Orkiestracja: URL -> parser -> rozdzialy -> EPUB.

Kod jest synchroniczny; warstwa HTTP odpala go przez `asyncio.to_thread`,
zeby nie blokowac petli zdarzen (i zeby dzialal synchroniczny Playwright).
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
    """Zaden parser nie obsluguje tej domeny."""


@dataclass
class ConversionResult:
    file_name: str
    content: bytes
    metadata: NovelMetadata
    chapter_count: int
    warnings: list[str] = field(default_factory=list)
    #: Ustawione, gdy kopia trafila na dysk (WNE_SAVE_TO_DISK).
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
            raise ParserError("Wybor rozdzialow jest pusty")

        if len(selected) > settings.max_chapters:
            warnings.append(
                f"Ograniczono do {settings.max_chapters} rozdzialow "
                f"(z {len(selected)} wybranych)"
            )
            selected = selected[: settings.max_chapters]

        contents: list[ChapterContent] = []
        for chapter in selected:
            try:
                contents.append(parser.get_chapter_content(chapter))
            except (FetchError, ParserError) as exc:
                log.warning("Pomijam rozdzial %s (%s): %s", chapter.index, chapter.url, exc)
                warnings.append(f"#{chapter.index} {chapter.title}: {exc}")
                contents.append(
                    ChapterContent(
                        title=chapter.title,
                        html=(
                            "<p><em>[webnoveltoepub] Nie udalo sie pobrac tego "
                            f"rozdzialu. Zrodlo: <a href=\"{chapter.url}\">"
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
        saved_path=save_to_disk(file_name, payload, settings),
    )


def save_to_disk(file_name: str, payload: bytes, settings: Settings) -> Path | None:
    """Zapisuje kopie EPUB-a w `settings.output_dir`, jesli wlaczono zapis.

    Problem z dyskiem (brak uprawnien do bind mounta, pelny wolumen) nie moze
    wywrocic konwersji - uzytkownik i tak dostaje plik w odpowiedzi HTTP.
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
            "Nie udalo sie zapisac EPUB-a w %s: %s. "
            "Przy bind mouncie sprawdz uprawnienia do zapisu dla uzytkownika kontenera.",
            settings.output_dir,
            exc,
        )
        return None

    log.info("Zapisano %s", target)
    return target


def _free_path(path: Path) -> Path:
    """Nie nadpisujemy cudzych plikow - kolejne konwersje dostaja sufiks -2, -3...

    Ta sama powiesc konwertowana w innym zakresie rozdzialow ma te sama nazwe,
    a po cichu podmieniony plik to utrata danych uzytkownika.
    """
    if not path.exists():
        return path
    for counter in range(2, 1000):
        candidate = path.with_name(f"{path.stem}-{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise OSError(f"Za duzo plikow o nazwie {path.name}")


def select_chapters(chapters: list[ChapterRef], request: ConvertRequest) -> list[ChapterRef]:
    """Filtruje liste rozdzialow wg `selected` (wygrywa) albo zakresu start/end."""
    if request.selected:
        wanted = set(request.selected)
        return [chapter for chapter in chapters if chapter.index in wanted]

    start = request.start or 1
    end = request.end or len(chapters)
    return [chapter for chapter in chapters if start <= chapter.index <= end]
