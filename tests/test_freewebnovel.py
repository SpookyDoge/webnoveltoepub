"""Testy parsera FreeWebNovel na syntetycznym HTML-u odwzorowujacym strukture strony."""

from __future__ import annotations

import pytest

from app.models import ChapterRef
from app.parsers.base import ParserError
from app.parsers.freewebnovel import FreeWebNovelParser

NOVEL_URL = "https://freewebnovel.com/novel/testowa-powiesc"

META_BLOCK = """
  <meta property="og:title" content="Testowa Powiesc"/>
  <meta property="og:image" content="https://freewebnovel.com/files/article/image/0/1/1s.jpg"/>
  <meta property="og:novel:novel_name" content="Testowa Powiesc"/>
  <meta property="og:novel:author" content="Autor Testowy"/>
  <meta property="og:novel:genre" content="Fantasy, Action, Adventure"/>
  <meta property="og:novel:status" content="OnGoing"/>
  <meta property="og:novel:index_url" content="https://freewebnovel.com/novel/testowa-powiesc"/>
"""


def _chapter_link(number: int) -> str:
    return (
        f'<li><span class="glyphicon"></span>'
        f'<a class="con" href="/novel/testowa-powiesc/chapter-{number}" '
        f'title="Chapter {number} Tytul">Chapter {number} Tytul</a></li>'
    )


def _list_page(numbers: range, page_count: int) -> str:
    options = "".join(
        f'<option value="/novel/testowa-powiesc">C.{i}</option>' for i in range(page_count)
    )
    return f"""
    <html><head>{META_BLOCK}</head><body>
      <div class="m-book1">
        <div class="m-imgtxt">
          <img src="/files/article/image/0/1/1s.jpg" alt="Testowa Powiesc"/>
        </div>
        <h1 class="tit">Testowa Powiesc</h1>
        <div class="txt">
          <div class="item"><div class="right">
            <a class="a1" href="/author/Autor">Autor Testowy</a>
          </div></div>
        </div>
      </div>
      <div class="m-desc"><div class="txt"><div class="inner">
        <p>Opis powiesci w dwoch zdaniach.</p>
      </div></div></div>
      <div class="m-newest1"><ul class="ul-list5">
        <li><a class="con" href="/novel/testowa-powiesc/chapter-99"
               title="Najnowszy">Najnowszy</a></li>
      </ul></div>
      <div class="m-newest2">
        <ul class="ul-list5" id="idData">{"".join(_chapter_link(n) for n in numbers)}</ul>
      </div>
      <div class="page" id="barcon">
        <select id="indexselect" onchange="self.location.href=options[selectedIndex].value">
          {options}
        </select>
      </div>
    </body></html>
    """


CHAPTER_URL = "https://freewebnovel.com/novel/testowa-powiesc/chapter-1"

#: Odwzorowuje prawdziwa strukture: #article jest ZAGNIEZDZONY w div.m-read
#: div.txt, a we wrapperze (poza trescia) siedza dodatkowe smieci reklamowe -
#: w tym zakomentowany kod, ktory `decode()` wypisuje doslownie.
CHAPTER_PAGE = """
<html><head>
  <meta property="og:novel:chapter_name" content="Chapter 1 Prawdziwy Tytul"/>
  <meta property="og:novel:index_url" content="https://freewebnovel.com/novel/testowa-powiesc"/>
  <style>.trap { display: none; }</style>
</head><body>
  <div class="m-read">
    <h1 class="tit">Testowa Powiesc</h1>
    <span class="chapter">Chapter 1 Prawdziwy Tytul</span>
    <div class="txt">
      <!--bg-->
      <!--<script async src="https://platform.example/ad.js"></script>-->
      <!--bg end-->
      <div class="reader-ad-skip">Reklama poza trescia</div>
      <div id="article">
        <div class="reader-ad-skip skiptranslate" style="text-align:center" translate="no">
          <div id="bg-ssp-6327">Advertisement<script>var adx_id = 1;</script></div>
        </div>
        <p>Pierwszy akapit tresci.</p>
        <p class="trap">Akapit ukryty regula CSS.</p>
        <p>Drugi akapit tresci.</p>
        <div id="pf-878-1"><script>window.pubfuturetag = [];</script></div>
      </div>
    </div>
  </div>
  <a id="next_url" href="/novel/testowa-powiesc/chapter-2">Next</a>
</body></html>
"""


