"""The library catalog: library folders, series, shelves, favourites and read marks (stage 2 spec)."""
from __future__ import annotations

import json
import math
import os
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path

from mangareader.library.classify import is_inside
from mangareader.library.store import Store, path_key
from mangareader.sources.natsort import natural_key


class Status(StrEnum):
    NOT_STARTED = "not_started"
    READING = "reading"
    FINISHED = "finished"


class CatalogError(ValueError):
    """A ready-made message for the person using the program."""


@dataclass(frozen=True)
class Root:
    id: int
    path: Path
    added_at: float

    @property
    def available(self) -> bool:
        return self.path.is_dir()


@dataclass(frozen=True)
class Shelf:
    id: int
    name: str
    icon: str
    created_at: float


@dataclass(frozen=True)
class SeriesCard:
    id: int
    path: Path
    title: str
    root_id: int | None
    added_at: float
    last_opened_at: float | None
    favorite: bool
    formats: tuple[str, ...]
    cover_source_id: int | None
    last_source_id: int | None
    where: tuple[str, ...]
    shelf_ids: frozenset[int]
    available: bool
    pages_total: int
    pages_read: float
    sources: int
    opened: int
    finished: int

    @property
    def main_format(self) -> str:
        return self.formats[0] if self.formats else ""

    @property
    def status(self) -> Status:
        if self.opened == 0:
            return Status.NOT_STARTED
        if self.sources and self.finished == self.sources:
            return Status.FINISHED
        return Status.READING

    @property
    def progress(self) -> float:
        if self.pages_total:
            return min(1.0, self.pages_read / self.pages_total)
        return 1.0 if self.status is Status.FINISHED else 0.0


_CARD_SQL = """
SELECT s.id, s.path, s.title, s.root_id, s.added_at, s.last_opened_at, s.favorite, s.formats, s.cover_source_id,
       s.last_source_id, s.last_label,
       COALESCE(SUM(src.page_count), 0),
       COALESCE(SUM(CASE WHEN p.finished THEN src.page_count ELSE COALESCE(p.fraction, 0) * src.page_count END), 0),
       COUNT(src.id), COUNT(p.source_id), COALESCE(SUM(p.finished), 0)
FROM series s LEFT JOIN sources src ON src.series_id = s.id LEFT JOIN progress p ON p.source_id = src.id
"""


def _shelf_key(name: str) -> str:
    return name.strip().casefold()


def _moved(path: str, old: Path, new: Path) -> str:
    return str(new) + os.path.abspath(path)[len(os.path.abspath(old)):]


