"""Background scheduler for automatic library updates.

A plain asyncio task rather than APScheduler: there is exactly one periodic
job, the app already owns an event loop, and the loop body just hands work to
a thread. A dependency would add install weight (and one more thing to bundle
into the .exe) to replace roughly twenty lines.

The loop wakes on a short tick instead of sleeping the whole interval, so a
settings change applies without restarting anything - and so does an explicit
nudge from PUT /api/settings.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timedelta

from .config import Settings, get_settings
from .jobs import start_update_all
from .library import SettingsStore, utc_now
from .models import AutoUpdateRun
from .progress import registry

log = logging.getLogger(__name__)

#: Delay before the startup check. Long enough for the app to finish booting
#: and for the user to reach the UI and turn it off if it was a mistake.
STARTUP_DELAY_SECONDS = 30.0

#: How often the loop re-reads settings. Also the worst-case lag before a
#: settings change is noticed if the wake-up nudge is missed.
TICK_SECONDS = 60.0


class UpdateScheduler:
    """Runs `update_all` on an interval, driven by persisted settings."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.store = SettingsStore(self.settings)
        # Created in start(), not here: an asyncio.Event binds to the loop that
        # first awaits it, and this object is built at import time - long
        # before any loop exists, and potentially reused across several.
        self._wakeup: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self._running = False
        #: Guards against one skip entry per tick while a long job runs.
        self._skip_recorded = False
        self.next_run_at: str | None = None

    # -- Lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self._task is None:
            self._wakeup = asyncio.Event()
            self._task = asyncio.create_task(self._loop(), name="auto-update")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        self._wakeup = None

    def nudge(self) -> None:
        """Tells the loop settings changed, so it re-plans immediately."""
        if self._wakeup is not None:
            self._wakeup.set()

    # -- The loop -----------------------------------------------------------

    async def _loop(self) -> None:
        startup_due: float | None = None
        if self.store.load().check_on_startup:
            startup_due = asyncio.get_running_loop().time() + STARTUP_DELAY_SECONDS
            log.info("Startup library check scheduled in %ss", int(STARTUP_DELAY_SECONDS))

        while True:
            try:
                config = self.store.load()
                now = asyncio.get_running_loop().time()

                if startup_due is not None and now >= startup_due:
                    # Stand down rather than run alongside: two passes would
                    # double the traffic to the same sites and fight over the
                    # same EPUB files. `startup_due` stays set, so the check
                    # happens as soon as the slot is free.
                    if registry.active() is not None:
                        self._stand_down("startup")
                    else:
                        startup_due = None
                        await self._run_once("startup")
                        continue

                self.next_run_at = self._compute_next_run(config)
                if self._is_due(config):
                    if registry.active() is None:
                        await self._run_once("interval")
                        continue
                    self._stand_down("interval")

                await self._sleep_tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the loop must outlive any failure
                log.exception("Auto-update loop hit an error; continuing")
                await self._sleep_tick()

    async def _sleep_tick(self) -> None:
        if self._wakeup is None:
            await asyncio.sleep(TICK_SECONDS)
            return
        try:
            await asyncio.wait_for(self._wakeup.wait(), timeout=TICK_SECONDS)
        except TimeoutError:
            pass
        finally:
            self._wakeup.clear()

    def _is_due(self, config) -> bool:
        if not config.auto_update_enabled or self._running:
            return False
        last = self.store.last_run_at()
        if last is None:
            # Enabling it should not immediately hammer every site; the first
            # automatic pass happens one interval later. "Check on startup" is
            # the switch for people who want one right away.
            self.store.record_run(
                AutoUpdateRun(
                    started_at=utc_now(),
                    finished_at=utc_now(),
                    trigger="baseline",
                    checked=0,
                )
            )
            return False
        return _parse(last) + timedelta(hours=config.auto_update_interval_hours) <= _now()

    def _compute_next_run(self, config) -> str | None:
        if not config.auto_update_enabled:
            return None
        last = self.store.last_run_at()
        if last is None:
            return None
        due = _parse(last) + timedelta(hours=config.auto_update_interval_hours)
        return due.isoformat(timespec="seconds")

    def _stand_down(self, trigger: str) -> None:
        """Notes that a pass was postponed because something else was running.

        Recorded once per postponement, not once per tick: a long manual
        conversion would otherwise fill the whole 20-entry history with
        skips. `last_run_at` ignores these, so the pass stays due and starts
        as soon as the slot frees up.
        """
        log.info("Automatic check (%s) postponed - another job is running", trigger)
        if self._skip_recorded:
            return
        self._skip_recorded = True
        self.store.record_run(
            AutoUpdateRun(
                started_at=utc_now(),
                finished_at=utc_now(),
                trigger=trigger,
                status="skipped",
            )
        )

    async def _run_once(self, trigger: str) -> None:
        """Runs one pass. Never raises - a failed check must not kill the loop.

        The work itself goes through `start_update_all`, exactly as the manual
        button does: same registry, same job id, same SSE stream, same
        pause/stop endpoints. This method only decides *when*.
        """
        self._running = True
        self._skip_recorded = False
        started = utc_now()
        status = "ok"
        checked = updated = failed = 0
        try:
            log.info("Automatic library check started (%s)", trigger)
            job = start_update_all(self.settings, trigger)
            # Blocks a worker thread, not the loop, so ticks keep happening.
            await asyncio.to_thread(job.wait)

            if job.status == "error":
                status, failed = "error", 1
                log.warning("Automatic check failed: %s", job.error)
            else:
                response = job.result
                if response is not None:
                    checked = len(response.results)
                    updated = response.updated
                    failed = response.failed
                # The user hit Stop mid-run: partial by choice, not a failure.
                if job.state == "stopped":
                    status = "stopped"
                log.info(
                    "Automatic check %s: %s checked, %s updated, %s failed",
                    status,
                    checked,
                    updated,
                    failed,
                )
        except Exception as exc:  # noqa: BLE001
            status, failed = "error", 1
            log.exception("Automatic library check failed: %s", exc)
        finally:
            self._running = False
            self.store.record_run(
                AutoUpdateRun(
                    started_at=started,
                    finished_at=utc_now(),
                    trigger=trigger,
                    status=status,
                    checked=checked,
                    updated=updated,
                    failed=failed,
                )
            )
            self.next_run_at = self._compute_next_run(self.store.load())


def _now() -> datetime:
    return datetime.fromisoformat(utc_now())


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


#: One scheduler per process, started from the FastAPI lifespan.
scheduler = UpdateScheduler()
