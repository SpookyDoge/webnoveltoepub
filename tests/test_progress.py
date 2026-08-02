"""The shared progress mechanism: job registry, SSE stream, and its wiring."""

from __future__ import annotations

import json
import threading
import time

from fastapi.testclient import TestClient

from app import service
from app.main import app
from app.models import ChapterContent, ChapterRef, NovelMetadata, PreviewResponse
from app.progress import Job, JobRegistry, _format_sse


def _events(chunks: list[str]) -> list[dict]:
    """Parses SSE text back into event payloads, ignoring keep-alives."""
    parsed = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.startswith("data: "):
                parsed.append(json.loads(line[6:]))
    return parsed


# -- Formatting -------------------------------------------------------------


def test_sse_frame_has_an_event_name_and_json_data():
    frame = _format_sse({"type": "chapter_downloaded", "index": 3})
    assert frame.startswith("event: chapter_downloaded\n")
    assert '"index": 3' in frame
    assert frame.endswith("\n\n")


def test_sse_data_is_not_ascii_escaped():
    """Chapter titles are not English; escaping would bloat every frame."""
    assert "Zażółć" in _format_sse({"type": "x", "title": "Zażółć"})


# -- Registry ---------------------------------------------------------------


def test_run_executes_the_worker_and_stores_its_result():
    registry = JobRegistry()
    job = registry.run("test", lambda emit: "the result")

    for _ in range(50):
        if job.finished:
            break
        time.sleep(0.01)

    assert job.status == "done"
    assert job.result == "the result"


def test_a_failing_worker_becomes_an_error_event():
    registry = JobRegistry()
    job = registry.run("test", lambda emit: 1 / 0)

    events = _events(list(registry.stream(job)))

    assert events[-1]["type"] == "error"
    assert "ZeroDivisionError" in events[-1]["detail"]
    assert job.status == "error"


def test_stream_replays_history_for_a_late_subscriber():
    """A browser that connects a moment late still sees the whole story."""
    registry = JobRegistry()
    job = Job(id="x", kind="test")
    job.emit("chapters_found", total=2)
    job.emit("chapters_found", total=4)
    job.finish()

    events = _events(list(registry.stream(job)))

    assert [e["type"] for e in events] == ["chapters_found", "chapters_found", "done"]
    assert [e.get("total") for e in events[:2]] == [2, 4]


def test_stream_delivers_no_duplicates_when_following_live():
    registry = JobRegistry()
    job = Job(id="x", kind="test")
    job.emit("first", n=1)

    collected: list[dict] = []

    def consume() -> None:
        collected.extend(_events(list(registry.stream(job))))

    reader = threading.Thread(target=consume)
    reader.start()
    time.sleep(0.05)
    job.emit("second", n=2)
    job.finish()
    reader.join(timeout=5)

    assert [e["type"] for e in collected] == ["first", "second", "done"]


def test_stream_ends_on_a_job_that_already_finished():
    registry = JobRegistry()
    job = Job(id="x", kind="test")
    job.finish()
    assert [e["type"] for e in _events(list(registry.stream(job)))] == ["done"]


def test_expired_jobs_are_evicted():
    registry = JobRegistry()
    job = registry.create("test")
    job.finish()
    job.finished_at = time.monotonic() - 10_000

    registry.create("another")

    assert registry.get(job.id) is None


# -- Wiring into the service layer ------------------------------------------


class StubParser:
    name = "royalroad"
    requires_playwright = False
    on_chapters_found = None

    def get_metadata(self, url):
        return NovelMetadata(title="Novel", author="Author", source_url=url)

    def get_chapter_list(self, url):
        chapters = [
            ChapterRef(index=i, title=f"Chapter {i}", url=f"{url}/c{i}") for i in range(1, 4)
        ]
        # Two batches, as a paginated table of contents would arrive.
        self.report_chapters(chapters[:2])
        self.report_chapters(chapters[2:])
        return chapters

    def report_chapters(self, chapters):
        if self.on_chapters_found:
            self.on_chapters_found(list(chapters))

    def get_chapter_content(self, chapter):
        return ChapterContent(title=chapter.title, html="<p>Body</p>")

    def get_cover_image(self, metadata):
        return None


class StubFetcher:
    def close(self):
        pass


