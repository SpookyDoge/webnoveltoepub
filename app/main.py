"""FastAPI application: the API plus serving the frontend."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import quote, urlparse

from fastapi import FastAPI, HTTPException, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, i18n
from .config import WEB_DIR, get_settings
from .fetcher import FetchError, PlaywrightUnavailableError
from .library import Library
from .models import (
    ConvertRequest,
    LibraryEntry,
    ParserInfo,
    PreviewRequest,
    PreviewResponse,
)
from .parsers import ParserError, all_parsers, discover
from .progress import registry
from .service import (
    ConversionResult,
    UnsupportedSiteError,
    convert,
    preview,
    update_all,
    update_entry,
)

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
    yield


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
    job = registry.run("preview", lambda emit: preview(url, settings, emit))
    return {"job_id": job.id}


@app.post("/api/jobs/convert")
async def start_convert_job(request: ConvertRequest) -> dict[str, str]:
    """Same work as /api/convert; the EPUB is collected from /result after."""
    request.url = _validate_url(request.url)
    job = registry.run("convert", lambda emit: convert(request, settings, emit))
    return {"job_id": job.id}


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


@app.post("/api/library/update-all")
async def start_update_all_job() -> dict[str, str]:
    job = registry.run("library_update_all", lambda emit: update_all(settings, emit))
    return {"job_id": job.id}


@app.post("/api/library/{entry_id}/update")
async def start_update_job(entry_id: str) -> dict[str, str]:
    if await asyncio.to_thread(Library(settings).get, entry_id) is None:
        raise HTTPException(status_code=404, detail="unknown_entry")
    job = registry.run(
        "library_update", lambda emit: update_entry(entry_id, settings, emit)
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


# Mount the frontend last - the /api/* routes are already registered and win.
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
else:  # pragma: no cover
    log.warning("Frontend directory does not exist: %s", WEB_DIR)