class Catalog:
    def __init__(self, store: Store):
        self.store = store

    # -- library folders ----------------------------------------------------------------------------
    def roots(self) -> list[Root]:
        rows = self.store.query("SELECT id, path, added_at FROM roots ORDER BY added_at, id")
        return [Root(rid, Path(path), added) for rid, path, added in rows]

    def _check_nesting(self, path: Path, except_id: int | None = None) -> None:
        key = path_key(path)
        for root in self.roots():
            if root.id == except_id:
                continue
            if path_key(root.path) == key:
                raise CatalogError("Эта папка уже в библиотеке")
            if is_inside(path, root.path):
                raise CatalogError(f"Эта папка уже внутри папки библиотеки «{root.path.name}»")
            if is_inside(root.path, path):
                raise CatalogError(f"Внутри этой папки уже есть папка библиотеки «{root.path.name}»")

    def add_root(self, path: Path) -> int:
        path = Path(os.path.abspath(path))
        key = path_key(path)
        self._check_nesting(path)
        return self.store.execute("INSERT INTO roots(path, path_key, added_at) VALUES (?, ?, ?)",
                                  (str(path), key, self.store.now()))

    def remove_root(self, root_id: int) -> None:
        self.store.execute("DELETE FROM roots WHERE id=?", (root_id,))

    def relocate_root(self, root_id: int, new_path: Path) -> None:
        new = Path(os.path.abspath(new_path))
        row = self.store.query("SELECT path FROM roots WHERE id=?", (root_id,))
        if not row:
            return
        old = Path(row[0][0])
        self._check_nesting(new, except_id=root_id)
        old_key = path_key(old)

        def inside(key: str) -> bool:
            return key == old_key or key.startswith(old_key.rstrip(os.sep) + os.sep)

        with self.store.transaction() as conn:
            for table in ("roots", "series", "sources"):
                for rid, path, key in conn.execute(f"SELECT id, path, path_key FROM {table}").fetchall():
                    if inside(key):
                        moved = _moved(path, old, new)
                        conn.execute(f"UPDATE OR REPLACE {table} SET path=?, path_key=? WHERE id=?",
                                     (moved, path_key(Path(moved)), rid))
            for (key,) in conn.execute("SELECT series_key FROM series_prefs").fetchall():
                if inside(key):
                    conn.execute("UPDATE OR REPLACE series_prefs SET series_key=? WHERE series_key=?",
                                 (path_key(Path(_moved(key, old, new))), key))

    # -- series ---------------------------------------------------------------------------------------
    def ensure_series(self, path: Path, root_id: int | None = None) -> int:
        path = Path(path)
        key = path_key(path)
        with self.store.transaction() as conn:
            row = conn.execute("SELECT id, root_id FROM series WHERE path_key=?", (key,)).fetchone()
            if row is not None:
                if row[1] is None and root_id is not None:
                    conn.execute("UPDATE series SET root_id=? WHERE id=?", (root_id, row[0]))
                return row[0]
            title = path.stem if path.is_file() else path.name
            return conn.execute("INSERT INTO series(path, path_key, title, root_id, added_at) VALUES (?, ?, ?, ?, ?)",
                                (str(path), key, title, root_id, self.store.now())).lastrowid

    def update_series(self, series_id: int, *, title: str, formats: Sequence[str], cover_source_id: int | None,
                      source_ids: Sequence[int]) -> None:
        ids = list(dict.fromkeys(source_ids))
        marks = ",".join("?" * len(ids))
        with self.store.transaction() as conn:
            conn.execute("UPDATE series SET title=?, formats=?, cover_source_id=? WHERE id=?",
                         (title, ",".join(formats), cover_source_id, series_id))
            if ids:
                conn.execute(f"UPDATE sources SET series_id=NULL WHERE series_id=? AND id NOT IN ({marks})",
                             [series_id, *ids])
                conn.execute(f"UPDATE sources SET series_id=? WHERE id IN ({marks})", [series_id, *ids])
            else:
                conn.execute("UPDATE sources SET series_id=NULL WHERE series_id=?", (series_id,))

    def remove_series(self, series_id: int) -> None:
        self.store.execute("DELETE FROM series WHERE id=? AND root_id IS NULL", (series_id,))

    def _cards(self, where: str = "", params: Sequence = ()) -> list[SeriesCard]:
        rows = self.store.query(f"{_CARD_SQL} {where} GROUP BY s.id ORDER BY s.id", params)
        shelves: dict[int, set[int]] = {}
        for shelf_id, series_id in self.store.query("SELECT shelf_id, series_id FROM shelf_series"):
            shelves.setdefault(series_id, set()).add(shelf_id)
        cards = []
        for (sid, path, title, root_id, added, opened_at, favorite, formats, cover, last_source, label,
             total, read, sources, opened, finished) in rows:
            cards.append(SeriesCard(
                sid, Path(path), title, root_id, added, opened_at, bool(favorite),
                tuple(f for f in formats.split(",") if f), cover, last_source, tuple(json.loads(label)),
                frozenset(shelves.get(sid, ())), Path(path).exists(), total, read, sources, opened, finished))
        return cards

    def cards(self) -> list[SeriesCard]:
        return self._cards()

    def card(self, series_id: int) -> SeriesCard | None:
        found = self._cards("WHERE s.id=?", (series_id,))
        return found[0] if found else None

    def touch(self, series_id: int, source_id: int, where: Sequence[str]) -> None:
        self.store.execute("UPDATE series SET last_opened_at=?, last_source_id=?, last_label=? WHERE id=?",
                           (self.store.now(), source_id, json.dumps(list(where), ensure_ascii=False), series_id))

    def set_favorite(self, series_id: int, on: bool) -> None:
        self.store.execute("UPDATE series SET favorite=? WHERE id=?", (int(on), series_id))

    def mark_read(self, series_id: int) -> None:
        # position and updated_at stay, so reopening still lands on the last opened volume
        self.store.execute("INSERT INTO progress(source_id, position, finished, fraction, updated_at)"
                           " SELECT id, 0, 1, 1.0, 0 FROM sources WHERE series_id=?"
                           " ON CONFLICT(source_id) DO UPDATE SET finished=1, fraction=1.0", (series_id,))

    def mark_unread(self, series_id: int) -> None:
        with self.store.transaction() as conn:
            conn.execute("DELETE FROM progress WHERE source_id IN (SELECT id FROM sources WHERE series_id=?)",
                         (series_id,))
            conn.execute("UPDATE series SET last_source_id=NULL, last_label='[]' WHERE id=?", (series_id,))

    # -- shelves -------------------------------------------------------------------------------------
    def shelves(self) -> list[Shelf]:
        rows = self.store.query("SELECT id, name, icon, created_at FROM shelves ORDER BY created_at, id")
        return [Shelf(*row) for row in rows]

    def check_shelf_name(self, name: str, except_id: int | None = None) -> str | None:
        key = _shelf_key(name)
        if not key:
            return "Введите название"
        row = self.store.query("SELECT id FROM shelves WHERE name_key=?", (key,))
        if row and row[0][0] != except_id:
            return "Такая полка уже есть"
        return None

    def add_shelf(self, name: str, icon: str) -> int:
        error = self.check_shelf_name(name)
        if error:
            raise CatalogError(error)
        return self.store.execute("INSERT INTO shelves(name, name_key, icon, created_at) VALUES (?, ?, ?, ?)",
                                  (name.strip(), _shelf_key(name), icon, self.store.now()))

    def rename_shelf(self, shelf_id: int, name: str) -> None:
        error = self.check_shelf_name(name, shelf_id)
        if error:
            raise CatalogError(error)
        self.store.execute("UPDATE shelves SET name=?, name_key=? WHERE id=?",
                           (name.strip(), _shelf_key(name), shelf_id))

    def set_shelf_icon(self, shelf_id: int, icon: str) -> None:
        self.store.execute("UPDATE shelves SET icon=? WHERE id=?", (icon, shelf_id))

    def delete_shelf(self, shelf_id: int) -> None:
        self.store.execute("DELETE FROM shelves WHERE id=?", (shelf_id,))

    def add_to_shelf(self, shelf_id: int, series_ids: Sequence[int]) -> None:
        with self.store.transaction() as conn:
            conn.executemany("INSERT OR IGNORE INTO shelf_series(shelf_id, series_id) VALUES (?, ?)",
                             [(shelf_id, sid) for sid in series_ids])

    def remove_from_shelf(self, shelf_id: int, series_ids: Sequence[int]) -> None:
        with self.store.transaction() as conn:
            conn.executemany("DELETE FROM shelf_series WHERE shelf_id=? AND series_id=?",
                             [(shelf_id, sid) for sid in series_ids])


