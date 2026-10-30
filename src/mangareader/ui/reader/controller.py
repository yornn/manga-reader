"""Reader state: which source is open, which pages are shown, and what to persist."""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from mangareader.library.classify import (SeriesTree, SourceEntry, SourceInfo, TreeNode, chapter_spans,
                                          entry_from_info, find_series_root, internal_chapters, is_volume_folder)
from mangareader.library.fingerprint import fingerprint
from mangareader.library.model import ChapterMark, Kind, SeriesPrefs, SourceRecord
from mangareader.library.scanner import scan_series
from mangareader.library.store import Store
from mangareader.paths import DataLocation, find_7zz
from mangareader.render.cache import ImageCache
from mangareader.render.loader import PageLoader
from mangareader.render.thumbs import ThumbnailStore
from mangareader.settings import Settings, load_settings
from mangareader.sources import SourceContext, open_source
from mangareader.sources.base import PageSource, PasswordRequired, SourceError
from mangareader.sources.folder import has_direct_images
from mangareader.sources.sevenzip import ExtractClaim, claim_extract_dir, release_extract_dir
from mangareader.ui.reader.layout import Direction, Mode, group_index, place_group, place_ribbon, view_groups
from mangareader.ui.reader.navigation import Position, chapter_starts, step, step_chapter
from mangareader.ui.reader.view import PageView

log = logging.getLogger("mangareader.reader")

PasswordProvider = Callable[[Path, bool], "str | None"]


@dataclass
class Services:
    data: DataLocation
    settings: Settings
    store: Store
    ctx: SourceContext
    cache: ImageCache
    thumbs: ThumbnailStore
    loader: PageLoader
    extract_claim: ExtractClaim

    def shutdown(self) -> None:
        self.store.close()
        release_extract_dir(self.extract_claim)


def make_services(data: DataLocation) -> Services:
    settings = load_settings(data.settings_file)
    claim = claim_extract_dir(data.extract)
    cache = ImageCache(settings.cache_mb * 2**20)
    thumbs = ThumbnailStore(data.thumbs)
    return Services(data, settings, Store(data.db), SourceContext(claim.path, find_7zz()), cache, thumbs,
                    PageLoader(cache, thumbs), claim)


def _inside(path: Path, folder: Path) -> bool:
    p, f = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(folder))
    try:
        return p != f and os.path.commonpath([p, f]) == f   # also right for a drive root like E:\\
    except ValueError:  # different drives
        return False


class _ScanTask(QRunnable):
    def __init__(self, fn: Callable[[], None]):
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            self._fn()
        except Exception:
            log.exception("series scan failed")


