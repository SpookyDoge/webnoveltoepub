"""The chapter cap is opt-in: 0 (the default) converts everything."""

from __future__ import annotations

from app import service
from app.config import Settings
from app.models import ChapterContent, ChapterRef, ConvertRequest, NovelMetadata

URL = "https://www.royalroad.com/fiction/1/x"


class StubParser:
    name = "royalroad"
    requires_playwright = False
    on_chapters_found = None

    def __init__(self, total: int) -> None:
        self.total = total
        self.fetched: list[int] = []

    def get_metadata(self, url):
        return NovelMetadata(title="Novel", author="A", source_url=url)

    def get_chapter_list(self, url):
        return [
            ChapterRef(index=i, title=f"Chapter {i}", url=f"{url}/c{i}")
            for i in range(1, self.total + 1)
        ]

    def get_chapter_content(self, chapter):
        self.fetched.append(chapter.index)
        return ChapterContent(title=chapter.title, html="<p>Body</p>")

    def get_cover_image(self, metadata):
        return None


class StubFetcher:
    def close(self):
        pass


def _settings(tmp_path, **overrides) -> Settings:
    return Settings(library_path=tmp_path / "library.json", **overrides)


def test_no_cap_by_default():
    assert Settings().max_chapters == 0


def test_everything_is_converted_when_uncapped(tmp_path, monkeypatch):
    parser = StubParser(total=450)
    monkeypatch.setattr(service, "_make_parser", lambda url, s: (parser, StubFetcher()))

    result = service.convert(ConvertRequest(url=URL), _settings(tmp_path))

    assert result.chapter_count == 450
    assert len(parser.fetched) == 450
    assert result.warnings == []


def test_a_positive_cap_still_truncates_and_warns(tmp_path, monkeypatch):
    parser = StubParser(total=450)
    monkeypatch.setattr(service, "_make_parser", lambda url, s: (parser, StubFetcher()))

    result = service.convert(ConvertRequest(url=URL), _settings(tmp_path, max_chapters=100))

    assert result.chapter_count == 100
    assert len(parser.fetched) == 100
    assert "Limited to 100 chapters" in result.warnings[0]


def test_a_cap_larger_than_the_novel_changes_nothing(tmp_path, monkeypatch):
    parser = StubParser(total=5)
    monkeypatch.setattr(service, "_make_parser", lambda url, s: (parser, StubFetcher()))

    result = service.convert(ConvertRequest(url=URL), _settings(tmp_path, max_chapters=100))

    assert result.chapter_count == 5
    assert result.warnings == []


def test_preview_reports_the_cap_so_the_ui_can_tick_boxes(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "_make_parser", lambda url, s: (StubParser(9), StubFetcher()))

    assert service.preview(URL, _settings(tmp_path)).max_chapters == 0
    assert service.preview(URL, _settings(tmp_path, max_chapters=7)).max_chapters == 7