# -- views over the cards (no database access) -------------------------------------------------------
class SectionKind(StrEnum):
    ALL = "all"
    FAVORITES = "favorites"
    FORMAT = "format"
    SHELF = "shelf"


@dataclass(frozen=True)
class Section:
    kind: SectionKind = SectionKind.ALL
    value: str | int | None = None


class Sort(StrEnum):
    RECENT = "recent"
    TITLE = "title"
    ADDED = "added"


FORMAT_ORDER = ("CBZ", "CBR", "CB7", "ZIP", "RAR", "7Z", "PDF", "EPUB", "FB2", "MOBI", "XPS", "TXT", "Папка")
FOLDER_FORMAT = "Папка"
_LABEL_BY_EXT = {".oxps": "XPS"}


def format_label(path: Path) -> str:
    path = Path(path)
    if path.is_dir():
        return FOLDER_FORMAT
    ext = path.suffix.lower()
    return _LABEL_BY_EXT.get(ext, ext.lstrip(".").upper())


def series_formats(paths: Iterable[Path]) -> list[str]:
    counts = Counter(format_label(p) for p in paths)
    order = {f: i for i, f in enumerate(FORMAT_ORDER)}
    return sorted(counts, key=lambda f: (-counts[f], order.get(f, len(order)), f))


def normalize(text: str) -> str:
    return text.casefold().replace("ё", "е")


def _in_section(card: SeriesCard, section: Section) -> bool:
    if section.kind is SectionKind.FAVORITES:
        return card.favorite
    if section.kind is SectionKind.FORMAT:
        return section.value in card.formats
    if section.kind is SectionKind.SHELF:
        return section.value in card.shelf_ids
    return True


def filter_cards(cards: Iterable[SeriesCard], section: Section = Section(), query: str = "",
                 status: Status | None = None, sort: Sort = Sort.RECENT) -> list[SeriesCard]:
    sort = Sort(sort)                          # Qt widgets hand the value back as a plain string
    needle = normalize(query.strip())
    found = [c for c in cards if _in_section(c, section) and (status is None or c.status is status)
             and needle in normalize(c.title)]
    if sort is Sort.TITLE:
        found.sort(key=lambda c: natural_key(normalize(c.title)))
    elif sort is Sort.ADDED:
        found.sort(key=lambda c: -c.added_at)
    else:
        found.sort(key=lambda c: (c.last_opened_at is None, -(c.last_opened_at or 0.0), -c.added_at))
    return found


def continue_reading(cards: Iterable[SeriesCard], limit: int = 5) -> list[SeriesCard]:
    reading = [c for c in cards if c.status is Status.READING and c.last_opened_at is not None]
    reading.sort(key=lambda c: -c.last_opened_at)
    return reading[:limit]


def format_counts(cards: Iterable[SeriesCard]) -> list[tuple[str, int]]:
    counts = Counter(f for c in cards for f in set(c.formats))
    known = [(f, counts[f]) for f in FORMAT_ORDER if counts[f]]
    return known + sorted((f, n) for f, n in counts.items() if f not in FORMAT_ORDER)


def percent(card: SeriesCard) -> int:
    value = math.floor(card.progress * 100)
    return value if card.status is Status.FINISHED else min(99, value)


def tile_caption(card: SeriesCard) -> str:
    if not card.available:
        return "недоступно"
    if card.status is Status.FINISHED:
        return "прочитано"
    if card.status is Status.NOT_STARTED:
        return "не начато"
    return f"{card.where[0]} · {percent(card)}%" if card.where else f"{percent(card)}%"


def continue_caption(card: SeriesCard) -> str:
    return " · ".join(card.where) if card.where else f"{percent(card)}%"


def _plural_days(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "дня"
    return "дней"


def when_text(ts: float, now: float) -> str:
    then = datetime.fromtimestamp(ts)
    days = (date.fromtimestamp(now) - then.date()).days
    if days <= 0:
        return "сегодня"
    if days == 1:
        return "вчера"
    if days < 7:
        return f"{days} {_plural_days(days)} назад"
    return then.strftime("%d.%m.%Y")