@pytest.fixture
def parser(fake_fetcher):
    fetcher = fake_fetcher(
        pages={
            NOVEL_URL: _list_page(range(1, 41), page_count=1),
            CHAPTER_URL: CHAPTER_PAGE,
        },
        binaries={
            "https://freewebnovel.com/files/article/image/0/1/1s.jpg": (
                b"\xff\xd8\xff",
                "image/jpeg",
            )
        },
    )
    return FreeWebNovelParser(fetcher)


@pytest.fixture
def paginated_parser(fake_fetcher):
    """Powiesc na 3 stronach listy: 40 + 40 + 5 rozdzialow."""
    fetcher = fake_fetcher(
        pages={
            NOVEL_URL: _list_page(range(1, 41), page_count=3),
            f"{NOVEL_URL}?page=2": _list_page(range(41, 81), page_count=3),
            f"{NOVEL_URL}?page=3": _list_page(range(81, 86), page_count=3),
        }
    )
    return FreeWebNovelParser(fetcher)


# -- Metadane ---------------------------------------------------------------


def test_get_metadata_prefers_og_novel_meta(parser):
    metadata = parser.get_metadata(NOVEL_URL)
    assert metadata.title == "Testowa Powiesc"
    assert metadata.author == "Autor Testowy"
    assert "Opis powiesci" in metadata.description
    assert metadata.cover_url == "https://freewebnovel.com/files/article/image/0/1/1s.jpg"
    assert metadata.tags == ["Fantasy", "Action", "Adventure"]
    assert metadata.publisher == "FreeWebNovel"
    assert metadata.language == "en"


def test_metadata_falls_back_to_html_without_meta(fake_fetcher):
    page = _list_page(range(1, 3), page_count=1).replace(META_BLOCK, "")
    parser = FreeWebNovelParser(fake_fetcher({NOVEL_URL: page}))
    metadata = parser.get_metadata(NOVEL_URL)
    assert metadata.title == "Testowa Powiesc"
    assert metadata.author == "Autor Testowy"
    assert metadata.cover_url.endswith("/files/article/image/0/1/1s.jpg")
    assert metadata.tags == []


def test_get_cover_image(parser):
    cover = parser.get_cover_image(parser.get_metadata(NOVEL_URL))
    assert cover is not None
    assert cover.media_type == "image/jpeg"


# -- Lista rozdzialow -------------------------------------------------------


def test_single_page_chapter_list(parser):
    chapters = parser.get_chapter_list(NOVEL_URL)
    assert len(chapters) == 40
    assert chapters[0].index == 1
    assert chapters[0].title == "Chapter 1 Tytul"
    assert chapters[0].url == CHAPTER_URL


def test_latest_chapters_block_is_not_mixed_into_the_list(parser):
    """Blok 'najnowsze rozdzialy' tez uzywa ul.ul-list5 - nie moze zaburzyc kolejnosci."""
    chapters = parser.get_chapter_list(NOVEL_URL)
    assert [c.index for c in chapters] == list(range(1, 41))
    assert all("chapter-99" not in c.url for c in chapters[:40])


def test_pagination_walks_every_page(paginated_parser):
    chapters = paginated_parser.get_chapter_list(NOVEL_URL)
    assert len(chapters) == 85
    assert [c.index for c in chapters[:3]] == [1, 2, 3]
    assert chapters[-1].index == 85
    assert chapters[-1].url.endswith("/chapter-85")
    # Numeracja musi byc ciagla przez granice stron.
    assert [c.index for c in chapters] == list(range(1, 86))


