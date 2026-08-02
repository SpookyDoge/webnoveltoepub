"""Library registry and incremental updates - offline, no network."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app import service
from app.config import Settings
from app.epub_builder import build_epub
from app.library import Library, entry_id, utc_now
from app.models import ChapterContent, ChapterRef, NovelMetadata

SOURCE_URL = "https://www.royalroad.com/fiction/1/test-novel"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        save_to_disk=True,
        output_dir=tmp_path / "output",
        library_path=tmp_path / "library.json",
        library_update_delay=0.0,
        request_delay=0.0,
    )


def _chapter(index: int) -> ChapterRef:
    return ChapterRef(index=index, title=f"Chapter {index}", url=f"{SOURCE_URL}/chapter-{index}")


def _metadata(title: str = "Test Novel", url: str = SOURCE_URL) -> NovelMetadata:
    return NovelMetadata(title=title, author="Author", source_url=url)


class StubParser:
    """Serves a chapter list of a chosen length and counts what gets fetched."""

    name = "royalroad"
    requires_playwright = False
    on_chapters_found = None

    def __init__(self, total_chapters: int, metadata: NovelMetadata | None = None):
        self.total_chapters = total_chapters
        self.metadata = metadata or _metadata()
        self.fetched: list[int] = []

    def get_metadata(self, url):
        return self.metadata.model_copy()

    def get_chapter_list(self, url):
        chapters = [_chapter(i) for i in range(1, self.total_chapters + 1)]
        self.report_chapters(chapters)
        return chapters

    def report_chapters(self, chapters):
        if self.on_chapters_found:
            self.on_chapters_found(list(chapters))

    def get_chapter_content(self, chapter):
        # The whole point of an update: this must only run for new chapters.
        self.fetched.append(chapter.index)
        return ChapterContent(title=chapter.title, html=f"<p>Body {chapter.index}</p>")

    def get_cover_image(self, metadata):
        return None


class StubFetcher:
    def close(self):
        pass


def _install(monkeypatch, parser: StubParser) -> None:
    monkeypatch.setattr(service, "_make_parser", lambda url, s: (parser, StubFetcher()))


def _seed_library(settings: Settings, chapter_count: int, *, with_file: bool = True) -> Path | None:
    """A library entry whose EPUB already holds `chapter_count` chapters."""
    file_path = None
    if with_file:
        settings.output_dir.mkdir(parents=True, exist_ok=True)
        file_path = settings.output_dir / "test-novel.epub"
        file_path.write_bytes(
            build_epub(
                _metadata(),
                [
                    ChapterContent(title=f"Chapter {i}", html=f"<p>Body {i}</p>")
                    for i in range(1, chapter_count + 1)
                ],
            )
        )

    Library(settings).upsert(
        Library.build_entry(
            source_url=SOURCE_URL,
            parser_name="royalroad",
            title="Test Novel",
            author="Author",
            language="en",
            cover_url=None,
            file_path=file_path,
            chapter_count=chapter_count,
            last_chapter_url=_chapter(chapter_count).url,
        )
    )
    return file_path


def _chapter_count_in(path: Path) -> int:
    with zipfile.ZipFile(io.BytesIO(path.read_bytes())) as archive:
        return sum(1 for name in archive.namelist() if "chapter_" in name)


# -- Registry ---------------------------------------------------------------


def test_entry_id_is_derived_from_the_source_url():
    assert entry_id(SOURCE_URL) == entry_id(SOURCE_URL)
    assert entry_id(SOURCE_URL) != entry_id(SOURCE_URL + "-other")


def test_empty_library_when_the_file_is_missing(tmp_path):
    assert Library(_settings(tmp_path)).load() == []


def test_upsert_replaces_the_row_and_keeps_created_at(tmp_path):
    settings = _settings(tmp_path)
    library = Library(settings)
    _seed_library(settings, 5)

    first = library.load()[0]
    library.upsert(first.model_copy(update={"chapter_count": 9, "created_at": "2099-01-01"}))

    entries = library.load()
    assert len(entries) == 1
    assert entries[0].chapter_count == 9
    assert entries[0].created_at == first.created_at


def test_corrupt_library_does_not_take_the_app_down(tmp_path):
    settings = _settings(tmp_path)
    settings.library_path.parent.mkdir(parents=True, exist_ok=True)
    settings.library_path.write_text("{ not json", encoding="utf-8")
    assert Library(settings).load() == []


def test_delete_can_keep_or_remove_the_file(tmp_path):
    settings = _settings(tmp_path)
    file_path = _seed_library(settings, 2)
    key = entry_id(SOURCE_URL)

    assert Library(settings).delete(key, delete_file=False) is not None
    assert file_path.is_file()
    assert Library(settings).load() == []

    _seed_library(settings, 2)
    Library(settings).delete(key, delete_file=True)
    assert not file_path.is_file()


def test_delete_unknown_entry_returns_none(tmp_path):
    assert Library(_settings(tmp_path)).delete("nope") is None


# -- Recording conversions --------------------------------------------------


def test_conversion_records_an_entry(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    _install(monkeypatch, StubParser(total_chapters=3))

    from app.models import ConvertRequest

    service.convert(ConvertRequest(url=SOURCE_URL), settings)

    entries = Library(settings).load()
    assert len(entries) == 1
    assert entries[0].chapter_count == 3
    assert entries[0].file_path is not None


def test_entry_is_recorded_even_without_saving_to_disk(tmp_path, monkeypatch):
    """History still worth keeping; it just cannot be topped up later."""
    settings = _settings(tmp_path).model_copy(update={"save_to_disk": False})
    _install(monkeypatch, StubParser(total_chapters=3))

    from app.models import ConvertRequest

    service.convert(ConvertRequest(url=SOURCE_URL), settings)

    entry = Library(settings).load()[0]
    assert entry.file_path is None


# -- Incremental update -----------------------------------------------------


def test_update_fetches_only_the_new_chapters(tmp_path, monkeypatch):
    """10 stored, 13 on the source - exactly 3 downloads, not 13."""
    settings = _settings(tmp_path)
    file_path = _seed_library(settings, 10)
    parser = StubParser(total_chapters=13)
    _install(monkeypatch, parser)

    result = service.update_entry(entry_id(SOURCE_URL), settings)

    assert result.status == "updated"
    assert result.added_chapters == 3
    assert result.chapter_count == 13
    assert parser.fetched == [11, 12, 13]
    assert _chapter_count_in(file_path) == 13


def test_update_appends_to_the_existing_file(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    file_path = _seed_library(settings, 2)
    _install(monkeypatch, StubParser(total_chapters=4))

    service.update_entry(entry_id(SOURCE_URL), settings)

    with zipfile.ZipFile(io.BytesIO(file_path.read_bytes())) as archive:
        assert archive.testzip() is None
        names = sorted(n for n in archive.namelist() if "chapter_" in n)
        assert len(names) == 4
        # The originals survived rather than being rebuilt from nothing.
        assert b"Body 1" in archive.read(names[0])
        assert b"Body 4" in archive.read(names[3])


def test_update_records_the_new_count(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    _seed_library(settings, 5)
    _install(monkeypatch, StubParser(total_chapters=7))

    service.update_entry(entry_id(SOURCE_URL), settings)

    entry = Library(settings).load()[0]
    assert entry.chapter_count == 7
    assert entry.last_chapter_url.endswith("/chapter-7")


def test_update_with_nothing_new_downloads_nothing(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    _seed_library(settings, 6)
    parser = StubParser(total_chapters=6)
    _install(monkeypatch, parser)

    result = service.update_entry(entry_id(SOURCE_URL), settings)

    assert result.status == "up_to_date"
    assert parser.fetched == []


def test_update_without_a_file_is_reported_not_silently_rebuilt(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    _seed_library(settings, 4, with_file=False)
    parser = StubParser(total_chapters=9)
    _install(monkeypatch, parser)

    result = service.update_entry(entry_id(SOURCE_URL), settings)

    assert result.status == "no_file"
    assert parser.fetched == []


def test_update_of_unknown_entry_raises(tmp_path):
    with pytest.raises(service.LibraryEntryNotFoundError):
        service.update_entry("does-not-exist", _settings(tmp_path))


def test_update_notices_a_shifted_chapter_list(tmp_path, monkeypatch):
    """Stored marker no longer at the expected position - flagged, not ignored."""
    settings = _settings(tmp_path)
    _seed_library(settings, 5)

    library = Library(settings)
    entry = library.load()[0]
    library.upsert(entry.model_copy(update={"last_chapter_url": f"{SOURCE_URL}/chapter-999"}))

    _install(monkeypatch, StubParser(total_chapters=8))
    result = service.update_entry(entry_id(SOURCE_URL), settings)

    assert result.status == "updated"
    assert "chapter_list_shifted" in (result.detail or "")


# -- Bulk update ------------------------------------------------------------


def test_update_all_walks_every_entry(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    _seed_library(settings, 10)

    second_url = "https://www.royalroad.com/fiction/2/second-novel"
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    second_file = settings.output_dir / "second-novel.epub"
    second_file.write_bytes(
        build_epub(
            _metadata("Second Novel", second_url),
            [ChapterContent(title="Chapter 1", html="<p>Body 1</p>")],
        )
    )
    Library(settings).upsert(
        Library.build_entry(
            source_url=second_url,
            parser_name="royalroad",
            title="Second Novel",
            author="Author",
            language="en",
            cover_url=None,
            file_path=second_file,
            chapter_count=1,
            last_chapter_url=f"{SOURCE_URL}/chapter-1",
        )
    )

    parsers = {SOURCE_URL: StubParser(13), second_url: StubParser(2)}
    monkeypatch.setattr(
        service,
        "_make_parser",
        lambda url, s: (parsers[url], StubFetcher()),
    )

    response = service.update_all(settings)

    assert response.updated == 2
    assert response.failed == 0
    assert {r.added_chapters for r in response.results} == {3, 1}
    assert parsers[SOURCE_URL].fetched == [11, 12, 13]
    assert parsers[second_url].fetched == [2]


def test_update_all_keeps_going_when_one_novel_fails(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    _seed_library(settings, 10)

    second_url = "https://www.royalroad.com/fiction/2/second-novel"
    Library(settings).upsert(
        Library.build_entry(
            source_url=second_url,
            parser_name="royalroad",
            title="Second Novel",
            author="Author",
            language="en",
            cover_url=None,
            file_path=None,
            chapter_count=1,
            last_chapter_url=None,
        )
    )

    def make(url, s):
        if url == second_url:
            raise RuntimeError("site is down")
        return StubParser(11), StubFetcher()

    monkeypatch.setattr(service, "_make_parser", make)

    response = service.update_all(settings)
    statuses = {r.title: r.status for r in response.results}

    assert statuses["Test Novel"] == "updated"
    # No file, so it never even reaches the parser that would have blown up.
    assert statuses["Second Novel"] == "no_file"
    assert response.updated == 1


def test_update_all_on_an_empty_library(tmp_path):
    response = service.update_all(_settings(tmp_path))
    assert response.results == []
    assert response.updated == 0


# -- Timestamps -------------------------------------------------------------


def test_utc_now_is_iso_8601():
    assert "T" in utc_now()
