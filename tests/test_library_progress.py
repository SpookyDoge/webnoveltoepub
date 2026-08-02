"""The SSE contract the Convert tab's progress panel binds to.

The panel is plain JavaScript and the project has no frontend test runner, so
the part that can actually regress is tested here: a job started from the
Library must stream the exact event names and fields `jobPanel` reads, and its
job id must work with the same control endpoints a conversion uses.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import service
from app.config import Settings
from app.epub_builder import build_epub
from app.library import Library, entry_id
from app.main import app
from app.models import ChapterContent, ChapterRef, NovelMetadata

FIRST = "https://www.royalroad.com/fiction/1/first-novel"
SECOND = "https://www.royalroad.com/fiction/2/second-novel"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        save_to_disk=True,
        output_dir=tmp_path / "output",
        library_path=tmp_path / "library.json",
        library_update_delay=0.0,
        request_delay=0.0,
    )


class StubParser:
    """Reports `total_chapters` for whichever novel it is asked about."""

    name = "royalroad"
    requires_playwright = False
    on_chapters_found = None

    def __init__(self, total_chapters: int):
        self.total_chapters = total_chapters

    def get_metadata(self, url):
        return NovelMetadata(title=f"Novel at {url}", author="Author", source_url=url)

    def get_chapter_list(self, url):
        return [
            ChapterRef(index=i, title=f"Chapter {i}", url=f"{url}/chapter-{i}")
            for i in range(1, self.total_chapters + 1)
        ]

    def get_chapter_content(self, chapter):
        return ChapterContent(title=chapter.title, html=f"<p>Body {chapter.index}</p>")

    def get_cover_image(self, metadata):
        return None


class StubFetcher:
    def close(self):
        pass


def _seed(settings: Settings, url: str, title: str, chapters: int) -> None:
    """A library entry with a real EPUB behind it, so Update can append."""
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    path = settings.output_dir / f"{title.lower().replace(' ', '-')}.epub"
    path.write_bytes(
        build_epub(
            NovelMetadata(title=title, author="Author", source_url=url),
            [
                ChapterContent(title=f"Chapter {i}", html=f"<p>Body {i}</p>")
                for i in range(1, chapters + 1)
            ],
        )
    )
    Library(settings).upsert(
        Library.build_entry(
            source_url=url,
            parser_name="royalroad",
            title=title,
            author="Author",
            language="en",
            cover_url=None,
            file_path=path,
            chapter_count=chapters,
            last_chapter_url=f"{url}/chapter-{chapters}",
        )
    )


def _events(body: str) -> list[dict]:
    return [
        json.loads(line[6:])
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


def _drain(client: TestClient, job_id: str) -> list[dict]:
    with client.stream("GET", f"/api/jobs/{job_id}/events") as response:
        return _events("".join(response.iter_text()))


def _install(monkeypatch, settings: Settings, chapters: int) -> None:
    monkeypatch.setattr("app.main.settings", settings)
    monkeypatch.setattr(
        service, "_make_parser", lambda url, s: (StubParser(chapters), StubFetcher())
    )


# -- A single Update --------------------------------------------------------


def test_update_job_streams_everything_the_panel_renders(tmp_path, monkeypatch):
    """entry_started -> update_started -> chapter_downloaded -> entry_finished."""
    settings = _settings(tmp_path)
    _seed(settings, FIRST, "First Novel", chapters=3)
    _install(monkeypatch, settings, chapters=5)

    with TestClient(app) as client:
        job_id = client.post(f"/api/library/{entry_id(FIRST)}/update").json()["job_id"]
        events = _drain(client, job_id)

    by_type = {event["type"]: event for event in events}

    # The panel titles itself from this, before any chapter arrives.
    assert by_type["entry_started"]["title"] == "First Novel"
    # Sizes the bar: only the surplus is fetched, not the whole novel.
    assert by_type["update_started"]["new_chapters"] == 2
    # Drives the bar and the "X / Y chapters" counter.
    downloads = [e for e in events if e["type"] == "chapter_downloaded"]
    assert [e["index"] for e in downloads] == [1, 2]
    assert all(e["total"] == 2 for e in downloads)
    # Chooses the closing message, and whether a download link is offered.
    assert by_type["entry_finished"]["status"] == "updated"
    assert events[-1]["type"] == "done"


def test_an_up_to_date_novel_reports_a_status_but_no_bar(tmp_path, monkeypatch):
    """No update_started means the panel never shows chapter numbers."""
    settings = _settings(tmp_path)
    _seed(settings, FIRST, "First Novel", chapters=4)
    _install(monkeypatch, settings, chapters=4)

    with TestClient(app) as client:
        job_id = client.post(f"/api/library/{entry_id(FIRST)}/update").json()["job_id"]
        events = _drain(client, job_id)

    types = [event["type"] for event in events]
    assert "update_started" not in types
    assert "chapter_downloaded" not in types
    assert next(e for e in events if e["type"] == "entry_finished")["status"] == "up_to_date"


def test_the_library_job_id_accepts_the_shared_job_controls(tmp_path, monkeypatch):
    """Pause/Stop are the same endpoints a conversion uses - not a second path."""
    settings = _settings(tmp_path)
    _seed(settings, FIRST, "First Novel", chapters=1)
    _install(monkeypatch, settings, chapters=3)

    with TestClient(app) as client:
        job_id = client.post(f"/api/library/{entry_id(FIRST)}/update").json()["job_id"]
        for action in ("pause", "resume", "stop"):
            assert client.post(f"/api/jobs/{job_id}/{action}").status_code == 200
        _drain(client, job_id)


# -- Update all -------------------------------------------------------------


def test_update_all_streams_both_levels_of_context(tmp_path, monkeypatch):
    """"Updating 2 of 2: <title>" plus the chapter progress inside it."""
    settings = _settings(tmp_path)
    _seed(settings, FIRST, "First Novel", chapters=2)
    _seed(settings, SECOND, "Second Novel", chapters=2)
    _install(monkeypatch, settings, chapters=4)

    with TestClient(app) as client:
        job_id = client.post("/api/library/update-all").json()["job_id"]
        events = _drain(client, job_id)

    bulk = [e for e in events if e["type"] == "bulk_progress"]
    assert [e["index"] for e in bulk] == [1, 2]
    assert all(e["total"] == 2 for e in bulk)
    # Without a title the series line could only show bare numbers.
    assert {e["title"] for e in bulk} == {"First Novel", "Second Novel"}

    # Chapter events still arrive per novel, so the bar keeps moving inside one.
    assert [e["index"] for e in events if e["type"] == "chapter_downloaded"] == [1, 2, 1, 2]


def test_update_all_reports_the_series_size_before_the_first_novel(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    _seed(settings, FIRST, "First Novel", chapters=2)
    _seed(settings, SECOND, "Second Novel", chapters=2)
    _install(monkeypatch, settings, chapters=2)

    with TestClient(app) as client:
        job_id = client.post("/api/library/update-all").json()["job_id"]
        events = _drain(client, job_id)

    assert events[0]["type"] == "bulk_started"
    assert events[0]["total"] == 2
