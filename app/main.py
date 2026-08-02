"""FastAPI application: the API plus serving the frontend."""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, i18n
from .config import WEB_DIR, get_settings
from .epub_builder import slugify
from .fetcher import FetchError, PlaywrightUnavailableError
from .jobs import job_worker, start_update_all
from .library import Library, SettingsStore
from .models import (
    AppSettings,
    ConvertRequest,
    LibraryEntry,
    LibraryImportResponse,
    ParserInfo,
    PreviewRequest,
    PreviewResponse,
    SettingsResponse,
)
from .parsers import ParserError, all_parsers, discover
from .progress import registry
from .scheduler import scheduler
from .service import (
    ConversionResult,
    UnsupportedSiteError,
    convert,
    import_webtoepub_library,
    preview,
    update_entry,
)
from .webtoepub import WebToEpubImportError

log = logging.getLogger(__name__)
settings = get_settings()
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    discover()
    log.info(
        "Loaded %s parsers: %s",
        len(all_parsers()),
        ", ".join(p.name for p in all_parsers()),
    )
    scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()


app = FastAPI(
    title="webnoveltoepub",
    version=__version__,
    description="Self-hosted web novel to EPUB converter",
    lifespan=lifespan,
)


def _validate_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="invalid_url")
    return url


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/api/parsers", response_model=list[ParserInfo])
async def list_parsers() -> list[ParserInfo]:
    return [
        ParserInfo(
            name=parser.name,
            label=parser.label,
            domains=list(parser.domains),
            requires_playwright=parser.requires_playwright,
        )
        for parser in all_parsers()
    ]


@app.get("/api/languages", response_model=list[i18n.LanguageInfo])
async def list_languages() -> list[i18n.LanguageInfo]:
    return i18n.available_languages()


@app.get("/api/languages/{code}")
async def get_language(code: str) -> dict:
    data = i18n.load_language(code)
    if data is None:
        raise HTTPException(status_code=404, detail="unknown_language")
    return data


@app.post("/api/preview", response_model=PreviewResponse)
async def preview_novel(request: PreviewRequest) -> PreviewResponse:
    url = _validate_url(request.url)
    try:
        return await asyncio.to_thread(preview, url, settings)
    except UnsupportedSiteError as exc:
        raise HTTPException(status_code=422, detail="unsupported_site") from exc
    except ParserError as exc:
        raise HTTPException(status_code=422, detail=f"parser_error: {exc}") from exc
    # Must precede FetchError - it is a subclass, and this one is a setup
    # problem (422), not a network failure (502).
    except PlaywrightUnavailableError as exc:
        raise HTTPException(
            status_code=422, detail=f"playwright_unavailable: {exc}"
        ) from exc
    except FetchError as exc:
        raise HTTPException(status_code=502, detail=f"fetch_error: {exc}") from exc


@app.post(
    "/api/convert",
    responses={200: {"content": {"application/epub+zip": {}}}},
    response_class=Response,
)
async def convert_novel(request: ConvertRequest) -> Response:
    request.url = _validate_url(request.url)
    try:
        result = await asyncio.to_thread(convert, request, settings)
    except UnsupportedSiteError as exc:
        raise HTTPException(status_code=422, detail="unsupported_site") from exc
    except ParserError as exc:
        raise HTTPException(status_code=422, detail=f"parser_error: {exc}") from exc
    except PlaywrightUnavailableError as exc:
        raise HTTPException(
            status_code=422, detail=f"playwright_unavailable: {exc}"
        ) from exc
    except FetchError as exc:
        raise HTTPException(status_code=502, detail=f"fetch_error: {exc}") from exc

    return _epub_response(result)


def _epub_response(result: ConversionResult) -> Response:
    """The EPUB download, shared by the direct and the job-based route."""
    if result.warnings:
        log.warning(
            "Conversion finished with %s warnings: %s",
            len(result.warnings),
            result.metadata.source_url,
        )

    disposition = (
        f'attachment; filename="{result.file_name}"; '
        f"filename*=UTF-8''{quote(result.file_name)}"
    )
    headers = {
        "Content-Disposition": disposition,
        "X-Chapter-Count": str(result.chapter_count),
        "X-Warning-Count": str(len(result.warnings)),
    }
    if result.saved_path is not None:
        headers["X-Saved-Path"] = str(result.saved_path)

    return Response(
        content=result.content,
        media_type="application/epub+zip",
        headers=headers,
    )


