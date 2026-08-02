from __future__ import annotations

import io
import zipfile

import pytest

from app.epub_builder import build_epub, slugify
from app.models import ChapterContent, CoverImage, NovelMetadata

METADATA = NovelMetadata(
    title="Zażółć Gęślą Jaźń",
    author="Autor Testowy",
    description="Opis.",
    language="pl",
    source_url="https://www.royalroad.com/fiction/42/x",
    tags=["Fantasy"],
)

CHAPTERS = [
    ChapterContent(title="Rozdział 1", html="<p>Treść pierwsza.</p>"),
    ChapterContent(title="Rozdział 2", html="<p>Treść druga.</p>"),
]


def test_build_epub_produces_valid_zip_with_expected_entries():
    payload = build_epub(METADATA, CHAPTERS)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        assert "mimetype" in names
        assert "META-INF/container.xml" in names
        assert any(name.endswith("chapter_0001.xhtml") for name in names)
        assert any(name.endswith("chapter_0002.xhtml") for name in names)
        assert archive.testzip() is None


def test_metadata_lands_in_opf():
    payload = build_epub(METADATA, CHAPTERS)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        opf_name = next(name for name in archive.namelist() if name.endswith(".opf"))
        opf = archive.read(opf_name).decode("utf-8")
    assert "Zażółć Gęślą Jaźń" in opf
    assert "Autor Testowy" in opf
    assert ">pl<" in opf


def test_identifier_is_deterministic_per_source_url():
    first = build_epub(METADATA, CHAPTERS)
    second = build_epub(METADATA, CHAPTERS)

    def identifier(payload: bytes) -> str:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            opf_name = next(n for n in archive.namelist() if n.endswith(".opf"))
            opf = archive.read(opf_name).decode("utf-8")
        start = opf.index("urn:uuid:")
        return opf[start : start + 45]

    assert identifier(first) == identifier(second)


def test_cover_is_embedded():
    cover = CoverImage(data=b"\x89PNG\r\n\x1a\n", media_type="image/png", file_name="cover.png")
    payload = build_epub(METADATA, CHAPTERS, cover)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert any("cover.png" in name for name in archive.namelist())


def test_empty_chapter_list_is_rejected():
    with pytest.raises(ValueError):
        build_epub(METADATA, [])


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Zażółć Gęślą Jaźń", "zazolc-gesla-jazn"),
        ("A  B!!! C", "a-b-c"),
        ("日本語", "novel"),
        ("", "novel"),
    ],
)
def test_slugify(value, expected):
    assert slugify(value) == expected
