"""Left panel of the reader: volumes, chapters and page thumbnails in one expanding list (stage 2 spec, 7.2)."""
from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QStyledItemDelegate, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from mangareader.library.classify import SeriesTree
from mangareader.library.model import ChapterMark, Kind
from mangareader.library.store import Store
from mangareader.render.covers import CoverLoader
from mangareader.render.loader import PageLoader
from mangareader.ui import style
from mangareader.ui.reader.navigation import Position


class RowKind(StrEnum):
    VOLUME = "volume"
    CHAPTER = "chapter"
    THUMBS = "thumbs"


KIND_ROLE = Qt.UserRole
POSITION_ROLE = Qt.UserRole + 1
OVERRIDE_ROLE = Qt.UserRole + 2
PAGES_ROLE = Qt.UserRole + 3
SOURCE_ROLE = Qt.UserRole + 4
PROGRESS_ROLE = Qt.UserRole + 5
CONTAINER_ROLE = Qt.UserRole + 6        # (entry, first page, end page) of a row that holds thumbnails
THUMBS_PER_ROW = 3
_LABEL_GAP = 4


class _Tree(QTreeWidget):
    page_clicked = Signal(int)

    def __init__(self, panel: "NavPanel"):
        super().__init__()
        self._panel = panel

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            page = self._panel.page_at(event.position().toPoint())
            if page is not None:
                self.page_clicked.emit(page)
                event.accept()
                return
        super().mouseReleaseEvent(event)


class _Delegate(QStyledItemDelegate):
    def __init__(self, panel: "NavPanel"):
        super().__init__(panel)
        self._panel = panel

    def sizeHint(self, option, index) -> QSize:
        size = super().sizeHint(option, index)
        kind = index.data(KIND_ROLE)
        if kind == RowKind.THUMBS:
            return QSize(size.width(), style.NAV_THUMB.height() + option.fontMetrics.height() + 3 * _LABEL_GAP)
        if kind == RowKind.VOLUME:
            return QSize(size.width(), max(size.height(), style.VOLUME_COVER.height() + 8))
        return size

    def paint(self, painter: QPainter, option, index) -> None:
        kind = index.data(KIND_ROLE)
        if kind == RowKind.THUMBS:
            self._paint_thumbs(painter, option, index)
            return
        super().paint(painter, option, index)
        progress = index.data(PROGRESS_ROLE)
        if kind == RowKind.VOLUME and progress:
            left = option.rect.left() + style.VOLUME_COVER.width() + 10
            bar = QRect(left, option.rect.bottom() - style.PROGRESS_HEIGHT - 3,
                        max(0, option.rect.right() - left - 8), style.PROGRESS_HEIGHT)
            painter.save()
            painter.setPen(Qt.NoPen)
            painter.setBrush(style.PLACEHOLDER)
            painter.drawRect(bar)
            painter.setBrush(style.accent_color())
            painter.drawRect(QRect(bar.left(), bar.top(), round(bar.width() * min(1.0, progress)), bar.height()))
            painter.restore()

    def _paint_thumbs(self, painter: QPainter, option, index) -> None:
        panel = self._panel
        painter.save()
        line = option.fontMetrics.height()
        for slot, page in enumerate(index.data(PAGES_ROLE) or []):
            cell = panel.cell_rect(option.rect, slot)
            box = QRect(cell.left() + _LABEL_GAP, cell.top() + _LABEL_GAP, cell.width() - 2 * _LABEL_GAP,
                        cell.height() - line - 3 * _LABEL_GAP)
            image = panel.thumbnail(page)
            if image is None:
                painter.fillRect(box, style.PLACEHOLDER)
                target = box
            else:
                size = image.size().scaled(box.size(), Qt.KeepAspectRatio)
                target = QRect(0, 0, size.width(), size.height())
                target.moveCenter(box.center())
                painter.drawImage(target, image)
            if page == panel.current_page():
                painter.setPen(QPen(style.accent_color(), 3))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(target.adjusted(-2, -2, 2, 2))
            painter.setPen(style.muted_color())
            painter.drawText(QRect(cell.left(), box.bottom() + _LABEL_GAP, cell.width(), line), Qt.AlignCenter,
                             panel.thumb_label(page))
        painter.restore()


