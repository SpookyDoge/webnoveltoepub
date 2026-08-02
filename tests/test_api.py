from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import service
from app.main import app
from app.models import ChapterContent, ChapterRef, NovelMetadata, PreviewResponse


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_parsers_endpoint_lists_royalroad(client):
    payload = client.get("/api/parsers").json()
    assert any(parser["name"] == "royalroad" for parser in payload)


def test_languages_endpoint_exposes_pl_and_en(client):
    codes = {lang["code"] for lang in client.get("/api/languages").json()}
    assert {"en", "pl"} <= codes


def test_language_file_has_no_missing_keys(client):
    en = client.get("/api/languages/en").json()
    pl = client.get("/api/languages/pl").json()
    assert set(en) == set(pl), "The translation files have drifted apart on keys"


def test_unknown_language_is_404(client):
    assert client.get("/api/languages/xx").status_code == 404


def test_language_endpoint_rejects_path_traversal(client):
    assert client.get("/api/languages/..%2f..%2fconfig").status_code in (400, 404)


def test_preview_rejects_non_http_url(client):
    response = client.post("/api/preview", json={"url": "file:///etc/passwd"})
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_url"


def test_preview_rejects_unsupported_site(client):
    response = client.post("/api/preview", json={"url": "https://example.com/novel"})
    assert response.status_code == 422
    assert response.json()["detail"] == "unsupported_site"


def test_convert_returns_epub(client, monkeypatch):
    """A full /api/convert run with the parser layer stubbed out."""
    metadata = NovelMetadata(
        title="Fejkowa Powiesc",
        author="Autor",
        language="pl",
        source_url="https://www.royalroad.com/fiction/1/fejk",
    )
    chapters = [
        ChapterRef(index=1, title="Rozdzial 1", url="https://www.royalroad.com/c/1"),
        ChapterRef(index=2, title="Rozdzial 2", url="https://www.royalroad.com/c/2"),
    ]

    class StubParser:
        name = "royalroad"
        requires_playwright = False

        def get_metadata(self, url):
            return metadata.model_copy()

        def get_chapter_list(self, url):
            return chapters

        def get_chapter_content(self, chapter):
            return ChapterContent(title=chapter.title, html=f"<p>Tresc {chapter.index}</p>")

        def get_cover_image(self, metadata):
            return None

    class StubFetcher:
        def close(self):
            pass

    monkeypatch.setattr(service, "_make_parser", lambda url, s: (StubParser(), StubFetcher()))

    response = client.post(
        "/api/convert",
        json={"url": "https://www.royalroad.com/fiction/1/fejk", "selected": [1, 2]},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/epub+zip"
    assert "fejkowa-powiesc.epub" in response.headers["content-disposition"]
    assert response.headers["x-chapter-count"] == "2"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.testzip() is None


def test_preview_response_shape():
    """PreviewResponse must carry the cap - the frontend bases its default selection on it."""
    response = PreviewResponse(
        parser="royalroad",
        metadata=NovelMetadata(title="x", source_url="https://x.test"),
        chapters=[],
        max_chapters=300,
    )
    assert response.model_dump()["max_chapters"] == 300
