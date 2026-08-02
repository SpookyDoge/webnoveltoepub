"""Persisted settings, the run log and the automatic-update scheduler."""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.jobs import KIND_UPDATE_ALL, start_update_all
from app.library import SettingsStore, utc_now
from app.main import app
from app.models import AppSettings, AutoUpdateRun, LibraryUpdateAllResponse
from app.progress import registry
from app.scheduler import UpdateScheduler


def _settings(tmp_path: Path) -> Settings:
    return Settings(library_path=tmp_path / "library.json")


# -- Storage ----------------------------------------------------------------


def test_defaults_are_off(tmp_path):
    stored = SettingsStore(_settings(tmp_path)).load()
    assert stored.auto_update_enabled is False
    assert stored.check_on_startup is False
    assert stored.auto_update_interval_hours == 24


def test_settings_round_trip(tmp_path):
    store = SettingsStore(_settings(tmp_path))
    store.save(AppSettings(auto_update_enabled=True, auto_update_interval_hours=6))

    reloaded = store.load()
    assert reloaded.auto_update_enabled is True
    assert reloaded.auto_update_interval_hours == 6


def test_interval_below_one_hour_is_rejected():
    """Anything shorter just hammers source sites for nothing."""
    with pytest.raises(ValueError):
        AppSettings(auto_update_interval_hours=0)


def test_settings_live_beside_the_library_not_inside_it(tmp_path):
    settings = _settings(tmp_path)
    store = SettingsStore(settings)
    store.save(AppSettings(auto_update_enabled=True))

    assert store.path != settings.resolved_library_path()
    assert store.path.name == "settings.json"


