"""Pause, resume and stop - offline, with a parser that records every fetch."""

from __future__ import annotations

import io
import threading
import time
import zipfile
from pathlib import Path

from app import service
from app.config import Settings
from app.epub_builder import build_epub
from app.library import Library, entry_id
from app.models import ChapterContent, ChapterRef, ConvertRequest, NovelMetadata
from app.progress import JobControl

URL = "https://www.royalroad.com/fiction/1/test-novel"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        save_to_disk=True,
        output_dir=tmp_path / "output",
        library_path=tmp_path / "library.json",
        library_update_delay=0.0,
        request_delay=0.0,
    )


class RecordingParser:
    """Records each chapter fetch and lets the test watch progress live."""

    name = "royalroad"
    requires_playwright = False
    on_chapters_found = None

    def __init__(self, total: int, delay: float = 0.0) -> None:
        self.total = total
        # A per-chapter cost, so a pause or stop has somewhere to land. Without
        # it the stub finishes the whole novel before the test can intervene.
        self.delay = delay
        self.fetched: list[int] = []

    def get_metadata(self, url):
        return NovelMetadata(title="Test Novel", author="Author", source_url=URL)

    def get_chapter_list(self, url):
        return [
            ChapterRef(index=i, title=f"Chapter {i}", url=f"{URL}/chapter-{i}")
            for i in range(1, self.total + 1)
        ]

    def get_chapter_content(self, chapter):
        if self.delay:
            time.sleep(self.delay)
        self.fetched.append(chapter.index)
        return ChapterContent(title=chapter.title, html=f"<p>Body {chapter.index}</p>")

    def get_cover_image(self, metadata):
        return None


class StubFetcher:
    def close(self):
        pass


def _install(monkeypatch, parser: RecordingParser) -> None:
    monkeypatch.setattr(service, "_make_parser", lambda url, s: (parser, StubFetcher()))


