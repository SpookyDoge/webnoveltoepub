from __future__ import annotations

from app.models import ChapterRef, ConvertRequest
from app.service import select_chapters

CHAPTERS = [
    ChapterRef(index=i, title=f"Rozdzial {i}", url=f"https://x.test/{i}") for i in range(1, 11)
]


def _request(**kwargs) -> ConvertRequest:
    return ConvertRequest(url="https://x.test/novel", **kwargs)


def test_no_selection_means_everything():
    assert len(select_chapters(CHAPTERS, _request())) == 10


def test_range_is_inclusive():
    picked = select_chapters(CHAPTERS, _request(start=3, end=5))
    assert [c.index for c in picked] == [3, 4, 5]


def test_open_ended_range():
    assert [c.index for c in select_chapters(CHAPTERS, _request(start=8))] == [8, 9, 10]
    assert [c.index for c in select_chapters(CHAPTERS, _request(end=2))] == [1, 2]


def test_explicit_selection_wins_over_range():
    picked = select_chapters(CHAPTERS, _request(start=1, end=2, selected=[7, 9]))
    assert [c.index for c in picked] == [7, 9]


def test_selection_keeps_reading_order_and_ignores_bogus_indices():
    picked = select_chapters(CHAPTERS, _request(selected=[9, 2, 999]))
    assert [c.index for c in picked] == [2, 9]
