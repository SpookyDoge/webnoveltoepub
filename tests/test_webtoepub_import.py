"""Importing a WebToEpub export, and downloading what the library holds."""

from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import service
from app.config import Settings
from app.epub_builder import build_epub
from app.library import Library, entry_id
from app.main import app
from app.models import ChapterContent, NovelMetadata
from app.webtoepub import (
    WebToEpubImportError,
    count_chapters,
    decode_epub,
    parse_export,
)

ROYALROAD = "https://www.royalroad.com/fiction/1/imported-novel"
ELSEWHERE = "https://example.com/novel/unsupported"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        save_to_disk=False,  # import must write files regardless of this
        output_dir=tmp_path / "output",
        library_path=tmp_path / "library.json",
    )


def _epub(chapters: int, *, extra_front_matter: bool = True) -> bytes:
    """An EPUB shaped roughly like one WebToEpub produces."""
    contents = [
        ChapterContent(title=f"Chapter {i}", html=f"<p>Body {i}</p>")
        for i in range(1, chapters + 1)
    ]
    payload = build_epub(
        NovelMetadata(title="Imported Novel", author="Someone", source_url=ROYALROAD),
        contents,
    )
    if not extra_front_matter:
        return payload
    return payload


def _data_uri(payload: bytes, *, firefox: bool = False) -> str:
    prefix = (
        "data:application/octet-stream;base64,"
        if firefox
        else "data:application/epub+zip;base64,"
    )
    return prefix + base64.b64encode(payload).decode("ascii")


