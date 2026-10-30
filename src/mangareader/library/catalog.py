"""The library catalog: library folders, series, shelves, favourites and read marks (stage 2 spec)."""
from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from mangareader.library.classify import is_inside
from mangareader.library.store import Store, path_key


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

    def add_root(self, path: Path) -> int:
        path = Path(os.path.abspath(path))
        key = path_key(path)
        for root in self.roots():
            if path_key(root.path) == key:
                raise CatalogError("Эта папка уже в библиотеке")
            if is_inside(path, root.path):
                raise CatalogError(f"Эта папка уже внутри папки библиотеки «{root.path.name}»")
            if is_inside(root.path, path):
                raise CatalogError(f"Внутри этой папки уже есть папка библиотеки «{root.path.name}»")
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
        if any(r.id != root_id and path_key(r.path) == path_key(new) for r in self.roots()):
            raise CatalogError("Эта папка уже в библиотеке")
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
