"""Reading a library exported from the WebToEpub browser extension.

WebToEpub keeps its library in browser storage and exports it two ways:

* a ZIP (version 2), with one folder per novel -
  `Library/<i>/{LibStoryURL,LibFilename,LibEpub,LibCover,LibNewChapterCount}`
  plus `LibraryVersion.txt` and `LibraryCountEntries.txt`,
* a legacy JSON file with a `Library` array of objects carrying the same
  `Lib*` properties.

Both are accepted. `LibEpub` is a data URI (`data:application/epub+zip;base64,`
- Firefox writes `application/octet-stream` instead), and `LibFilename` is the
file name without its `.epub` extension.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import zipfile
from dataclasses import dataclass

from ebooklib import epub

log = logging.getLogger(__name__)

_ZIP_MAGIC = b"PK\x03\x04"
_DATA_URI_RE = re.compile(r"^data:[^;,]*;base64,", re.I)

#: Documents WebToEpub adds that are not chapters. Matched on the file name,
#: which is the only thing that reliably survives its export.
_NON_CHAPTER_RE = re.compile(
    r"(information|cover|title|toc|nav|contents)", re.I
)


class WebToEpubImportError(RuntimeError):
    """The uploaded file is not a WebToEpub export we can read."""


@dataclass
class ImportedNovel:
    """One novel lifted out of a WebToEpub export."""

    source_url: str
    title: str
    epub_bytes: bytes
    #: Chapters counted inside the EPUB - see count_chapters() for the caveat.
    chapter_count: int


def parse_export(data: bytes) -> list[ImportedNovel]:
    """Reads either export format and returns the novels found in it."""
    if data[:4] == _ZIP_MAGIC:
        return _parse_zip(data)
    return _parse_json(data)


def _parse_zip(data: bytes) -> list[ImportedNovel]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise WebToEpubImportError("Not a readable ZIP file") from exc

    with archive:
        names = set(archive.namelist())
        # Trust the folders that are actually present rather than the declared
        # count: a truncated export should still yield whatever survived.
        indices = sorted(
            {
                int(match.group(1))
                for name in names
                if (match := re.match(r"Library/(\d+)/", name))
            }
        )
        if not indices:
            raise WebToEpubImportError("No Library/<n>/ entries in the archive")

        novels: list[ImportedNovel] = []
        for index in indices:
            def read(key: str, i: int = index) -> str | None:
                name = f"Library/{i}/{key}"
                if name not in names:
                    return None
                return archive.read(name).decode("utf-8", errors="replace")

            novel = _build(read("LibStoryURL"), read("LibFilename"), read("LibEpub"))
            if novel is not None:
                novels.append(novel)

    if not novels:
        raise WebToEpubImportError("The archive held no readable novels")
    return novels


def _parse_json(data: bytes) -> list[ImportedNovel]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebToEpubImportError("Not a WebToEpub ZIP or JSON export") from exc

    rows = payload.get("Library") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise WebToEpubImportError("JSON export has no 'Library' array")

    novels = [
        novel
        for row in rows
        if isinstance(row, dict)
        and (
            novel := _build(
                row.get("LibStoryURL"), row.get("LibFilename"), row.get("LibEpub")
            )
        )
        is not None
    ]
    if not novels:
        raise WebToEpubImportError("The export held no readable novels")
    return novels


def _build(url: str | None, file_name: str | None, epub_uri: str | None) -> ImportedNovel | None:
    """Turns one raw row into a novel, skipping anything unusable."""
    if not url or not epub_uri:
        log.warning("Skipping WebToEpub entry without a URL or EPUB")
        return None

    try:
        payload = decode_epub(epub_uri)
    except Exception as exc:  # noqa: BLE001 - one bad row must not sink the import
        log.warning("Skipping %s: %s", url, exc)
        return None

    title = (file_name or "").strip() or url.rstrip("/").rsplit("/", 1)[-1]
    return ImportedNovel(
        source_url=url.strip(),
        title=title,
        epub_bytes=payload,
        chapter_count=count_chapters(payload),
    )


def decode_epub(value: str) -> bytes:
    """Decodes the stored EPUB, with or without its data-URI prefix."""
    payload = base64.b64decode(_DATA_URI_RE.sub("", value.strip()), validate=False)
    if payload[:4] != _ZIP_MAGIC:
        raise ValueError("Decoded data is not an EPUB")
    return payload


def count_chapters(payload: bytes) -> int:
    """Counts chapter documents in an EPUB written by someone else.

    Best effort by design: WebToEpub does not record how many chapters a book
    holds, so this counts reading-order documents and drops the obvious
    non-chapters (its information page, covers, contents). The number matters
    because updates resume from it, so it is reported back to the user rather
    than applied silently.
    """
    try:
        book = epub.read_epub(io.BytesIO(payload))
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not read an imported EPUB to count chapters: %s", exc)
        return 0

    count = 0
    for entry in book.spine:
        item_id = entry[0] if isinstance(entry, (tuple, list)) else entry
        item = book.get_item_with_id(item_id) if isinstance(item_id, str) else item_id
        if not isinstance(item, epub.EpubHtml) or isinstance(item, epub.EpubNav):
            continue
        if _NON_CHAPTER_RE.search(item.file_name or ""):
            continue
        count += 1
    return count
