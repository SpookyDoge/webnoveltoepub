"""Aplikacja FastAPI: API + serwowanie frontu."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import quote, urlparse

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles

from . import __version__, i18n
from .config import WEB_DIR, get_settings
from .fetcher import FetchError
from .models import ConvertRequest, ParserInfo, PreviewRequest, PreviewResponse
from .parsers import ParserError, all_parsers, discover
from .service import UnsupportedSiteError, convert, preview

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
        "Zaladowano %s parserow: %s",
        len(all_parsers()),
        ", ".join(p.name for p in all_parsers()),
    )
    yield


app = FastAPI(
    title="webnoveltoepub",
    version=__version__,
    description="Self-hosted konwerter web noveli do EPUB",
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
    except FetchError as exc:
        raise HTTPException(status_code=502, detail=f"fetch_error: {exc}") from exc

    if result.warnings:
        log.warning(
            "Konwersja %s zakonczona z %s ostrzezeniami",
            request.url,
            len(result.warnings),
        )

    disposition = (
        f'attachment; filename="{result.file_name}"; '
        f"filename*=UTF-8''{quote(result.file_name)}"
    )
    return Response(
        content=result.content,
        media_type="application/epub+zip",
        headers={
            "Content-Disposition": disposition,
            "X-Chapter-Count": str(result.chapter_count),
            "X-Warning-Count": str(len(result.warnings)),
        },
    )


# Front montujemy na koncu - trasy /api/* zostaly juz zarejestrowane i wygrywaja.
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
else:  # pragma: no cover
    log.warning("Katalog frontu nie istnieje: %s", WEB_DIR)