class ReaderController(QObject):
    state_changed = Signal()
    tree_changed = Signal()
    source_opened = Signal()
    source_changed = Signal(str)
    error = Signal(str)
    _scan_done = Signal(object)

    def __init__(self, services: Services, view: PageView, parent: QObject | None = None):
        super().__init__(parent)
        self.services = services
        self.view = view
        self.password_provider: PasswordProvider | None = None
        self.tree: SeriesTree | None = None
        self.entries: list[SourceEntry] = []
        self.entry_index = 0
        self.series_root: Path | None = None
        self.source: PageSource | None = None
        self.source_key: str | None = None
        self.record: SourceRecord | None = None
        self.sizes: list[tuple[int, int] | None] = []
        self.groups: list[list[int]] = []
        self.page = 0
        self.mode = Mode.SINGLE
        self.direction = Direction.RTL
        self._relayout = QTimer(self)
        self._relayout.setSingleShot(True)
        self._relayout.setInterval(150)
        self._relayout.timeout.connect(self._apply_sizes)
        self._fingerprint = ""
        self._book_layout = (0, 0, 0.0)
        self._book_relayout = QTimer(self)
        self._book_relayout.setSingleShot(True)
        self._book_relayout.setInterval(300)
        self._book_relayout.timeout.connect(self._relayout_book)
        view.resized.connect(self._on_view_resized)
        services.loader.size_known.connect(self._on_size_known)
        view.visible_page_changed.connect(self._on_ribbon_page)
        view.flip_requested.connect(lambda forward: self.next() if forward else self.prev())
        self._scan_done.connect(self._on_scan_done)

    # -- properties ---------------------------------------------------------------------
    @property
    def entry(self) -> SourceEntry | None:
        return self.entries[self.entry_index] if self.entries else None

    @property
    def position(self) -> Position:
        return Position(self.entry_index, self.page)

    @property
    def current_group(self) -> list[int]:
        if not self.groups:
            return []
        if self.mode is Mode.RIBBON:
            return [self.page]
        return self.groups[group_index(self.groups, self.page)]

    # -- opening --------------------------------------------------------------------------
    def open_path(self, path: Path, password: str | None = None) -> bool:
        path = Path(path)
        if not path.exists():
            self.error.emit(f"Файл не найден: {path.name}")
            return False
        if path.is_dir() and not has_direct_images(path):
            root = path.parent if is_volume_folder(path) else path
            tree = scan_series(root, self.services.store, self.services.ctx)
            inside = [e for e in tree.reading_order() if _inside(e.path, path)]
            if not inside:
                self.error.emit("В папке нет страниц")
                return False
            latest = self.services.store.latest_progress([e.record_id for e in inside if e.record_id])
            target = next((e for e in inside if e.record_id == latest), inside[0])
            if not self._open_source(target.path, password, root):
                return False
            self._set_tree(tree)
            return True
        root = find_series_root(path)
        if not self._open_source(path, password, root):
            return False
        self._start_scan(root)
        return True

    def _open_with_password(self, path: Path, password: str | None) -> PageSource | None:
        while True:
            try:
                return open_source(path, self.services.ctx, password)
            except PasswordRequired as e:
                answer = self.password_provider(path, e.wrong) if self.password_provider else None
                if not answer:
                    return None
                password = answer
            except SourceError as e:
                self.error.emit(str(e))
                return None

    def _open_source(self, path: Path, password: str | None, series_root: Path,
                     start_page: int | None = None) -> bool:
        source = self._open_with_password(path, password)
        if source is None:
            return False
        if not source.pages:
            source.close()
            self.error.emit("В файле нет страниц")
            return False
        self.close_source()
        store = self.services.store
        if path.is_dir():
            size, mtime = source.file_size, 0.0
        else:
            st = path.stat()
            size, mtime = st.st_size, st.st_mtime
        fp = fingerprint(source)
        self.record = store.register(path, size, mtime, fp, len(source.pages), tuple(internal_chapters(source.pages)))
        self.source, self.source_key, self._fingerprint = source, str(path), fp
        self._layout_book()
        self.services.loader.register(self.source_key, source, self._thumb_key())
        if self.series_root is None or os.path.normcase(str(self.series_root)) != os.path.normcase(str(series_root)):
            self.series_root = series_root
            self.tree = None
            self.entries = []
        prefs = store.series_prefs(series_root)
        if prefs:
            self.mode, self.direction = Mode(prefs.mode), Direction(prefs.direction)
        else:
            self.mode = Mode.SINGLE
            self.direction = Direction.LTR if source.kind == "document" else Direction.RTL
        index = self.tree.index_of(path) if self.tree else None
        if index is None:
            info = SourceInfo(len(source.pages), self.record.chapters, self.record.kind_override,
                              tuple(store.chapter_marks(self.record.id)), self.record.id)
            self.entries = [entry_from_info(path, info)]
            index = 0
        self.entry_index = index
        self.sizes = [None] * len(source.pages)
        self.services.loader.probe_sizes(self.source_key)
        if start_page is None:
            progress = store.progress(self.record.id)
            start_page = source.page_for_token(progress.position) if progress else 0
        self.services.settings.add_recent(str(path))
        self.source_opened.emit()
        self._rebuild_groups()
        self._show(max(0, min(start_page, len(source.pages) - 1)))
        return True

    def close_source(self) -> None:
        if self.source is not None:
            self.services.loader.unregister(self.source_key)
            self.source.close()
        self.source, self.source_key, self.record = None, None, None

    # -- series scan ----------------------------------------------------------------------
    def _start_scan(self, root: Path) -> None:
        services = self.services

        def run() -> None:
            tree = scan_series(root, services.store, services.ctx)
            try:
                self._scan_done.emit(tree)
            except RuntimeError:  # window already gone
                pass
        QThreadPool.globalInstance().start(_ScanTask(run))

    def _on_scan_done(self, tree: SeriesTree) -> None:
        if self.series_root is None or os.path.normcase(str(tree.root)) != os.path.normcase(str(self.series_root)):
            return
        self._set_tree(tree)

    def _set_tree(self, tree: SeriesTree) -> None:
        if self.source is not None:
            index = tree.index_of(self.source.path)
            if index is None:  # e.g. a .txt the scan skips: keep the list that holds just this file
                return
            self.entries = tree.reading_order()
            self.entry_index = index
        self.tree = tree
        self.refresh_entry_chapters()
        self.tree_changed.emit()
        self.state_changed.emit()

    def rescan(self) -> None:
        if self.series_root is not None:
            self._set_tree(scan_series(self.series_root, self.services.store, self.services.ctx))

    # -- layout -----------------------------------------------------------------------------
    def _rebuild_groups(self) -> None:
        offset = self.record.spread_offset if self.record else 0
        self.groups = view_groups(self.mode, self.sizes, offset)

    def _show(self, page: int) -> None:
        if self.source is None or not self.groups:
            return
        if self.mode is Mode.RIBBON:
            self.page = page
            self.view.show_pages(self.source_key, place_ribbon(self.sizes), self.direction, ribbon=True,
                                 focus_page=page)
            neighbours = [page + 1, page + 2, page - 1]
            self.services.loader.prefetch(self.source_key, [p for p in neighbours if 0 <= p < len(self.sizes)])
        else:
            gi = group_index(self.groups, page)
            self.page = self.groups[gi][0]
            self.view.show_pages(self.source_key, place_group(self.groups[gi], self.sizes, self.direction),
                                 self.direction)
            self._prepare_neighbours(gi)
        self._save_progress()
        self.state_changed.emit()

    def _prepare_neighbours(self, gi: int) -> None:
        for g in (gi + 1, gi + 2, gi - 1):
            if 0 <= g < len(self.groups):
                self.view.prepare(self.source_key, place_group(self.groups[g], self.sizes, self.direction))

    def _save_progress(self) -> None:
        if self.record is None or self.source is None:
            return
        last = self.page >= len(self.source.pages) - 1 if self.mode is Mode.RIBBON else (
            group_index(self.groups, self.page) == len(self.groups) - 1)
        self.services.store.set_progress(self.record.id, self.source.position_token(self.page), last)

    def _on_size_known(self, key: str, page: int, w: int, h: int) -> None:
        if key != self.source_key or page >= len(self.sizes) or self.sizes[page] == (w, h):
            return
        self.sizes[page] = (w, h)
        self._relayout.start()

    def _apply_sizes(self) -> None:
        # re-show only if the pages on screen moved; otherwise just remember the sizes
        if self.source is None:
            return
        self._rebuild_groups()
        if self.mode is Mode.RIBBON:
            placed = place_ribbon(self.sizes)
            if placed != self.view.placed():
                self.view.show_pages(self.source_key, placed, self.direction, ribbon=True, focus_page=self.page,
                                     anchor=self.view.ribbon_anchor())
            return
        gi = group_index(self.groups, self.page)
        if place_group(self.groups[gi], self.sizes, self.direction) != self.view.placed():
            self._show(self.page)
        else:
            self._prepare_neighbours(gi)

    def _on_ribbon_page(self, page: int) -> None:
        if self.mode is Mode.RIBBON and self.source is not None:
            self.page = page
            self._save_progress()
            self.state_changed.emit()

    # -- books -----------------------------------------------------------------------------------------
    def _layout_book(self) -> None:
        # lay a reflowable book out for the current window and font size
        viewport = self.view.viewport()
        self._book_layout = (max(200, viewport.width()), max(200, viewport.height()),
                             self.services.settings.book_font_size)
        self.source.relayout(*self._book_layout)

    def _thumb_key(self) -> str:
        # book pages change with the layout, so their thumbnails are keyed by it as well
        if self.source is not None and self.source.is_reflowable:
            w, h, font = self._book_layout
            return f"{self._fingerprint}-{w}x{h}-{font:g}"
        return self._fingerprint

    def _relayout_book(self) -> None:
        source = self.source
        if source is None or not source.is_reflowable:
            return
        token = source.position_token(self.page)
        self._layout_book()
        loader = self.services.loader
        loader.unregister(self.source_key)
        loader.register(self.source_key, source, self._thumb_key())
        self.sizes = [None] * len(source.pages)
        loader.probe_sizes(self.source_key)
        self.source_opened.emit()
        self._rebuild_groups()
        self._show(source.page_for_token(token))

    def _on_view_resized(self) -> None:
        if self.source is not None and self.source.is_reflowable:
            self._book_relayout.start()

    def set_font_size(self, size: float) -> None:
        self.services.settings.book_font_size = size
        self._relayout_book()

    # -- navigation ---------------------------------------------------------------------------
    def _page_counts(self) -> list[int]:
        counts = [e.page_count for e in self.entries]
        if self.source is not None and self.entries:
            counts[self.entry_index] = len(self.source.pages)
        return counts

    def go_to(self, pos: Position) -> None:
        if not 0 <= pos.entry < len(self.entries):
            return
        if pos.entry == self.entry_index:
            if self.mode is Mode.RIBBON:
                self.page = pos.page
                self.view.scroll_to_page(pos.page)
                self._save_progress()
                self.state_changed.emit()
            else:
                self._show(pos.page)
            return
        entry = self.entries[pos.entry]
        if self._open_source(entry.path, None, self.series_root or entry.path.parent, start_page=pos.page):
            self.source_changed.emit(entry.title)

    def _step(self, forward: bool) -> None:
        if self.source is None:
            return
        if self.mode is Mode.RIBBON:
            target = self.page + (1 if forward else -1)
            if 0 <= target < len(self.source.pages):
                self.go_to(Position(self.entry_index, target))
                return
            groups = [[i] for i in range(len(self.source.pages))]
        else:
            groups = self.groups
        pos = step(self.position, groups, self._page_counts(), forward)
        if pos is not None:
            self.go_to(pos)

    def next(self) -> None:
        self._step(True)

    def prev(self) -> None:
        self._step(False)

    def next_chapter(self) -> None:
        pos = step_chapter(self.position, chapter_starts(self.entries), True)
        if pos is not None:
            self.go_to(pos)

    def prev_chapter(self) -> None:
        pos = step_chapter(self.position, chapter_starts(self.entries), False)
        if pos is not None:
            self.go_to(pos)

    def first_page(self) -> None:
        self.go_to(Position(self.entry_index, 0))

    def last_page(self) -> None:
        if self.source is not None:
            self.go_to(Position(self.entry_index, len(self.source.pages) - 1))

    # -- modes ---------------------------------------------------------------------------------
    def _save_prefs(self) -> None:
        if self.series_root is not None:
            self.services.store.set_series_prefs(self.series_root, SeriesPrefs(self.direction.value, self.mode.value))

    def set_mode(self, mode: Mode) -> None:
        self.mode = mode
        self._save_prefs()
        self._rebuild_groups()
        self._show(self.page)

    def toggle_direction(self) -> None:
        self.direction = Direction.LTR if self.direction is Direction.RTL else Direction.RTL
        self._save_prefs()
        self._show(self.page)

    def toggle_spread_offset(self) -> None:
        if self.record is None:
            return
        self.services.store.set_spread_offset(self.record.id, 1 - self.record.spread_offset)
        self.record = self.services.store.find_by_path(self.record.path)
        self._rebuild_groups()
        self._show(self.page)

    # -- labels -----------------------------------------------------------------------------------
    def breadcrumb(self) -> list[str]:
        entry = self.entry
        if entry is None:
            return []
        parts = [self.tree.title if self.tree else (self.series_root.name if self.series_root else "")]
        node = next((n for n in (self.tree.nodes if self.tree else []) if entry in n.entries), None)
        parts.append(node.title if node else entry.title)
        if entry.chapters:
            current = [c for c in entry.chapters if c.start_page <= self.page]
            if current:
                parts.append(current[-1].title)
        elif node is None or node.folder is not None:
            parts.append(entry.title)
        result: list[str] = []
        for part in parts:
            if part and (not result or result[-1] != part):
                result.append(part)
        return result

    def page_label(self) -> str:
        if self.source is None:
            return ""
        total = len(self.source.pages)
        group = self.current_group
        if len(group) > 1:
            return f"{min(group) + 1}–{max(group) + 1}/{total}"
        return f"{self.page + 1}/{total}"

    def refresh_entry_chapters(self) -> None:
        """Recompute the current volume's chapters from the store (internal spans + manual marks)."""
        if self.record is None or self.entry is None:
            return
        record = self.services.store.find_by_path(self.record.path)
        if record is not None and self.entry.kind is Kind.VOLUME:
            self.entry.chapters = chapter_spans(record.chapters, self.services.store.chapter_marks(record.id))

    # -- marks and overrides -------------------------------------------------------------------------
    def display_tree(self) -> SeriesTree | None:
        if self.tree is not None:
            return self.tree
        if self.series_root is None or not self.entries:
            return None
        nodes = [TreeNode(e.kind, e.title, e.number, [e]) for e in self.entries]
        return SeriesTree(self.series_root, self.series_root.name, nodes, [])

    def marks(self) -> dict[int, ChapterMark]:
        if self.record is None:
            return {}
        return {m.page_index: m for m in self.services.store.chapter_marks(self.record.id)}

    def markable(self) -> bool:
        return self.entry is not None and self.entry.kind is Kind.VOLUME

    def add_chapter_mark(self, page: int, number: str, title: str = "") -> None:
        if self.record is None:
            return
        self.services.store.set_chapter_mark(self.record.id, ChapterMark(page, number, title))
        self._marks_changed()

    def delete_chapter_mark(self, page: int) -> None:
        if self.record is None:
            return
        self.services.store.delete_chapter_mark(self.record.id, page)
        self._marks_changed()

    def _marks_changed(self) -> None:
        self.refresh_entry_chapters()
        self.tree_changed.emit()
        self.state_changed.emit()

    def set_kind_override(self, entry_index: int, kind: Kind | None) -> None:
        if not 0 <= entry_index < len(self.entries):
            return
        record_id = self.entries[entry_index].record_id
        if record_id is None:
            return
        self.services.store.set_kind_override(record_id, kind)
        if self.record is not None and self.record.id == record_id:
            self.record = self.services.store.find_by_path(self.record.path)
        self.rescan()
