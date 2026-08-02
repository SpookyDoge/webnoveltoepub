"""Starting background jobs, in the one place both callers can reach.

`main.py` (the buttons in the UI) and `scheduler.py` (the timer) must produce
*the same* job - same registry, same id, same SSE stream, same pause/stop
endpoints. Neither can own that code: main imports the scheduler for its
lifespan, so a scheduler that imported main back would close an import cycle.
Hence this module, which imports neither.
"""

from __future__ import annotations

from collections.abc import Callable

from .config import Settings
from .fetcher import FetchError, PlaywrightUnavailableError
from .parsers import ParserError
from .progress import Emitter, Job, JobControl, JobError, registry
from .service import StoppedBeforeStartError, UnsupportedSiteError, update_all

#: Job kinds. `library_update_all` covers the manual button and the scheduler
#: alike - they differ by `Job.trigger`, not by kind, because everything that
#: reads a job (the UI, the controls, the result endpoint) treats them as one.
KIND_UPDATE_ALL = "library_update_all"


def error_detail(exc: Exception) -> str:
    """Turns an exception into the detail code the frontend translates.

    The single source of truth for both routes: the synchronous ones raise it
    as an HTTP detail, the job ones hand it to the client over SSE. Order
    matters - PlaywrightUnavailableError is a FetchError.
    """
    if isinstance(exc, UnsupportedSiteError):
        return "unsupported_site"
    if isinstance(exc, StoppedBeforeStartError):
        return "stopped_empty"
    if isinstance(exc, ParserError):
        return f"parser_error: {exc}"
    if isinstance(exc, PlaywrightUnavailableError):
        return f"playwright_unavailable: {exc}"
    if isinstance(exc, FetchError):
        return f"fetch_error: {exc}"
    return f"unknown_error: {type(exc).__name__}: {exc}"


def job_worker(work: Callable[[Emitter, JobControl], object]) -> Callable[..., object]:
    """Wraps a job body so failures arrive as codes, not raw exception text."""

    def runner(emit: Emitter, control: JobControl) -> object:
        try:
            return work(emit, control)
        except Exception as exc:
            raise JobError(error_detail(exc)) from exc

    return runner


def start_update_all(settings: Settings, trigger: str = "manual") -> Job:
    """Starts a whole-library update - the one path for button and timer alike.

    `trigger` only labels where it came from, so the UI can say why something
    began without the user touching anything. It changes nothing about how the
    job runs, is controlled or reports progress.
    """
    return registry.run(
        KIND_UPDATE_ALL,
        job_worker(lambda emit, control: update_all(settings, emit, control)),
        trigger=trigger,
    )