class NavPanel(QWidget):
    position_selected = Signal(int, int)
    mark_requested = Signal(int)
    mark_edit_requested = Signal(int)
    mark_delete_requested = Signal(int)
    kind_override_requested = Signal(int, str)

    def __init__(self, loader: PageLoader, covers: CoverLoader, store: Store, parent=None):
        super().__init__(parent)
        self._loader = loader
        self._covers = covers
        self._store = store
        self._series: SeriesTree | None = None
        self._key: str | None = None
        self._entry_index = 0
        self._count = 0
        self._marks: dict[int, ChapterMark] = {}
        self._markable = False
        self._current = Position(0, 0)
        self._containers: list[QTreeWidgetItem] = []
        self._auto_container: tuple[int, int] | None = None
        self._collapsing = False
        self.tree = _Tree(self)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(12)
        self.tree.setIconSize(style.VOLUME_COVER)
        self.tree.setItemDelegate(_Delegate(self))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.setVerticalScrollMode(QTreeWidget.ScrollPerPixel)
        self.tree.itemClicked.connect(self._on_clicked)
        self.tree.itemExpanded.connect(self._on_expanded)
        self.tree.page_clicked.connect(lambda page: self.position_selected.emit(self._entry_index, page))
        self.tree.customContextMenuRequested.connect(self._on_menu)
        self.tree.setFrameShape(QTreeWidget.NoFrame)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree)
        style.set_surface(self, style.PANEL)
        loader.thumb_ready.connect(self._on_thumb)
        covers.cover_ready.connect(self._on_cover)

    # -- data -----------------------------------------------------------------------------------------
    @property
    def page_count(self) -> int:
        return self._count

    def set_tree(self, tree: SeriesTree | None) -> None:
        self._series = tree
        self._rebuild()

    def set_source(self, key: str | None, entry_index: int, page_count: int, marks: dict[int, ChapterMark],
                   markable: bool) -> None:
        if (key, entry_index) != (self._key, self._entry_index):
            self._auto_container = None                  # another file: expand its current chapter again
        self._key, self._entry_index, self._count = key, entry_index, page_count
        self._marks, self._markable = dict(marks), markable
        self._rebuild()

    def set_marks(self, marks: dict[int, ChapterMark]) -> None:
        self._marks = dict(marks)
        self.tree.viewport().update()

    def current_page(self) -> int | None:
        return self._current.page if self._current.entry == self._entry_index else None

    def thumbnail(self, page: int):
        return self._loader.thumbnail(self._key, page) if self._key is not None else None

    def thumb_label(self, page: int) -> str:
        mark = self._marks.get(page)
        return f"{page + 1} · Гл {mark.number}" if mark else f"{page + 1}"

    # -- building ---------------------------------------------------------------------------------------
    def _progress(self, record_ids_and_pages: list[tuple[int | None, int]]) -> float:
        total = sum(n for _, n in record_ids_and_pages)
        if not total:
            return 0.0
        read = 0.0
        for record_id, pages in record_ids_and_pages:
            progress = self._store.progress(record_id) if record_id is not None else None
            if progress is not None:
                read += pages * (1.0 if progress.finished else progress.fraction)
        return read / total

    def _row(self, kind: RowKind, text: str, pos: Position | None, parent: QTreeWidgetItem | None = None
             ) -> QTreeWidgetItem:
        item = QTreeWidgetItem([text])
        item.setData(0, KIND_ROLE, kind)
        if pos is not None:
            item.setData(0, POSITION_ROLE, pos)
        if parent is None:
            self.tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        item.setChildIndicatorPolicy(QTreeWidgetItem.DontShowIndicatorWhenChildless if kind == RowKind.VOLUME
                                     else QTreeWidgetItem.DontShowIndicator)
        return item

    def _volume_row(self, item: QTreeWidgetItem, source_id: int | None, parts: list[tuple[int | None, int]]) -> None:
        item.setData(0, SOURCE_ROLE, source_id)
        item.setData(0, PROGRESS_ROLE, self._progress(parts))
        self._set_cover(item)

    def _set_cover(self, item: QTreeWidgetItem) -> None:
        image = self._covers.cover(item.data(0, SOURCE_ROLE))
        if image is None:
            pixmap = QPixmap(style.VOLUME_COVER)
            pixmap.fill(style.PLACEHOLDER)
        else:
            pixmap = QPixmap.fromImage(image).scaled(style.VOLUME_COVER, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        item.setIcon(0, pixmap)

    def _container(self, item: QTreeWidgetItem, entry: int, start: int, end: int) -> None:
        item.setData(0, CONTAINER_ROLE, (entry, start, end))
        item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
        self._containers.append(item)

    @staticmethod
    def _row_key(item: QTreeWidgetItem) -> tuple:
        return item.data(0, KIND_ROLE), item.data(0, POSITION_ROLE), item.text(0)

    def _rebuild(self) -> None:
        # a rebuild (series scan finished, a mark added) keeps what the person had expanded
        expanded = {self._row_key(item) for item in self._items() if item.isExpanded()}
        self.tree.clear()
        self._containers = []
        tree = self._series
        if tree is None:
            return
        index = 0
        for node in tree.nodes:
            if node.folder is not None:
                top = self._row(RowKind.VOLUME, node.title, Position(index, 0))
                self._volume_row(top, node.entries[0].record_id, [(e.record_id, e.page_count) for e in node.entries])
                for entry in node.entries:
                    child = self._row(RowKind.CHAPTER, entry.title, Position(index, 0), top)
                    if index == self._entry_index:
                        self._container(child, index, 0, self._count)
                    index += 1
                continue
            entry = node.entries[0]
            title = f"🔒 {node.title}" if entry.locked else node.title
            if node.kind is Kind.VOLUME:
                top = self._row(RowKind.VOLUME, title, Position(index, 0))
                self._volume_row(top, entry.record_id, [(entry.record_id, entry.page_count)])
            else:
                top = self._row(RowKind.CHAPTER, title, Position(index, 0))
            top.setData(0, OVERRIDE_ROLE, index)
            current = index == self._entry_index
            if entry.chapters:
                end = self._count if current else entry.page_count
                spans = entry.chapters
                for k, span in enumerate(spans):
                    child = self._row(RowKind.CHAPTER, span.title, Position(index, span.start_page), top)
                    if current:
                        stop = spans[k + 1].start_page if k + 1 < len(spans) else end
                        self._container(child, index, span.start_page, stop)
            elif current:
                self._container(top, index, 0, self._count)
            index += 1
        for item in list(self._items()):
            if self._row_key(item) in expanded:
                item.setExpanded(True)
        self.set_current(self._current)

    def _populate(self, item: QTreeWidgetItem) -> None:
        _entry, start, end = item.data(0, CONTAINER_ROLE)
        for first in range(start, end, THUMBS_PER_ROW):
            row = self._row(RowKind.THUMBS, "", None, item)
            row.setData(0, PAGES_ROLE, list(range(first, min(first + THUMBS_PER_ROW, end))))
            row.setFlags(Qt.ItemIsEnabled)

    # -- current position ---------------------------------------------------------------------------------
    def _items(self, parent: QTreeWidgetItem | None = None):
        count = self.tree.topLevelItemCount() if parent is None else parent.childCount()
        for i in range(count):
            item = self.tree.topLevelItem(i) if parent is None else parent.child(i)
            yield item
            yield from self._items(item)

    def item(self, *titles: str) -> QTreeWidgetItem | None:
        found = None
        for title in titles:
            pool = ([self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())] if found is None
                    else [found.child(i) for i in range(found.childCount())])
            found = next((it for it in pool if it.text(0) == title), None)
            if found is None:
                return None
        return found

    def set_current(self, pos: Position) -> None:
        self._current = pos
        best = None
        for item in self._items():
            p = item.data(0, POSITION_ROLE)
            if item.data(0, KIND_ROLE) == RowKind.THUMBS or p is None:
                continue
            if p.entry == pos.entry and p.page <= pos.page and (best is None or p >= best[0]):
                best = (p, item)
        for item in self._items():
            if item.data(0, KIND_ROLE) != RowKind.THUMBS:
                font = QFont(item.font(0))
                font.setBold(best is not None and item is best[1])
                item.setFont(0, font)
        container = next((c for c in self._containers if c.data(0, CONTAINER_ROLE)[0] == pos.entry
                          and c.data(0, CONTAINER_ROLE)[1] <= pos.page < c.data(0, CONTAINER_ROLE)[2]), None)
        if container is not None:
            key = container.data(0, CONTAINER_ROLE)[:2]
            if key != self._auto_container:
                self._auto_container = key
                parent = container.parent()
                if parent is not None:
                    parent.setExpanded(True)
                container.setExpanded(True)
            row = next((container.child(i) for i in range(container.childCount())
                        if pos.page in (container.child(i).data(0, PAGES_ROLE) or [])), None)
            if row is not None and container.isExpanded():
                self.tree.scrollToItem(row)
        elif best is not None:
            self.tree.scrollToItem(best[1])
        self.tree.viewport().update()

    # -- interaction --------------------------------------------------------------------------------------
    def _on_expanded(self, item: QTreeWidgetItem) -> None:
        if item.data(0, CONTAINER_ROLE) is None:
            return
        if item.childCount() == 0:
            self._populate(item)
        if self._collapsing:
            return
        self._collapsing = True
        for other in self._containers:
            if other is not item and other.isExpanded():
                other.setExpanded(False)
        self._collapsing = False

    def _on_clicked(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        pos = item.data(0, POSITION_ROLE)
        if pos is not None:
            self.position_selected.emit(pos.entry, pos.page)

    def cell_rect(self, row_rect: QRect, slot: int) -> QRect:
        width = row_rect.width() // THUMBS_PER_ROW
        return QRect(row_rect.left() + slot * width, row_rect.top(), width, row_rect.height())

    def page_at(self, point) -> int | None:
        item = self.tree.itemAt(point)
        if item is None or item.data(0, KIND_ROLE) != RowKind.THUMBS:
            return None
        rect = self.tree.visualItemRect(item)
        pages = item.data(0, PAGES_ROLE)
        slot = (point.x() - rect.left()) // max(1, rect.width() // THUMBS_PER_ROW)
        return pages[slot] if 0 <= slot < len(pages) else None

    def thumb_rect(self, page: int) -> QRect | None:
        for container in self._containers:
            if not container.isExpanded():
                continue
            for i in range(container.childCount()):
                row = container.child(i)
                pages = row.data(0, PAGES_ROLE)
                if page in pages:
                    return self.cell_rect(self.tree.visualItemRect(row), pages.index(page))
        return None

    def page_menu(self, page: int) -> QMenu | None:
        if not self._markable:
            return None
        menu = QMenu(self)
        if page in self._marks:
            menu.addAction(self.tr("Изменить отметку…"), lambda: self.mark_edit_requested.emit(page))
            menu.addAction(self.tr("Удалить отметку"), lambda: self.mark_delete_requested.emit(page))
        else:
            menu.addAction(self.tr("Здесь начинается глава…"), lambda: self.mark_requested.emit(page))
        return menu

    def row_menu(self, item: QTreeWidgetItem) -> QMenu | None:
        index = item.data(0, OVERRIDE_ROLE)
        if index is None:
            return None
        menu = QMenu(self)
        for text, kind in ((self.tr("Это том"), Kind.VOLUME.value), (self.tr("Это глава"), Kind.CHAPTER.value),
                           (self.tr("Сбросить"), "")):
            menu.addAction(text, lambda k=kind: self.kind_override_requested.emit(index, k))
        return menu

    def _on_menu(self, point) -> None:
        page = self.page_at(point)
        if page is not None:
            menu = self.page_menu(page)
        else:
            item = self.tree.itemAt(point)
            menu = self.row_menu(item) if item is not None else None
        if menu is not None:
            menu.exec(self.tree.viewport().mapToGlobal(point))

    def _on_thumb(self, key: str, _page: int) -> None:
        if key == self._key:
            self.tree.viewport().update()

    def _on_cover(self, source_id: int) -> None:
        for item in self._items():
            if item.data(0, KIND_ROLE) == RowKind.VOLUME and item.data(0, SOURCE_ROLE) == source_id:
                self._set_cover(item)
