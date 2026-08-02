"""One progress mechanism shared by every long-running operation.

Why jobs + Server-Sent Events rather than streaming the work itself: the
service layer is synchronous and runs in a worker thread (`asyncio.to_thread`),
so it cannot `yield` into an HTTP response. A job registry decouples the two -
the worker appends events, and an SSE endpoint replays and follows them.

SSE (not polling) because the browser side is a three-line `EventSource`, the
traffic is one-directional anyway, and there is no polling interval to trade
off latency against load.

Events live in one append-only list per job rather than a queue: a client that
connects late (or reconnects) replays from index 0 and then follows along, and
there is no way for the same event to be delivered twice.

Adding progress to a new operation:
    1. take `emit: Emitter | None = None` in the service function,
    2. call `emit("something_happened", ...)` at the interesting points,
    3. start it from a route with `registry.run(kind, worker)`.
Queueing, the SSE stream and cleanup are already handled here.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

#: What a service function is handed to report progress with.
Emitter = Callable[..., None]

#: Jobs are dropped this long after finishing. Long enough for a browser that
#: reconnects or downloads late, short enough that memory does not creep.
JOB_TTL_SECONDS = 30 * 60

#: How long a stream waits before emitting a keep-alive comment. Without
#: traffic, proxies and browsers happily close an idle connection.
HEARTBEAT_SECONDS = 15.0


@dataclass
class Job:
    """A single background operation and its event history."""

    id: str
    kind: str
    created_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    status: str = "running"
    #: Whatever the worker returned; for a conversion this holds the EPUB.
    result: Any = None
    error: str | None = None
    #: Append-only. Guarded by `_cond`, which also wakes up the streams.
    history: list[dict] = field(default_factory=list)
    _cond: threading.Condition = field(default_factory=threading.Condition)

    def emit(self, event_type: str, **data: Any) -> None:
        with self._cond:
            self.history.append({"type": event_type, **data})
            self._cond.notify_all()

    def finish(self, result: Any = None) -> None:
        self.result = result
        with self._cond:
            self.status = "done"
            self.finished_at = time.monotonic()
            self.history.append({"type": "done"})
            self._cond.notify_all()

    def fail(self, detail: str) -> None:
        self.error = detail
        with self._cond:
            self.status = "error"
            self.finished_at = time.monotonic()
            self.history.append({"type": "error", "detail": detail})
            self._cond.notify_all()

    def events_from(self, index: int, timeout: float) -> list[dict]:
        """Events after `index`, waiting up to `timeout` for the first one."""
        with self._cond:
            if index >= len(self.history) and self.status == "running":
                self._cond.wait(timeout)
            return self.history[index:]

    @property
    def finished(self) -> bool:
        return self.status != "running"


class JobRegistry:
    """In-memory job store.

    In-memory is deliberate: the app is single-process and single-user, and a
    job holds an EPUB that only makes sense for the browser that asked for it.
    Nothing here is worth surviving a restart.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, kind: str) -> Job:
        self._evict_expired()
        job = Job(id=uuid.uuid4().hex, kind=kind)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def run(self, kind: str, worker: Callable[[Emitter], Any]) -> Job:
        """Starts `worker` on a thread, handing it an emitter. Returns at once."""
        job = self.create(kind)

        def runner() -> None:
            try:
                job.finish(worker(job.emit))
            except Exception as exc:  # noqa: BLE001 - surfaced to the client
                log.exception("Job %s (%s) failed", job.id, kind)
                job.fail(f"{type(exc).__name__}: {exc}")

        threading.Thread(target=runner, name=f"job-{kind}", daemon=True).start()
        return job

    def stream(self, job: Job) -> Iterator[str]:
        """Server-Sent Events for a job: full history first, then live."""
        index = 0
        while True:
            pending = job.events_from(index, HEARTBEAT_SECONDS)
            if not pending:
                if job.finished:
                    return
                yield ": keep-alive\n\n"
                continue

            for event in pending:
                index += 1
                yield _format_sse(event)
                if event["type"] in ("done", "error"):
                    return

    def _evict_expired(self) -> None:
        now = time.monotonic()
        with self._lock:
            stale = [
                job_id
                for job_id, job in self._jobs.items()
                if job.finished_at is not None and now - job.finished_at > JOB_TTL_SECONDS
            ]
            for job_id in stale:
                del self._jobs[job_id]


def _format_sse(payload: dict) -> str:
    return f"event: {payload['type']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


#: Single shared registry - the app is one process.
registry = JobRegistry()