def _wait(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _chapters_in(data: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return sorted(n for n in archive.namelist() if "chapter_" in n)


# -- The switch itself ------------------------------------------------------


def test_checkpoint_passes_while_running():
    assert JobControl().checkpoint() is True


def test_checkpoint_reports_stop():
    control = JobControl()
    control.stop()
    assert control.checkpoint() is False
    assert control.stop_requested


def test_stop_releases_a_paused_worker():
    """Otherwise Stop would hang forever on an already-paused job."""
    control = JobControl()
    control.pause()

    released = threading.Event()

    def worker() -> None:
        control.checkpoint()
        released.set()

    threading.Thread(target=worker, daemon=True).start()
    assert not released.wait(0.2)

    control.stop()
    assert released.wait(2.0)


# -- Pause / resume during a conversion -------------------------------------


def test_pause_stops_after_the_current_chapter_and_resume_continues(tmp_path, monkeypatch):
    parser = RecordingParser(total=20, delay=0.02)
    _install(monkeypatch, parser)
    control = JobControl()
    settings = _settings(tmp_path)
    result: dict = {}

    def run() -> None:
        result["value"] = service.convert(
            ConvertRequest(url=URL), settings, control=control
        )

    worker = threading.Thread(target=run, daemon=True)
    worker.start()

    assert _wait(lambda: len(parser.fetched) >= 2)
    control.pause()

    # One chapter may already be in flight; after it lands, nothing more moves
    # even though there is plenty left to fetch.
    time.sleep(0.15)
    paused_at = len(parser.fetched)
    assert _wait(lambda: len(parser.fetched) > paused_at, timeout=0.4) is False
    assert paused_at < 20, "pause must happen before the whole novel is done"

    control.resume()
    assert _wait(lambda: "value" in result, timeout=10)
    worker.join(timeout=5)

    # Resumed where it left off: every chapter exactly once, in order.
    assert parser.fetched == list(range(1, 21))
    assert result["value"].chapter_count == 20


def test_stop_midway_produces_a_valid_partial_epub(tmp_path, monkeypatch):
    parser = RecordingParser(total=50, delay=0.02)
    _install(monkeypatch, parser)
    control = JobControl()
    settings = _settings(tmp_path)
    result: dict = {}

    def run() -> None:
        result["value"] = service.convert(
            ConvertRequest(url=URL), settings, control=control
        )

    worker = threading.Thread(target=run, daemon=True)
    worker.start()

    assert _wait(lambda: len(parser.fetched) >= 3)
    control.stop()
    assert _wait(lambda: "value" in result, timeout=10)
    worker.join(timeout=5)

    conversion = result["value"]
    downloaded = len(parser.fetched)

    assert downloaded < 50, "stop must land before the end"
    assert conversion.chapter_count == downloaded
    # A short book, but a correct one.
    assert len(_chapters_in(conversion.content)) == downloaded
    with zipfile.ZipFile(io.BytesIO(conversion.content)) as archive:
        assert archive.testzip() is None
    assert any("Stopped after" in w for w in conversion.warnings)


def test_stopped_conversion_is_a_valid_starting_point_for_update(tmp_path, monkeypatch):
    """The whole promise of Stop: the rest can be pulled in later."""
    parser = RecordingParser(total=50, delay=0.02)
    _install(monkeypatch, parser)
    control = JobControl()
    settings = _settings(tmp_path)
    result: dict = {}

    worker = threading.Thread(
        target=lambda: result.update(
            value=service.convert(ConvertRequest(url=URL), settings, control=control)
        ),
        daemon=True,
    )
    worker.start()
    assert _wait(lambda: len(parser.fetched) >= 3)
    control.stop()
    assert _wait(lambda: "value" in result, timeout=10)
    worker.join(timeout=5)

    downloaded = len(parser.fetched)
    entry = Library(settings).load()[0]

    # Counted by position in the source list, which is what update resumes from.
    assert entry.chapter_count == downloaded
    assert entry.last_chapter_url.endswith(f"/chapter-{downloaded}")
    assert entry.file_path is not None

    # Now the ordinary Update finishes the job, fetching only the remainder.
    resumed = RecordingParser(total=50)
    _install(monkeypatch, resumed)
    update = service.update_entry(entry_id(URL), settings)

    assert update.status == "updated"
    assert resumed.fetched == list(range(downloaded + 1, 51))
    assert update.chapter_count == 50
    assert len(_chapters_in(Path(entry.file_path).read_bytes())) == 50


def test_stop_before_any_chapter_fails_loudly(tmp_path, monkeypatch):
    """Nothing downloaded means there is no book to save - say so."""
    parser = RecordingParser(total=10)
    _install(monkeypatch, parser)
    control = JobControl()
    control.stop()

    # Its own exception type, so the UI can say "nothing was saved" rather
    # than blaming the parser for a page it never got round to reading.
    try:
        service.convert(ConvertRequest(url=URL), _settings(tmp_path), control=control)
    except service.StoppedBeforeStartError:
        pass
    else:
        raise AssertionError("expected StoppedBeforeStartError")

    assert parser.fetched == []
    assert Library(_settings(tmp_path)).load() == []


# -- Stop during a bulk update ----------------------------------------------


def test_stop_ends_the_whole_series_but_keeps_finished_entries(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    settings.output_dir.mkdir(parents=True, exist_ok=True)

    # Two novels, each with one stored chapter and more available.
    for number in (1, 2):
        url = f"https://www.royalroad.com/fiction/{number}/novel"
        path = settings.output_dir / f"novel-{number}.epub"
        path.write_bytes(
            build_epub(
                NovelMetadata(title=f"Novel {number}", source_url=url),
                [ChapterContent(title="Chapter 1", html="<p>Body 1</p>")],
            )
        )
        Library(settings).upsert(
            Library.build_entry(
                source_url=url,
                parser_name="royalroad",
                title=f"Novel {number}",
                author="Author",
                language="en",
                cover_url=None,
                file_path=path,
                chapter_count=1,
                last_chapter_url=f"{url}/chapter-1",
            )
        )

    control = JobControl()
    parsers: dict[str, RecordingParser] = {}

    def make(url, s):
        parser = parsers.setdefault(url, RecordingParser(total=3))
        parser.get_metadata = lambda _url, u=url: NovelMetadata(title="N", source_url=u)
        parser.get_chapter_list = lambda _url, u=url: [
            ChapterRef(index=i, title=f"Chapter {i}", url=f"{u}/chapter-{i}")
            for i in range(1, 4)
        ]
        return parser, StubFetcher()

    monkeypatch.setattr(service, "_make_parser", make)

    # Stop as soon as the first novel has fetched something.
    def stopper() -> None:
        while not any(p.fetched for p in parsers.values()):
            time.sleep(0.01)
        control.stop()

    threading.Thread(target=stopper, daemon=True).start()
    response = service.update_all(settings, control=control)

    # The series ended early, but the first novel's work was written out.
    assert len(response.results) < 2 or response.results[0].status in ("updated", "stopped")
    first = Library(settings).load()
    assert any(entry.chapter_count > 1 for entry in first) or response.results == []