def test_preview_emits_metadata_then_each_batch(monkeypatch):
    monkeypatch.setattr(service, "_make_parser", lambda url, s: (StubParser(), StubFetcher()))
    seen: list[tuple[str, dict]] = []

    result = service.preview(
        "https://www.royalroad.com/fiction/1/x",
        emit=lambda event_type, **data: seen.append((event_type, data)),
    )

    assert isinstance(result, PreviewResponse)
    assert [name for name, _ in seen] == ["metadata", "chapters_found", "chapters_found"]
    # Running total, so the UI can show a count without keeping its own tally.
    assert [data["total"] for name, data in seen if name == "chapters_found"] == [2, 3]
    assert len(seen[1][1]["chapters"]) == 2


def test_preview_detaches_the_hook_afterwards(monkeypatch):
    """A parser instance must not keep emitting into a finished job."""
    parser = StubParser()
    monkeypatch.setattr(service, "_make_parser", lambda url, s: (parser, StubFetcher()))

    service.preview("https://www.royalroad.com/fiction/1/x", emit=lambda *a, **k: None)

    assert parser.on_chapters_found is None


def test_convert_emits_progress_per_chapter(monkeypatch, tmp_path):
    from app.config import Settings
    from app.models import ConvertRequest

    monkeypatch.setattr(service, "_make_parser", lambda url, s: (StubParser(), StubFetcher()))
    settings = Settings(library_path=tmp_path / "library.json")
    seen: list[tuple[str, dict]] = []

    service.convert(
        ConvertRequest(url="https://www.royalroad.com/fiction/1/x"),
        settings,
        emit=lambda event_type, **data: seen.append((event_type, data)),
    )

    downloads = [data for name, data in seen if name == "chapter_downloaded"]
    assert [d["index"] for d in downloads] == [1, 2, 3]
    assert all(d["total"] == 3 for d in downloads)
    assert not any(d["failed"] for d in downloads)
    assert ("stage", {"stage": "building"}) in seen


def test_a_failed_chapter_is_flagged_but_does_not_stop_the_run(monkeypatch, tmp_path):
    """Existing behaviour kept: warning + placeholder, conversion completes."""
    from app.config import Settings
    from app.models import ConvertRequest
    from app.parsers import ParserError

    class Flaky(StubParser):
        def get_chapter_content(self, chapter):
            if chapter.index == 2:
                raise ParserError("boom")
            return ChapterContent(title=chapter.title, html="<p>Body</p>")

    monkeypatch.setattr(service, "_make_parser", lambda url, s: (Flaky(), StubFetcher()))
    seen: list[tuple[str, dict]] = []

    result = service.convert(
        ConvertRequest(url="https://www.royalroad.com/fiction/1/x"),
        Settings(library_path=tmp_path / "library.json"),
        emit=lambda event_type, **data: seen.append((event_type, data)),
    )

    downloads = [data for name, data in seen if name == "chapter_downloaded"]
    assert [d["failed"] for d in downloads] == [False, True, False]
    assert result.chapter_count == 3
    assert len(result.warnings) == 1


# -- HTTP -------------------------------------------------------------------


def test_events_endpoint_streams_until_done(monkeypatch):
    monkeypatch.setattr(service, "_make_parser", lambda url, s: (StubParser(), StubFetcher()))

    with TestClient(app) as client:
        job_id = client.post(
            "/api/jobs/preview", json={"url": "https://www.royalroad.com/fiction/1/x"}
        ).json()["job_id"]

        with client.stream("GET", f"/api/jobs/{job_id}/events") as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            # Proxies buffer by default, which would defeat the whole feature.
            assert response.headers["x-accel-buffering"] == "no"
            body = "".join(response.iter_text())

    types = [event["type"] for event in _events([body])]
    assert types[0] == "metadata"
    assert "chapters_found" in types
    assert types[-1] == "done"


def test_result_is_available_after_the_job_finishes(monkeypatch):
    monkeypatch.setattr(service, "_make_parser", lambda url, s: (StubParser(), StubFetcher()))

    with TestClient(app) as client:
        job_id = client.post(
            "/api/jobs/preview", json={"url": "https://www.royalroad.com/fiction/1/x"}
        ).json()["job_id"]
        with client.stream("GET", f"/api/jobs/{job_id}/events") as response:
            list(response.iter_text())

        payload = client.get(f"/api/jobs/{job_id}/result").json()

    assert payload["parser"] == "royalroad"
    assert len(payload["chapters"]) == 3


def test_unknown_job_is_404():
    with TestClient(app) as client:
        assert client.get("/api/jobs/nope/events").status_code == 404
        assert client.get("/api/jobs/nope/result").status_code == 404


def test_invalid_url_is_rejected_before_a_job_starts():
    with TestClient(app) as client:
        response = client.post("/api/jobs/preview", json={"url": "file:///etc/passwd"})
    assert response.status_code == 400