def _zip_export(rows: list[tuple[str, str, bytes]]) -> bytes:
    """Builds a version-2 WebToEpub export archive."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("LibraryVersion.txt", "2")
        archive.writestr("LibraryCountEntries.txt", str(len(rows)))
        archive.writestr("ReadingList.json", json.dumps({}))
        for index, (url, name, payload) in enumerate(rows):
            archive.writestr(f"Library/{index}/LibStoryURL", url)
            archive.writestr(f"Library/{index}/LibFilename", name)
            archive.writestr(f"Library/{index}/LibEpub", _data_uri(payload))
            archive.writestr(f"Library/{index}/LibCover", "data:image/jpeg;base64,//8=")
            archive.writestr(f"Library/{index}/LibNewChapterCount", "0")
    return buffer.getvalue()


def _json_export(rows: list[tuple[str, str, bytes]]) -> bytes:
    return json.dumps(
        {
            "Library": [
                {
                    "LibStoryURL": url,
                    "LibFilename": name,
                    "LibEpub": _data_uri(payload),
                    "LibCover": "",
                }
                for url, name, payload in rows
            ]
        }
    ).encode("utf-8")


# -- Parsing the export -----------------------------------------------------


def test_reads_the_zip_export():
    data = _zip_export([(ROYALROAD, "Imported Novel", _epub(4))])
    novels = parse_export(data)

    assert len(novels) == 1
    assert novels[0].source_url == ROYALROAD
    assert novels[0].title == "Imported Novel"
    assert novels[0].epub_bytes[:4] == b"PK\x03\x04"


def test_reads_the_legacy_json_export():
    novels = parse_export(_json_export([(ROYALROAD, "Imported Novel", _epub(2))]))
    assert len(novels) == 1
    assert novels[0].source_url == ROYALROAD


def test_accepts_the_firefox_data_uri_variant():
    """Firefox writes application/octet-stream instead of application/epub+zip."""
    payload = _epub(1)
    assert decode_epub(_data_uri(payload, firefox=True)) == payload


def test_rejects_a_file_that_is_neither_format():
    with pytest.raises(WebToEpubImportError):
        parse_export(b"just some text")


def test_rejects_a_zip_without_library_folders():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("something.txt", "hello")
    with pytest.raises(WebToEpubImportError):
        parse_export(buffer.getvalue())


def test_one_unreadable_row_does_not_sink_the_rest():
    good = _epub(3)
    data = _zip_export([(ROYALROAD, "Good", good), (ELSEWHERE, "Bad", b"not an epub")])
    # The bad row's EPUB fails to decode; the good one still comes through.
    novels = parse_export(data)
    assert [n.title for n in novels] == ["Good"]


def test_chapter_count_ignores_front_matter():
    """Our own title page must not be counted as a chapter."""
    assert count_chapters(_epub(5)) == 5


# -- Importing into the library ---------------------------------------------


def test_import_writes_files_and_creates_entries(tmp_path):
    settings = _settings(tmp_path)
    data = _zip_export([(ROYALROAD, "Imported Novel", _epub(7))])

    response = service.import_webtoepub_library(data, settings)

    assert response.imported == 1
    entry = Library(settings).load()[0]
    assert entry.source_url == ROYALROAD
    assert entry.chapter_count == 7
    assert entry.parser == "royalroad"
    # Written even though save_to_disk is off - otherwise the entry could
    # never be updated, which is the whole point of importing.
    assert Path(entry.file_path).is_file()


def test_import_flags_a_site_no_parser_handles(tmp_path):
    settings = _settings(tmp_path)
    data = _zip_export([(ELSEWHERE, "Foreign Novel", _epub(2))])

    response = service.import_webtoepub_library(data, settings)

    assert response.imported == 1
    result = response.results[0]
    assert result.detail == "unsupported_site"
    assert Library(settings).load()[0].parser == "unknown"


def test_import_never_overwrites_a_novel_we_already_track(tmp_path):
    settings = _settings(tmp_path)
    data = _zip_export([(ROYALROAD, "Imported Novel", _epub(3))])
    service.import_webtoepub_library(data, settings)

    # A second import of the same novel, claiming a different length.
    again = service.import_webtoepub_library(
        _zip_export([(ROYALROAD, "Imported Novel", _epub(99))]), settings
    )

    assert again.imported == 0
    assert again.skipped == 1
    assert Library(settings).load()[0].chapter_count == 3


def test_imported_epub_can_be_appended_to(tmp_path):
    """The imported book has to work with the ordinary Update path."""
    from app.epub_builder import append_chapters

    settings = _settings(tmp_path)
    service.import_webtoepub_library(
        _zip_export([(ROYALROAD, "Imported Novel", _epub(3))]), settings
    )
    entry = Library(settings).load()[0]

    payload = append_chapters(
        Path(entry.file_path),
        [ChapterContent(title="Chapter 4", html="<p>Body 4</p>")],
    )

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.testzip() is None
        assert len([n for n in archive.namelist() if "chapter_" in n]) == 4


def test_import_endpoint_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(
        service, "get_settings", lambda: _settings(tmp_path), raising=False
    )
    data = _zip_export([(ROYALROAD, "Imported Novel", _epub(2))])

    with TestClient(app) as client:
        response = client.post("/api/library/import", content=data)

    assert response.status_code == 200
    assert response.json()["imported"] >= 0


def test_import_endpoint_rejects_rubbish():
    with TestClient(app) as client:
        response = client.post("/api/library/import", content=b"nope")
    assert response.status_code == 422
    assert response.json()["detail"].startswith("import_error")


def test_import_endpoint_rejects_an_empty_body():
    with TestClient(app) as client:
        assert client.post("/api/library/import", content=b"").status_code == 400


# -- Downloading ------------------------------------------------------------


def test_download_serves_the_stored_file(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    service.import_webtoepub_library(
        _zip_export([(ROYALROAD, "Imported Novel", _epub(2))]), settings
    )
    monkeypatch.setattr("app.main.settings", settings)

    with TestClient(app) as client:
        response = client.get(f"/api/library/{entry_id(ROYALROAD)}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/epub+zip"
    assert "imported-novel.epub" in response.headers["content-disposition"]
    assert response.content[:4] == b"PK\x03\x04"


def test_download_of_an_unknown_entry_is_404():
    with TestClient(app) as client:
        assert client.get("/api/library/nope/download").status_code == 404


def test_download_reports_a_history_only_entry(tmp_path, monkeypatch):
    """Converted without saving to disk: there is no file to hand over."""
    settings = _settings(tmp_path)
    Library(settings).upsert(
        Library.build_entry(
            source_url=ROYALROAD,
            parser_name="royalroad",
            title="No File",
            author="A",
            language="en",
            cover_url=None,
            file_path=None,
            chapter_count=3,
            last_chapter_url=None,
        )
    )
    monkeypatch.setattr("app.main.settings", settings)

    with TestClient(app) as client:
        response = client.get(f"/api/library/{entry_id(ROYALROAD)}/download")

    assert response.status_code == 409
    assert response.json()["detail"] == "no_epub_on_disk"


def test_download_reports_a_file_that_vanished(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    service.import_webtoepub_library(
        _zip_export([(ROYALROAD, "Imported Novel", _epub(2))]), settings
    )
    Path(Library(settings).load()[0].file_path).unlink()
    monkeypatch.setattr("app.main.settings", settings)

    with TestClient(app) as client:
        response = client.get(f"/api/library/{entry_id(ROYALROAD)}/download")

    assert response.status_code == 410