# --------------------------------------------------------------------------
# Jobs + progress (SSE)
# --------------------------------------------------------------------------


@app.post("/api/jobs/preview")
async def start_preview_job(request: PreviewRequest) -> dict[str, str]:
    """Same work as /api/preview, but reporting chapters as they are found."""
    url = _validate_url(request.url)
    job = registry.run("preview", job_worker(lambda emit, control: preview(url, settings, emit)))
    return {"job_id": job.id}


@app.post("/api/jobs/convert")
async def start_convert_job(request: ConvertRequest) -> dict[str, str]:
    """Same work as /api/convert; the EPUB is collected from /result after."""
    request.url = _validate_url(request.url)
    job = registry.run(
        "convert",
        job_worker(lambda emit, control: convert(request, settings, emit, control)),
    )
    return {"job_id": job.id}


@app.get("/api/jobs/active")
async def active_job() -> dict | None:
    """Whatever is running right now, or null.

    Declared before /api/jobs/{job_id}/... so "active" is never read as an id.
    This is how a browser finds a job it did not start - a scheduled update
    would otherwise run invisibly, which is the whole point of this endpoint.
    """
    job = registry.active()
    if job is None:
        return None
    return {"job_id": job.id, "kind": job.kind, "trigger": job.trigger, "state": job.state}


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown_job")

    async def stream() -> AsyncIterator[str]:
        # The generator blocks on a condition variable, so it has to be drained
        # off the event loop.
        events = registry.stream(job)
        while True:
            chunk = await asyncio.to_thread(lambda: next(events, None))
            if chunk is None:
                return
            yield chunk

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # nginx buffers responses by default, which would hold every event
            # back until the job finished - exactly what this exists to avoid.
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/jobs/{job_id}/result")
async def job_result(job_id: str) -> Response:
    """Collects a finished job's payload: the EPUB, or the preview as JSON."""
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown_job")
    if job.status == "running":
        raise HTTPException(status_code=409, detail="job_still_running")
    if job.status == "error":
        raise HTTPException(status_code=422, detail=job.error or "job_failed")

    result = job.result
    if isinstance(result, PreviewResponse):
        return JSONResponse(content=result.model_dump())
    if hasattr(result, "content") and hasattr(result, "file_name"):
        return _epub_response(result)
    return JSONResponse(content=jsonable_encoder(result))


# --------------------------------------------------------------------------
# Library
# --------------------------------------------------------------------------


@app.get("/api/library", response_model=list[LibraryEntry])
async def list_library() -> list[LibraryEntry]:
    entries = await asyncio.to_thread(Library(settings).load)
    # Most recently touched first - that is the one a user comes back to.
    return sorted(entries, key=lambda entry: entry.updated_at, reverse=True)


@app.post("/api/library/import", response_model=LibraryImportResponse)
async def import_library(request: Request) -> LibraryImportResponse:
    """Imports a library exported from the WebToEpub browser extension.

    Takes the file as a raw body rather than a multipart upload: it is one
    file, and multipart would mean adding python-multipart to every build
    including the .exe.
    """
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="empty_upload")
    try:
        return await asyncio.to_thread(import_webtoepub_library, data, settings)
    except WebToEpubImportError as exc:
        raise HTTPException(status_code=422, detail=f"import_error: {exc}") from exc


