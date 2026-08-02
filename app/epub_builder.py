"""Assembling an EPUB from metadata + chapters (ebooklib)."""

from __future__ import annotations

import re
import tempfile
import unicodedata
import uuid
from pathlib import Path

from ebooklib import epub

from .models import ChapterContent, CoverImage, NovelMetadata

STYLESHEET = """\
body { font-family: serif; line-height: 1.5; margin: 0 5%; text-align: justify; }
h1, h2 { text-align: left; line-height: 1.25; }
p { margin: 0 0 0.75em 0; text-indent: 0; }
hr { border: 0; border-top: 1px solid currentColor; margin: 1.5em 20%; }
blockquote { margin: 1em 2em; font-style: italic; }
img { max-width: 100%; height: auto; }
.chapter-title { margin-bottom: 1.5em; }
.source-note { font-size: 0.8em; opacity: 0.7; }
"""


def build_epub(
    metadata: NovelMetadata,
    chapters: list[ChapterContent],
    cover: CoverImage | None = None,
) -> bytes:
    """Returns the finished EPUB file as bytes."""
    if not chapters:
        raise ValueError("Cannot build an EPUB with no chapters")

    book = epub.EpubBook()
    # Deterministic identifier: re-converting the same novel yields the same
    # UUID, so readers treat the file as an update rather than a new book.
    book.set_identifier(f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, metadata.source_url)}")
    book.set_title(metadata.title)
    book.set_language(metadata.language or "en")
    book.add_author(metadata.author)

    if metadata.description:
        book.add_metadata("DC", "description", metadata.description)
    if metadata.publisher:
        book.add_metadata("DC", "publisher", metadata.publisher)
    book.add_metadata("DC", "source", metadata.source_url)
    for tag in metadata.tags:
        book.add_metadata("DC", "subject", tag)

    style = epub.EpubItem(
        uid="style",
        file_name="style/main.css",
        media_type="text/css",
        content=STYLESHEET,
    )
    book.add_item(style)

    if cover is not None:
        book.set_cover(cover.file_name, cover.data)

    title_page = _build_title_page(metadata, style)
    book.add_item(title_page)

    spine: list[object] = ["nav", title_page]
    toc: list[epub.EpubHtml] = []

    for position, chapter in enumerate(chapters, start=1):
        item = epub.EpubHtml(
            title=chapter.title,
            file_name=f"text/chapter_{position:04d}.xhtml",
            lang=metadata.language or "en",
        )
        item.content = (
            f"<h2 class=\"chapter-title\">{_escape(chapter.title)}</h2>\n{chapter.html}"
        )
        item.add_item(style)
        book.add_item(item)
        spine.append(item)
        toc.append(item)

    book.toc = tuple(toc)
    book.spine = spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # ebooklib can only write to a path on disk.
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "book.epub"
        epub.write_epub(str(out_path), book)
        return out_path.read_bytes()


#: Characters with no NFKD decomposition (they are not "letter + diacritic"),
#: so without a manual map they would evaporate on the way to ASCII.
_TRANSLITERATION = str.maketrans(
    {
        "ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D",
        "ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "þ": "th",
    }
)


def slugify(value: str, *, fallback: str = "novel", max_length: int = 80) -> str:
    """A file name safe on Windows, on Linux and in a Content-Disposition header."""
    normalized = unicodedata.normalize("NFKD", value.translate(_TRANSLITERATION))
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_only).strip("-").lower()
    return (slug[:max_length].rstrip("-")) or fallback


def _build_title_page(metadata: NovelMetadata, style: epub.EpubItem) -> epub.EpubHtml:
    parts = [f"<h1>{_escape(metadata.title)}</h1>"]
    if metadata.author:
        parts.append(f"<p><em>{_escape(metadata.author)}</em></p>")
    if metadata.description:
        parts.append(f"<div>{_escape(metadata.description)}</div>")
    parts.append(
        "<p class=\"source-note\">"
        f"<a href=\"{_escape(metadata.source_url)}\">{_escape(metadata.source_url)}</a>"
        "</p>"
    )

    page = epub.EpubHtml(
        title=metadata.title,
        file_name="text/title.xhtml",
        lang=metadata.language or "en",
    )
    page.content = "\n".join(parts)
    page.add_item(style)
    return page


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