def test_pagination_requests_expected_urls(paginated_parser):
    paginated_parser.get_chapter_list(NOVEL_URL)
    assert f"{NOVEL_URL}?page=2" in paginated_parser.fetcher.requested
    assert f"{NOVEL_URL}?page=3" in paginated_parser.fetcher.requested


def test_pagination_stops_when_a_page_repeats(fake_fetcher):
    """Serwis oddaje strone 1 zamiast 404 - nie wolno nam wpasc w petle ani duplikowac."""
    first = _list_page(range(1, 41), page_count=5)
    parser = FreeWebNovelParser(
        fake_fetcher({NOVEL_URL: first, f"{NOVEL_URL}?page=2": first})
    )
    chapters = parser.get_chapter_list(NOVEL_URL)
    assert len(chapters) == 40
    assert f"{NOVEL_URL}?page=3" not in parser.fetcher.requested


def test_missing_chapter_list_raises_parser_error(fake_fetcher):
    parser = FreeWebNovelParser(fake_fetcher({NOVEL_URL: "<html><body>404</body></html>"}))
    with pytest.raises(ParserError):
        parser.get_chapter_list(NOVEL_URL)


# -- Tresc rozdzialu --------------------------------------------------------


def test_chapter_content_strips_ads_and_css_traps(parser):
    content = parser.get_chapter_content(ChapterRef(index=1, title="x", url=CHAPTER_URL))
    assert content.title == "Chapter 1 Prawdziwy Tytul"
    assert "Pierwszy akapit" in content.html
    assert "Drugi akapit" in content.html
    assert "ukryty" not in content.html
    assert "Advertisement" not in content.html
    assert "adx_id" not in content.html
    assert "pubfuturetag" not in content.html
    assert "<script" not in content.html


def test_content_is_article_not_the_surrounding_wrapper(parser):
    """#article jest zagniezdzony w div.txt - wrapper niesie smieci spoza tresci."""
    content = parser.get_chapter_content(ChapterRef(index=1, title="x", url=CHAPTER_URL))
    assert "Reklama poza trescia" not in content.html
    assert "platform.example/ad.js" not in content.html


def test_chapter_title_falls_back_to_span(fake_fetcher):
    page = CHAPTER_PAGE.replace(
        '<meta property="og:novel:chapter_name" content="Chapter 1 Prawdziwy Tytul"/>', ""
    )
    parser = FreeWebNovelParser(fake_fetcher({CHAPTER_URL: page}))
    content = parser.get_chapter_content(ChapterRef(index=1, title="zapasowy", url=CHAPTER_URL))
    assert content.title == "Chapter 1 Prawdziwy Tytul"


def test_missing_content_raises_parser_error(fake_fetcher):
    parser = FreeWebNovelParser(fake_fetcher({CHAPTER_URL: "<html><body>404</body></html>"}))
    with pytest.raises(ParserError):
        parser.get_chapter_content(ChapterRef(index=1, title="x", url=CHAPTER_URL))


def test_content_that_is_only_ads_raises_parser_error(fake_fetcher):
    page = """<html><body><div id="article">
      <div class="reader-ad-skip">Advertisement</div>
    </div></body></html>"""
    parser = FreeWebNovelParser(fake_fetcher({CHAPTER_URL: page}))
    with pytest.raises(ParserError):
        parser.get_chapter_content(ChapterRef(index=1, title="x", url=CHAPTER_URL))


# -- URL --------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        NOVEL_URL,
        NOVEL_URL + "/",
        NOVEL_URL + "?page=7",
        NOVEL_URL + "/chapter-123",
        NOVEL_URL + "/chapter-123?x=1#anchor",
    ],
)
def test_normalize_url(parser, raw):
    assert parser.normalize_url(raw) == NOVEL_URL
