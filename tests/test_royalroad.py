"""Testy parsera RoyalRoad na syntetycznym HTML-u odwzorowujacym strukture strony."""

from __future__ import annotations

import pytest

from app.models import ChapterRef
from app.parsers.base import ParserError
from app.parsers.royalroad import RoyalRoadParser

FICTION_URL = "https://www.royalroad.com/fiction/42/testowa-powiesc"

FICTION_PAGE = """
<html><head>
  <meta property="og:title" content="Testowa Powiesc">
  <meta property="og:image" content="https://www.royalroad.com/covers/42.jpg">
</head><body>
  <div class="fic-title">
    <h1 class="font-white">Testowa Powiesc</h1>
    <h4 class="font-white"><a href="/profile/7">Autor Testowy</a></h4>
  </div>
  <div class="cover-art-container"><img src="/covers/42.jpg"></div>
  <div class="description"><p>Opis powiesci w dwoch zdaniach.</p></div>
  <span class="tags"><a class="fiction-tag" href="#">Fantasy</a>
    <a class="fiction-tag" href="#">LitRPG</a></span>
  <table id="chapters"><tbody>
    <tr><td><a href="/fiction/42/testowa-powiesc/chapter/1/rozdzial-1">Rozdzial 1</a></td></tr>
    <tr><td><a href="/fiction/42/testowa-powiesc/chapter/2/rozdzial-2">Rozdzial 2</a></td></tr>
  </tbody></table>
  <script>
    window.chapters = [
      {"id": 1, "title": "Rozdzial 1", "order": 0,
       "url": "/fiction/42/testowa-powiesc/chapter/1/rozdzial-1"},
      {"id": 2, "title": "Rozdzial 2", "order": 1,
       "url": "/fiction/42/testowa-powiesc/chapter/2/rozdzial-2"}
    ];
  </script>
</body></html>
"""

CHAPTER_PAGE = """
<html><head>
  <style>.hidden-trap { display: none; }</style>
</head><body>
  <h1 class="font-white">Rozdzial 1</h1>
  <div class="chapter-content">
    <p>Pierwszy akapit tresci.</p>
    <p class="hidden-trap">Ten akapit jest pulapka anty-scrapingowa.</p>
    <p>Drugi akapit tresci.</p>
  </div>
  <div class="author-note-portlet"><p>Notka autora poza trescia.</p></div>
</body></html>
"""

CHAPTER_URL = "https://www.royalroad.com/fiction/42/testowa-powiesc/chapter/1/rozdzial-1"


@pytest.fixture
def parser(fake_fetcher):
    fetcher = fake_fetcher(
        pages={FICTION_URL: FICTION_PAGE, CHAPTER_URL: CHAPTER_PAGE},
        binaries={"https://www.royalroad.com/covers/42.jpg": (b"\xff\xd8\xff", "image/jpeg")},
    )
    return RoyalRoadParser(fetcher)


def test_get_metadata(parser):
    metadata = parser.get_metadata(FICTION_URL)
    assert metadata.title == "Testowa Powiesc"
    assert metadata.author == "Autor Testowy"
    assert "Opis powiesci" in metadata.description
    assert metadata.cover_url == "https://www.royalroad.com/covers/42.jpg"
    assert metadata.tags == ["Fantasy", "LitRPG"]
    assert metadata.publisher == "RoyalRoad"


def test_chapter_list_is_read_from_embedded_json(parser):
    chapters = parser.get_chapter_list(FICTION_URL)
    assert [c.index for c in chapters] == [1, 2]
    assert chapters[0].title == "Rozdzial 1"
    assert chapters[0].url == CHAPTER_URL


def test_chapter_list_falls_back_to_table(fake_fetcher):
    page_without_script = FICTION_PAGE[: FICTION_PAGE.index("<script>")] + "</body></html>"
    parser = RoyalRoadParser(fake_fetcher({FICTION_URL: page_without_script}))
    chapters = parser.get_chapter_list(FICTION_URL)
    assert len(chapters) == 2
    assert chapters[1].url.endswith("/chapter/2/rozdzial-2")


def test_chapter_content_drops_css_hidden_trap(parser):
    chapter = ChapterRef(index=1, title="Rozdzial 1", url=CHAPTER_URL)
    content = parser.get_chapter_content(chapter)
    assert content.title == "Rozdzial 1"
    assert "Pierwszy akapit" in content.html
    assert "Drugi akapit" in content.html
    assert "pulapka" not in content.html
    # Notka autora jest poza div.chapter-content, wiec nie trafia do EPUB-a.
    assert "Notka autora" not in content.html


def test_missing_content_raises_parser_error(fake_fetcher):
    parser = RoyalRoadParser(fake_fetcher({CHAPTER_URL: "<html><body>404</body></html>"}))
    with pytest.raises(ParserError):
        parser.get_chapter_content(ChapterRef(index=1, title="x", url=CHAPTER_URL))


def test_chapter_url_is_normalized_to_fiction_url(parser):
    assert parser.normalize_url(CHAPTER_URL) == FICTION_URL
    assert parser.normalize_url(FICTION_URL + "/") == FICTION_URL
    assert parser.normalize_url(FICTION_URL + "?utm=1#x") == FICTION_URL


def test_get_cover_image(parser):
    metadata = parser.get_metadata(FICTION_URL)
    cover = parser.get_cover_image(metadata)
    assert cover is not None
    assert cover.media_type == "image/jpeg"
    assert cover.file_name == "cover.jpg"
