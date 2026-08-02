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


def append_chapters(epub_path: Path, chapters: list[ChapterContent]) -> bytes:
    """Adds chapters to an EPUB that already exists, returning the new bytes.

    The point is that the chapters already in the file are never re-downloaded:
    they are read back from disk, and only the new ones come off the network.
    """
    if not chapters:
        raise ValueError("No chapters to append")

    book = epub.read_epub(str(epub_path))

    # read_epub hands back the table of contents as Link objects whose uid is
    # None, and the NCX writer puts that straight into an XML attribute - which
    # throws. So the contents list is rebuilt from the actual documents, with
    # the titles recovered from those Links.
    titles_by_href = {
        getattr(link, "href", None): getattr(link, "title", None) for link in book.toc
    }
    documents = _documents_in_spine_order(book)
    for item in documents:
        if not item.title:
            item.title = titles_by_href.get(item.file_name) or item.file_name

    # File names carry the ordering, so continue from the highest one rather
    # than from the item count - a gap would otherwise cause a collision.
    existing = [item for item in documents if _CHAPTER_FILE_RE.match(item.file_name or "")]
    next_position = 1 + max(
        (int(_CHAPTER_FILE_RE.match(item.file_name).group(1)) for item in existing),
        default=0,
    )

    language = book.get_metadata("DC", "language")
    lang = language[0][0] if language else "en"

    style = next(
        (item for item in book.get_items() if item.file_name.endswith("main.css")), None
    )

    added: list[epub.EpubHtml] = []
    for offset, chapter in enumerate(chapters):
        position = next_position + offset
        item = epub.EpubHtml(
            # The uid must be set explicitly: on a book that came from
            # read_epub, ebooklib does not hand out ids, and a None id reaches
            # the NCX writer as an attribute value and blows up there.
            uid=f"chapter_{position:04d}",
            title=chapter.title,
            file_name=f"text/chapter_{position:04d}.xhtml",
            lang=lang,
        )
        item.content = (
            f"<h2 class=\"chapter-title\">{_escape(chapter.title)}</h2>\n{chapter.html}"
        )
        if style is not None:
            item.add_item(style)
        book.add_item(item)
        added.append(item)

    # read_epub gives spine entries as (idref, linear) tuples; the writer also
    # accepts item objects, so appending them directly is safe.
    book.spine = list(book.spine) + added
    book.toc = tuple(documents + added)

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "book.epub"
        epub.write_epub(str(out_path), book)
        return out_path.read_bytes()


#: Chapter file names produced by build_epub - also how append_chapters finds
#: where the existing numbering ends.
_CHAPTER_FILE_RE = re.compile(r"(?:.*/)?chapter_(\d+)\.xhtml$")


def _documents_in_spine_order(book: epub.EpubBook) -> list[epub.EpubHtml]:
    """Readable documents in reading order, skipping the generated navigation."""
    documents: list[epub.EpubHtml] = []
    for entry in book.spine:
        item_id = entry[0] if isinstance(entry, (tuple, list)) else entry
        item = book.get_item_with_id(item_id) if isinstance(item_id, str) else item_id
        if isinstance(item, epub.EpubHtml) and not isinstance(item, epub.EpubNav):
            documents.append(item)
    return documents


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
