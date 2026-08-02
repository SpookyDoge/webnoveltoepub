from __future__ import annotations

from app.parsers import all_parsers, get_parser_by_name, get_parser_class
from app.parsers.base import BaseParser


def test_royalroad_is_registered():
    names = [parser.name for parser in all_parsers()]
    assert "royalroad" in names


def test_registry_skips_abstract_base():
    assert BaseParser not in all_parsers()


def test_url_matching():
    assert get_parser_class("https://www.royalroad.com/fiction/1/x").name == "royalroad"
    assert get_parser_class("https://royalroad.com/fiction/1/x").name == "royalroad"
    assert get_parser_class("https://example.com/novel/1") is None


def test_domain_matching_is_not_a_substring_check():
    """"notroyalroad.com" nie moze przejsc jako royalroad.com."""
    assert get_parser_class("https://notroyalroad.com/fiction/1") is None


def test_get_parser_by_name():
    assert get_parser_by_name("royalroad") is not None
    assert get_parser_by_name("nope") is None
