"""Left panel: the series tree (volumes → chapters) and page thumbnails."""
from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPixmap
from PySide6.QtWidgets import QListView, QMenu, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from mangareader.library.classify import SeriesTree
from mangareader.library.model import ChapterMark, Kind
from mangareader.render.loader import PageLoader
from mangareader.ui.reader.navigation import Position

POSITION_ROLE = Qt.UserRole
OVERRIDE_ROLE = Qt.UserRole + 1
THUMB_SIZE = QSize(120, 180)
GRID_SIZE = QSize(132, 208)


class ThumbnailModel(QAbstractListModel):
    def __init__(self, loader: PageLoader):
        super().__init__()
        self._loader = loader
        self._key: str | None = None
        self._count = 0
        self._marks: dict[int, ChapterMark] = {}
        self._icons: dict[int, QPixmap] = {}
        self._placeholder = QPixmap(THUMB_SIZE)
        self._placeholder.fill(QColor(60, 60, 60))
        loader.thumb_ready.connect(self._on_thumb)

    def set_source(self, key: str | None, count: int, marks: dict[int, ChapterMark]) -> None:
        self.beginResetModel()
        self._key, self._count, self._marks = key, count, dict(marks)
        self._icons = {}
        self.endResetModel()

    def set_marks(self, marks: dict[int, ChapterMark]) -> None:
        self._marks = dict(marks)
        if self._count:
            self.dataChanged.emit(self.index(0), self.index(self._count - 1), [Qt.DisplayRole])

    def marks(self) -> dict[int, ChapterMark]:
        return self._marks

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else self._count

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or self._key is None:
            return None
        page = index.row()
        if role == Qt.DisplayRole:
            mark = self._marks.get(page)
            return f"{page + 1} · Гл {mark.number}" if mark else f"{page + 1}"
        if role == Qt.DecorationRole:
            icon = self._icons.get(page)
            if icon is None:
                image = self._loader.thumbnail(self._key, page)
                if image is None:
                    return self._placeholder
                icon = QPixmap.fromImage(image.scaled(THUMB_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self._icons[page] = icon
            return icon
        return None

    def _on_thumb(self, key: str, page: int) -> None:
        if key == self._key and page < self._count:
            self._icons.pop(page, None)
            self.dataChanged.emit(self.index(page), self.index(page), [Qt.DecorationRole])


class Sidebar(QWidget):
    position_selected = Signal(int, int)
    mark_requested = Signal(int)
    mark_edit_requested = Signal(int)
    mark_delete_requested = Signal(int)
    kind_override_requested = Signal(int, str)

    def __init__(self, loader: PageLoader, parent=None):
        super().__init__(parent)
        self._entry_index = 0
        self._markable = False
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderHidden(True)
        self.tree_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_widget.itemClicked.connect(self._on_tree_clicked)
        self.tree_widget.customContextMenuRequested.connect(self._tree_menu)
        self.thumb_view = QListView()
        self.thumb_view.setViewMode(QListView.IconMode)
        self.thumb_view.setFlow(QListView.LeftToRight)
        self.thumb_view.setWrapping(True)
        self.thumb_view.setResizeMode(QListView.Adjust)
        self.thumb_view.setUniformItemSizes(True)
        self.thumb_view.setIconSize(THUMB_SIZE)
        self.thumb_view.setGridSize(GRID_SIZE)
        self.thumb_view.setMovement(QListView.Static)
        self.thumb_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.thumb_model = ThumbnailModel(loader)
        self.thumb_view.setModel(self.thumb_model)
        self.thumb_view.clicked.connect(lambda index: self.position_selected.emit(self._entry_index, index.row()))
        self.thumb_view.customContextMenuRequested.connect(self._thumb_menu)
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.tree_widget)
        split.addWidget(self.thumb_view)
        split.setSizes([300, 500])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(split)

    # -- tree ---------------------------------------------------------------------------------
    def set_tree(self, tree: SeriesTree | None) -> None:
        self.tree_widget.clear()
        if tree is None:
            return
        index = 0
        for node in tree.nodes:
            top = QTreeWidgetItem([node.title])
            top.setData(0, POSITION_ROLE, Position(index, 0))
            if node.folder is None and len(node.entries) == 1:
                top.setData(0, OVERRIDE_ROLE, index)
            if node.folder is not None:
                for entry in node.entries:
                    child = QTreeWidgetItem([entry.title])
                    child.setData(0, POSITION_ROLE, Position(index, 0))
                    top.addChild(child)
                    index += 1
            else:
                for span in node.entries[0].chapters:
                    child = QTreeWidgetItem([span.title])
                    child.setData(0, POSITION_ROLE, Position(index, span.start_page))
                    top.addChild(child)
                index += 1
            if node.entries and node.entries[0].locked:
                top.setText(0, f"🔒 {node.title}")
            self.tree_widget.addTopLevelItem(top)
        self.tree_widget.expandAll()

    def _items(self):
        for i in range(self.tree_widget.topLevelItemCount()):
            top = self.tree_widget.topLevelItem(i)
            yield top
            for j in range(top.childCount()):
                yield top.child(j)

    def set_current(self, pos: Position) -> None:
        self._entry_index = pos.entry
        best = None
        for item in self._items():
            p = item.data(0, POSITION_ROLE)
            if p is not None and p.entry == pos.entry and p.page <= pos.page and (best is None or p >= best[0]):
                best = (p, item)
        for item in self._items():
            font = QFont(item.font(0))
            font.setBold(best is not None and item is best[1])
            item.setFont(0, font)
        if best is not None:
            self.tree_widget.scrollToItem(best[1])
        if 0 <= pos.page < self.thumb_model.rowCount():
            self.thumb_view.setCurrentIndex(self.thumb_model.index(pos.page))

    def _on_tree_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        pos = item.data(0, POSITION_ROLE)
        if pos is not None:
            self.position_selected.emit(pos.entry, pos.page)

    def _tree_menu(self, point) -> None:
        item = self.tree_widget.itemAt(point)
        index = item.data(0, OVERRIDE_ROLE) if item else None
        if index is None:
            return
        menu = QMenu(self)
        for text, kind in ((self.tr("Это том"), Kind.VOLUME.value), (self.tr("Это глава"), Kind.CHAPTER.value),
                           (self.tr("Сбросить"), "")):
            menu.addAction(text, lambda k=kind: self.kind_override_requested.emit(index, k))
        menu.exec(self.tree_widget.viewport().mapToGlobal(point))

    # -- thumbnails -------------------------------------------------------------------------------
    def set_source(self, key: str | None, page_count: int, marks: dict[int, ChapterMark], markable: bool) -> None:
        self._markable = markable
        self.thumb_model.set_source(key, page_count, marks)

    def set_marks(self, marks: dict[int, ChapterMark]) -> None:
        self.thumb_model.set_marks(marks)

    def _thumb_menu(self, point) -> None:
        index = self.thumb_view.indexAt(point)
        if not index.isValid() or not self._markable:
            return
        page = index.row()
        menu = QMenu(self)
        if page in self.thumb_model.marks():
            menu.addAction(self.tr("Изменить отметку…"), lambda: self.mark_edit_requested.emit(page))
            menu.addAction(self.tr("Удалить отметку"), lambda: self.mark_delete_requested.emit(page))
        else:
            menu.addAction(self.tr("Здесь начинается глава…"), lambda: self.mark_requested.emit(page))
        menu.exec(self.thumb_view.viewport().mapToGlobal(point))
