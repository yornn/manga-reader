"""The left navigation of the library: All, Favourites, Formats, shelves and Settings."""
from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QMenu, QPushButton, QTreeWidget, QTreeWidgetItem, \
    QVBoxLayout, QWidget

from mangareader.library.catalog import Section, SectionKind, SeriesCard, Shelf, format_counts
from mangareader.ui import icons, style
from mangareader.ui.library.tiles import SERIES_MIME, series_ids_from_mime

SECTION_ROLE = Qt.UserRole
ACTION_ROLE = Qt.UserRole + 1
ADD_SHELF = "add_shelf"
FORMATS = "formats"


class _NavTree(QTreeWidget):
    series_dropped = Signal(int, list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setDropIndicatorShown(False)

    def _shelf_at(self, pos) -> int | None:
        item = self.itemAt(pos)
        section = item.data(0, SECTION_ROLE) if item else None
        return section.value if section is not None and section.kind is SectionKind.SHELF else None

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(SERIES_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(SERIES_MIME) and self._shelf_at(event.position().toPoint()) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        shelf = self._shelf_at(event.position().toPoint())
        ids = series_ids_from_mime(event.mimeData()) if event.mimeData().hasFormat(SERIES_MIME) else []
        if shelf is None or not ids:
            event.ignore()
            return
        event.acceptProposedAction()
        self.series_dropped.emit(shelf, ids)


class LibraryNav(QWidget):
    section_selected = Signal(object)
    add_shelf_requested = Signal()
    settings_requested = Signal()
    shelf_rename_requested = Signal(int)
    shelf_icon_requested = Signal(int)
    shelf_delete_requested = Signal(int)
    series_dropped = Signal(int, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._section = Section()
        self._formats_open = True
        self.tree = _NavTree()
        self.tree.setColumnCount(2)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(16)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.itemClicked.connect(self._on_clicked)
        self.tree.customContextMenuRequested.connect(self._on_menu)
        self.tree.series_dropped.connect(self.series_dropped)
        self.settings_button = QPushButton(self.tr("⚙ Настройки"))
        self.settings_button.setFlat(True)
        self.settings_button.clicked.connect(self.settings_requested)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.settings_button)
        self.setFixedWidth(style.NAV_WIDTH)

    # -- content ----------------------------------------------------------------------------------------
    def _item(self, text: str, count: int | None, section: Section | None = None,
              parent: QTreeWidgetItem | None = None) -> QTreeWidgetItem:
        item = QTreeWidgetItem([text, "" if count is None else str(count)])
        item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
        if section is not None:
            item.setData(0, SECTION_ROLE, section)
        else:
            item.setFlags(Qt.ItemIsEnabled)
        if parent is None:
            self.tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        return item

    def set_data(self, cards: Sequence[SeriesCard], shelves: Sequence[Shelf]) -> None:
        self.tree.clear()
        self._item(self.tr("▦ Все"), len(cards), Section())
        self._item(self.tr("★ Избранное"), sum(c.favorite for c in cards), Section(SectionKind.FAVORITES))
        formats = format_counts(cards)
        if formats:
            parent = self._item("", None)
            parent.setData(0, ACTION_ROLE, FORMATS)
            for fmt, n in formats:
                self._item(fmt, n, Section(SectionKind.FORMAT, fmt), parent)
            parent.setExpanded(self._formats_open)
            self._label_formats(parent)
        header = self._item(self.tr("МОИ ПОЛКИ"), None)
        font = QFont(header.font(0))
        font.setPointSizeF(font.pointSizeF() * 0.85)
        font.setBold(True)
        header.setFont(0, font)
        header.setForeground(0, style.muted_color())
        for shelf in shelves:
            count = sum(shelf.id in c.shelf_ids for c in cards)
            item = self._item(shelf.name, count, Section(SectionKind.SHELF, shelf.id))
            item.setIcon(0, icons.icon(shelf.icon, style.SHELF_ICON, style.text_color()))
        add = self._item(self.tr("＋ Добавить категорию"), None)
        add.setData(0, ACTION_ROLE, ADD_SHELF)
        item = self.item_for(self._section)
        if item is None:
            self._section = Section()
            item = self.item_for(self._section)
        self.tree.setCurrentItem(item)

    def _label_formats(self, item: QTreeWidgetItem) -> None:
        item.setText(0, ("▾ " if item.isExpanded() else "▸ ") + self.tr("Форматы"))

    def _items(self):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            yield top
            for j in range(top.childCount()):
                yield top.child(j)

    def item_for(self, section: Section) -> QTreeWidgetItem | None:
        return next((item for item in self._items() if item.data(0, SECTION_ROLE) == section), None)

    def section(self) -> Section:
        return self._section

    def select(self, section: Section) -> None:
        item = self.item_for(section) or self.item_for(Section())
        self._section = item.data(0, SECTION_ROLE)
        self.tree.setCurrentItem(item)
        self.section_selected.emit(self._section)

    # -- interaction ------------------------------------------------------------------------------------
    def _on_clicked(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        action = item.data(0, ACTION_ROLE)
        if action == ADD_SHELF:
            self.add_shelf_requested.emit()
        elif action == FORMATS:
            item.setExpanded(not item.isExpanded())
            self._formats_open = item.isExpanded()
            self._label_formats(item)
        elif item.data(0, SECTION_ROLE) is not None:
            self._section = item.data(0, SECTION_ROLE)
            self.section_selected.emit(self._section)

    def shelf_menu(self, shelf_id: int) -> QMenu:
        menu = QMenu(self)
        menu.addAction(self.tr("Переименовать…"), lambda: self.shelf_rename_requested.emit(shelf_id))
        menu.addAction(self.tr("Сменить иконку…"), lambda: self.shelf_icon_requested.emit(shelf_id))
        menu.addAction(self.tr("Удалить полку"), lambda: self.shelf_delete_requested.emit(shelf_id))
        return menu

    def _on_menu(self, point) -> None:
        item = self.tree.itemAt(point)
        section = item.data(0, SECTION_ROLE) if item else None
        if section is not None and section.kind is SectionKind.SHELF:
            self.shelf_menu(section.value).exec(self.tree.viewport().mapToGlobal(point))
