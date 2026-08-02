"""Persistent registry of converted novels.

Storage is a single JSON file rather than SQLite: the data is tiny (one record
per novel), writes happen once per conversion, and a self-hoster can open the
file, fix a path or delete a row with a text editor. SQLite would buy
concurrency we do not need and cost readability we do.

What it does need is safety against a half-written file: writes go to a
temporary file in the same directory and are swapped in with os.replace(),
which is atomic. A process-wide lock serialises writers, because conversions
run in worker threads and two of them can finish at once.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .config import Settings, get_settings
from .models import LibraryEntry

log = logging.getLogger(__name__)

_WRITE_LOCK = threading.Lock()


def entry_id(source_url: str) -> str:
    """Stable id for a novel - the same URL always yields the same id.

    Deliberately the same derivation as the EPUB's `dc:identifier`, so a file
    and its library entry can always be matched up.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, source_url))


def utc_now() -> str:
    """Timestamp for library rows - UTC, second resolution, ISO 8601."""
    return datetime.now(UTC).isoformat(timespec="seconds")


class Library:
    """Reads and writes the library file. Cheap to construct; no state cached.

    Nothing is held in memory between calls: the file is small, and re-reading
    means an entry edited by hand (or by another process) is picked up.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.path: Path = self.settings.resolved_library_path()

    # -- Reading ------------------------------------------------------------

    def load(self) -> list[LibraryEntry]:
        if not self.path.is_file():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # A corrupt library must not take the whole app down - the user
            # would lose access to converting anything at all.
            log.warning("Could not read the library at %s: %s", self.path, exc)
            return []

        entries: list[LibraryEntry] = []
        for item in raw.get("entries", []):
            try:
                entries.append(LibraryEntry(**item))
            except Exception as exc:  # noqa: BLE001 - one bad row, not all of them
                log.warning("Skipping malformed library entry: %s", exc)
        return entries

    def get(self, entry_key: str) -> LibraryEntry | None:
        return next((e for e in self.load() if e.id == entry_key), None)

    # -- Writing ------------------------------------------------------------

    def save(self, entries: list[LibraryEntry]) -> None:
        payload = {
            "version": 1,
            "entries": [entry.model_dump() for entry in entries],
        }
        with _WRITE_LOCK:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                # Written in the target's own directory: os.replace is only
                # atomic within a single filesystem.
                fd, tmp_name = tempfile.mkstemp(
                    dir=self.path.parent, prefix=".library-", suffix=".tmp"
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                        json.dump(payload, tmp, ensure_ascii=False, indent=2)
                    os.replace(tmp_name, self.path)
                except BaseException:
                    Path(tmp_name).unlink(missing_ok=True)
                    raise
            except OSError as exc:
                # Losing the library is annoying; losing the conversion the
                # user just waited minutes for is worse.
                log.warning("Could not write the library at %s: %s", self.path, exc)

    def upsert(self, entry: LibraryEntry) -> LibraryEntry:
        """Adds the novel or refreshes the existing row, keeping created_at."""
        entries = self.load()
        for index, existing in enumerate(entries):
            if existing.id == entry.id:
                entry = entry.model_copy(update={"created_at": existing.created_at})
                entries[index] = entry
                break
        else:
            entries.append(entry)

        self.save(entries)
        return entry

    def delete(self, entry_key: str, *, delete_file: bool = False) -> LibraryEntry | None:
        entries = self.load()
        removed = next((e for e in entries if e.id == entry_key), None)
        if removed is None:
            return None

        self.save([e for e in entries if e.id != entry_key])

        if delete_file and removed.file_path:
            try:
                Path(removed.file_path).unlink(missing_ok=True)
                log.info("Deleted %s", removed.file_path)
            except OSError as exc:
                log.warning("Could not delete %s: %s", removed.file_path, exc)

        return removed

    # -- Building entries ---------------------------------------------------

    @staticmethod
    def build_entry(
        *,
        source_url: str,
        parser_name: str,
        title: str,
        author: str,
        language: str,
        cover_url: str | None,
        file_path: Path | None,
        chapter_count: int,
        last_chapter_url: str | None,
    ) -> LibraryEntry:
        timestamp = utc_now()
        return LibraryEntry(
            id=entry_id(source_url),
            source_url=source_url,
            parser=parser_name,
            title=title,
            author=author,
            language=language,
            cover_url=cover_url,
            file_path=str(file_path) if file_path else None,
            chapter_count=chapter_count,
            last_chapter_url=last_chapter_url,
            created_at=timestamp,
            updated_at=timestamp,
        )