@app.get("/api/library/{entry_id}/download")
async def download_library_entry(entry_id: str) -> Response:
    """Serves the stored EPUB, so the library is useful without re-converting."""
    entry = await asyncio.to_thread(Library(settings).get, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown_entry")
    if not entry.file_path:
        # Converted with WNE_SAVE_TO_DISK off: the row is history, not a file.
        raise HTTPException(status_code=409, detail="no_epub_on_disk")

    path = Path(entry.file_path)
    if not path.is_file():
        # Moved or deleted behind our back - say which file is missing rather
        # than handing back an empty download.
        log.warning("Library entry %s points at a missing file: %s", entry.id, path)
        raise HTTPException(status_code=410, detail="epub_file_missing")

    file_name = path.name
    disposition = (
        f'attachment; filename="{slugify(entry.title)}.epub"; '
        f"filename*=UTF-8''{quote(file_name)}"
    )
    return FileResponse(
        path,
        media_type="application/epub+zip",
        headers={"Content-Disposition": disposition},
    )


@app.post("/api/library/update-all")
async def start_update_all_job() -> dict[str, str]:
    """The manual button. The scheduler starts the very same job."""
    return {"job_id": start_update_all(settings).id}


@app.post("/api/library/{entry_id}/update")
async def start_update_job(entry_id: str) -> dict[str, str]:
    if await asyncio.to_thread(Library(settings).get, entry_id) is None:
        raise HTTPException(status_code=404, detail="unknown_entry")
    job = registry.run(
        "library_update",
        job_worker(lambda emit, control: update_entry(entry_id, settings, emit, control)),
    )
    return {"job_id": job.id}


@app.delete("/api/library/{entry_id}", response_model=LibraryEntry)
async def delete_library_entry(entry_id: str, delete_file: bool = False) -> LibraryEntry:
    removed = await asyncio.to_thread(
        Library(settings).delete, entry_id, delete_file=delete_file
    )
    if removed is None:
        raise HTTPException(status_code=404, detail="unknown_entry")
    return removed


class RevalidatingStaticFiles(StaticFiles):
    """Serves the frontend with revalidation instead of heuristic caching.

    With no Cache-Control header a browser is free to invent its own freshness
    window and keep running an old app.js long after an update - which looks
    exactly like a broken UI. ETags are already sent, so "no-cache" costs one
    conditional request and gets a 304 whenever nothing actually changed.
    """

    def file_response(self, *args: object, **kwargs: object) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response


# --------------------------------------------------------------------------
# Job control (pause / resume / stop)
# --------------------------------------------------------------------------


def _job_or_404(job_id: str):
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown_job")
    return job


@app.post("/api/jobs/{job_id}/pause")
async def pause_job(job_id: str) -> dict[str, str]:
    job = _job_or_404(job_id)
    job.pause()
    return {"state": job.state}


@app.post("/api/jobs/{job_id}/resume")
async def resume_job(job_id: str) -> dict[str, str]:
    job = _job_or_404(job_id)
    job.resume()
    return {"state": job.state}


@app.post("/api/jobs/{job_id}/stop")
async def stop_job(job_id: str) -> dict[str, str]:
    """Wraps the job up after the chapter in flight; keeps what was downloaded."""
    job = _job_or_404(job_id)
    job.stop()
    return {"state": job.state}


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str) -> dict[str, str]:
    job = _job_or_404(job_id)
    return {"id": job.id, "kind": job.kind, "state": job.state}


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------


@app.get("/api/settings", response_model=SettingsResponse)
async def get_app_settings() -> SettingsResponse:
    return await asyncio.to_thread(_settings_response)


@app.put("/api/settings", response_model=SettingsResponse)
async def put_app_settings(update: AppSettings) -> SettingsResponse:
    await asyncio.to_thread(SettingsStore(settings).save, update)
    # The scheduler re-plans on the spot - no restart to pick this up.
    scheduler.nudge()
    return await asyncio.to_thread(_settings_response)


def _settings_response() -> SettingsResponse:
    store = SettingsStore(settings)
    stored = store.load()
    return SettingsResponse(
        **stored.model_dump(),
        last_run_at=store.last_run_at(),
        next_run_at=scheduler.next_run_at,
        # In the .exe the process only lives while its window is open, so an
        # interval measured in hours mostly will not fire.
        runs_in_background=not getattr(sys, "frozen", False),
        recent_runs=list(reversed(store.runs())),
    )


# Mount the frontend last - the /api/* routes are already registered and win.
if WEB_DIR.is_dir():
    app.mount("/", RevalidatingStaticFiles(directory=str(WEB_DIR), html=True), name="web")
else:  # pragma: no cover
    log.warning("Frontend directory does not exist: %s", WEB_DIR)
