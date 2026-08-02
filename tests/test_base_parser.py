"""Testy pomocnikow z BaseParser - wspolnych dla wszystkich parserow."""

from __future__ import annotations

from app.fetcher import make_soup
from app.parsers.base import BaseParser

NESTED = """
<html><body>
  <div class="wrapper">
    <p>smiec z wrappera</p>
    <div id="content"><p>wlasciwa tresc</p></div>
  </div>
</body></html>
"""


def test_select_first_respects_selector_order_not_document_order():
    """Regresja: select_one("#content, .wrapper") zwraca wrapper (jest wyzej
    w dokumencie), przez co tresc przychodzi razem ze smieciami wokol niej."""
    soup = make_soup(NESTED)

    # Tak zachowuje sie lista selektorow CSS - dlatego jej nie uzywamy.
    assert soup.select_one("#content, div.wrapper").get("class") == ["wrapper"]

    # select_first pyta selektorami po kolei.
    element = BaseParser.select_first(soup, "#content", "div.wrapper")
    assert element.get("id") == "content"
    assert "smiec" not in element.get_text()


def test_select_first_falls_back_to_later_selectors():
    soup = make_soup(NESTED)
    element = BaseParser.select_first(soup, "#nie-ma", "div.wrapper")
    assert element.get("class") == ["wrapper"]


def test_select_first_returns_none_when_nothing_matches():
    assert BaseParser.select_first(make_soup(NESTED), "#a", ".b") is None