def test_corrupt_settings_fall_back_to_defaults(tmp_path):
    store = SettingsStore(_settings(tmp_path))
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{ broken", encoding="utf-8")

    assert store.load().auto_update_enabled is False


def test_run_log_keeps_only_the_most_recent(tmp_path):
    store = SettingsStore(_settings(tmp_path))
    for index in range(SettingsStore.MAX_RUNS + 5):
        store.record_run(
            AutoUpdateRun(
                started_at=utc_now(),
                finished_at=f"2026-01-01T00:00:{index:02d}+00:00",
                trigger="interval",
                checked=index,
            )
        )

    history = store.runs()
    assert len(history) == SettingsStore.MAX_RUNS
    assert history[-1].checked == SettingsStore.MAX_RUNS + 4


def test_saving_settings_does_not_wipe_the_run_log(tmp_path):
    store = SettingsStore(_settings(tmp_path))
    store.record_run(
        AutoUpdateRun(started_at=utc_now(), finished_at=utc_now(), trigger="interval")
    )
    store.save(AppSettings(auto_update_enabled=True))

    assert len(store.runs()) == 1


# -- Scheduling decisions ---------------------------------------------------


def _scheduler(tmp_path) -> UpdateScheduler:
    return UpdateScheduler(_settings(tmp_path))


def test_nothing_is_due_while_disabled(tmp_path):
    scheduler = _scheduler(tmp_path)
    assert scheduler._is_due(AppSettings(auto_update_enabled=False)) is False


def test_enabling_does_not_fire_immediately(tmp_path):
    """Turning it on should not stampede every site in the library at once."""
    scheduler = _scheduler(tmp_path)
    config = AppSettings(auto_update_enabled=True, auto_update_interval_hours=1)

    assert scheduler._is_due(config) is False
    # A baseline was written, so the first real run happens one interval later.
    assert scheduler.store.last_run_at() is not None


def test_due_once_the_interval_has_passed(tmp_path):
    scheduler = _scheduler(tmp_path)
    long_ago = (datetime.fromisoformat(utc_now()) - timedelta(hours=5)).isoformat(
        timespec="seconds"
    )
    scheduler.store.record_run(
        AutoUpdateRun(started_at=long_ago, finished_at=long_ago, trigger="interval")
    )

    config = AppSettings(auto_update_enabled=True, auto_update_interval_hours=2)
    assert scheduler._is_due(config) is True

    # ... but not with a longer interval.
    assert scheduler._is_due(
        AppSettings(auto_update_enabled=True, auto_update_interval_hours=12)
    ) is False


def test_next_run_is_one_interval_after_the_last(tmp_path):
    scheduler = _scheduler(tmp_path)
    stamp = "2026-01-01T00:00:00+00:00"
    scheduler.store.record_run(
        AutoUpdateRun(started_at=stamp, finished_at=stamp, trigger="interval")
    )

    config = AppSettings(auto_update_enabled=True, auto_update_interval_hours=6)
    assert scheduler._compute_next_run(config).startswith("2026-01-01T06:00")
    assert scheduler._compute_next_run(AppSettings(auto_update_enabled=False)) is None


def test_a_run_is_logged_and_reuses_update_all(tmp_path, monkeypatch):
    """The scheduler must not grow its own copy of the update logic.

    It patches the function the *job body* calls, which is the same one the
    manual button ends up in - proving there is a single execution path.
    """
    scheduler = _scheduler(tmp_path)
    calls: list[str] = []

    def fake_update_all(settings, emit=None, control=None):
        calls.append("called")
        return LibraryUpdateAllResponse(results=[], updated=2, failed=1)

    monkeypatch.setattr("app.jobs.update_all", fake_update_all)
    asyncio.run(scheduler._run_once("interval"))

    assert calls == ["called"]
    run = scheduler.store.runs()[-1]
    assert run.trigger == "interval"
    assert (run.updated, run.failed) == (2, 1)
    assert run.status == "ok"


def test_a_failing_run_is_logged_and_does_not_raise(tmp_path, monkeypatch):
    scheduler = _scheduler(tmp_path)

    def boom(settings, emit=None, control=None):
        raise RuntimeError("network down")

    monkeypatch.setattr("app.jobs.update_all", boom)
    asyncio.run(scheduler._run_once("interval"))

    run = scheduler.store.runs()[-1]
    assert run.failed == 1
    assert run.status == "error"


# -- One path for the button and the timer ----------------------------------


def _instant(settings, emit=None, control=None):
    return LibraryUpdateAllResponse(results=[], updated=0, failed=0)


def test_a_scheduled_job_is_shaped_exactly_like_a_manual_one(tmp_path, monkeypatch):
    """Same kind, same registry, same result type - only the label differs."""
    monkeypatch.setattr("app.jobs.update_all", _instant)

    manual = start_update_all(_settings(tmp_path))
    scheduled = start_update_all(_settings(tmp_path), trigger="interval")
    assert manual.wait(timeout=5) and scheduled.wait(timeout=5)

    assert manual.kind == scheduled.kind == KIND_UPDATE_ALL
    assert (manual.trigger, scheduled.trigger) == ("manual", "interval")
    # Found the same way, so every job endpoint works on both.
    assert registry.get(scheduled.id) is scheduled
    assert type(manual.result) is type(scheduled.result)


def test_a_scheduled_job_is_visible_and_controllable_over_http(tmp_path, monkeypatch):
    """The browser can find and steer a job it never started."""
    gate = threading.Event()

    def blocking(settings, emit=None, control=None):
        gate.wait(timeout=5)
        return LibraryUpdateAllResponse(results=[], updated=0, failed=0)

    monkeypatch.setattr("app.jobs.update_all", blocking)
    job = start_update_all(_settings(tmp_path), trigger="interval")

    try:
        with TestClient(app) as client:
            active = client.get("/api/jobs/active").json()
            assert active["job_id"] == job.id
            assert active["kind"] == KIND_UPDATE_ALL
            # This is what tells the UI to say "automatic", not "manual".
            assert active["trigger"] == "interval"

            # The very same control endpoints a manual run uses.
            for action in ("pause", "resume", "stop"):
                assert client.post(f"/api/jobs/{job.id}/{action}").status_code == 200
    finally:
        gate.set()
        job.wait(timeout=5)


def test_stop_over_http_really_halts_a_scheduled_run(tmp_path, monkeypatch):
    """Not just a 200: the work stops and what it managed is kept.

    Same guarantee the manual path makes in test_job_control.py, asserted here
    against a job the scheduler started.
    """
    from app import service
    from app.epub_builder import build_epub
    from app.library import Library
    from app.models import ChapterContent, ChapterRef, NovelMetadata

    settings = Settings(
        save_to_disk=True,
        output_dir=tmp_path / "output",
        library_path=tmp_path / "library.json",
        library_update_delay=0.0,
        request_delay=0.0,
    )
    settings.output_dir.mkdir(parents=True, exist_ok=True)

    fetched: list[int] = []

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

    class SlowParser:
        name = "royalroad"
        requires_playwright = False
        on_chapters_found = None

        def __init__(self, url):
            self.url = url

        def get_metadata(self, url):
            return NovelMetadata(title="N", source_url=self.url)

        def get_chapter_list(self, url):
            return [
                ChapterRef(index=i, title=f"Chapter {i}", url=f"{self.url}/chapter-{i}")
                for i in range(1, 9)
            ]

        def get_chapter_content(self, chapter):
            time.sleep(0.05)  # somewhere for Stop to land
            fetched.append(chapter.index)
            return ChapterContent(title=chapter.title, html="<p>Body</p>")

        def get_cover_image(self, metadata):
            return None

    class StubFetcher:
        def close(self):
            pass

    monkeypatch.setattr(
        service, "_make_parser", lambda url, s: (SlowParser(url), StubFetcher())
    )

    job = start_update_all(settings, trigger="interval")
    try:
        deadline = time.monotonic() + 5
        while not fetched and time.monotonic() < deadline:
            time.sleep(0.01)
        assert fetched, "the run never got going"

        with TestClient(app) as client:
            assert client.post(f"/api/jobs/{job.id}/stop").status_code == 200

        assert job.wait(timeout=10)
    finally:
        job.control.stop()
        job.wait(timeout=5)

    assert job.state == "stopped"
    assert len(fetched) < 14, "stop must land before both novels finish"
    # Partial progress is written out, exactly as a stopped manual run does.
    assert any(entry.chapter_count > 1 for entry in Library(settings).load())


def test_stop_on_an_automatic_run_is_logged_as_stopped(tmp_path, monkeypatch):
    """Partial by choice, so it must not be filed as a failure."""

    def stopped_midway(settings, emit=None, control=None):
        control.stop()  # what POST /api/jobs/{id}/stop does
        return LibraryUpdateAllResponse(results=[], updated=1, failed=0)

    monkeypatch.setattr("app.jobs.update_all", stopped_midway)
    scheduler = _scheduler(tmp_path)
    asyncio.run(scheduler._run_once("interval"))

    run = scheduler.store.runs()[-1]
    assert run.status == "stopped"
    # Whatever it managed is kept and reported, not discarded.
    assert run.updated == 1


def test_the_scheduler_stands_down_while_another_job_runs(tmp_path, monkeypatch):
    """Two passes would double the traffic and fight over the same files."""
    gate = threading.Event()
    monkeypatch.setattr("app.jobs.update_all", _instant)

    blocker = registry.run("convert", lambda emit, control: gate.wait(timeout=5))
    scheduler = _scheduler(tmp_path)
    scheduler.store.save(
        AppSettings(auto_update_enabled=True, auto_update_interval_hours=1)
    )
    stale = (datetime.fromisoformat(utc_now()) - timedelta(hours=5)).isoformat()
    scheduler.store.record_run(
        AutoUpdateRun(started_at=stale, finished_at=stale, trigger="interval")
    )

    before = set(registry._jobs)

    async def tick_briefly() -> None:
        task = asyncio.create_task(scheduler._loop())
        await asyncio.sleep(0.2)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    try:
        asyncio.run(tick_briefly())
        started = [
            registry._jobs[job_id]
            for job_id in set(registry._jobs) - before
            if registry._jobs[job_id].kind == KIND_UPDATE_ALL
        ]
        assert started == [], "the scheduler started a job while another was running"
        assert scheduler.store.runs()[-1].status == "skipped"
    finally:
        gate.set()
        blocker.wait(timeout=5)


def test_a_skipped_pass_does_not_postpone_the_real_one(tmp_path):
    """Counting a skip as a run would push the check a whole interval out."""
    store = SettingsStore(_settings(tmp_path))
    stamp = "2026-01-01T00:00:00+00:00"
    store.record_run(AutoUpdateRun(started_at=stamp, finished_at=stamp, trigger="interval"))
    store.record_run(
        AutoUpdateRun(
            started_at="2026-01-02T00:00:00+00:00",
            finished_at="2026-01-02T00:00:00+00:00",
            trigger="interval",
            status="skipped",
        )
    )

    assert store.last_run_at() == stamp


def test_only_one_skip_is_logged_per_postponement(tmp_path):
    """A long conversion would otherwise flood the 20-entry history."""
    scheduler = _scheduler(tmp_path)
    for _ in range(5):
        scheduler._stand_down("interval")

    assert [run.status for run in scheduler.store.runs()] == ["skipped"]


# -- HTTP -------------------------------------------------------------------


def test_settings_endpoints_round_trip():
    with TestClient(app) as client:
        original = client.get("/api/settings").json()
        try:
            updated = client.put(
                "/api/settings",
                json={
                    "auto_update_enabled": True,
                    "auto_update_interval_hours": 8,
                    "check_on_startup": True,
                },
            ).json()

            assert updated["auto_update_enabled"] is True
            assert updated["auto_update_interval_hours"] == 8
            assert "recent_runs" in updated
            assert "runs_in_background" in updated
            assert client.get("/api/settings").json()["auto_update_interval_hours"] == 8
        finally:
            client.put(
                "/api/settings",
                json={
                    "auto_update_enabled": original["auto_update_enabled"],
                    "auto_update_interval_hours": original["auto_update_interval_hours"],
                    "check_on_startup": original["check_on_startup"],
                },
            )


def test_settings_endpoint_rejects_a_sub_hour_interval():
    with TestClient(app) as client:
        response = client.put(
            "/api/settings",
            json={
                "auto_update_enabled": True,
                "auto_update_interval_hours": 0,
                "check_on_startup": False,
            },
        )
    assert response.status_code == 422
