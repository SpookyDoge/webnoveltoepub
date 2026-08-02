"""Persisted settings, the run log and the automatic-update scheduler."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.library import SettingsStore, utc_now
from app.main import app
from app.models import AppSettings, AutoUpdateRun, LibraryUpdateAllResponse
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
    """The scheduler must not grow its own copy of the update logic."""
    scheduler = _scheduler(tmp_path)
    calls: list[str] = []

    def fake_update_all(settings):
        calls.append("called")
        return LibraryUpdateAllResponse(results=[], updated=2, failed=1)

    monkeypatch.setattr("app.scheduler.update_all", fake_update_all)
    asyncio.run(scheduler._run_once("interval"))

    assert calls == ["called"]
    run = scheduler.store.runs()[-1]
    assert run.trigger == "interval"
    assert (run.updated, run.failed) == (2, 1)


def test_a_failing_run_is_logged_and_does_not_raise(tmp_path, monkeypatch):
    scheduler = _scheduler(tmp_path)

    def boom(settings):
        raise RuntimeError("network down")

    monkeypatch.setattr("app.scheduler.update_all", boom)
    asyncio.run(scheduler._run_once("interval"))

    assert scheduler.store.runs()[-1].failed == 1


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
