"""The library screen: navigation on the left; search, the continue-reading row and the tile grid on the right."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt, QUrl, Signal
from PySide6.QtGui import QCursor, QDesktopServices
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QHBoxLayout, QLabel, QLineEdit, QMenu,
                               QPushButton, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from mangareader.library.catalog import (CatalogError, Section, SectionKind, SeriesCard, Sort, Status,
                                         continue_reading, filter_cards)
from mangareader.ui import icons, style
from mangareader.ui.dialogs import errors
from mangareader.ui.library import shelf_dialog
from mangareader.ui.library.continue_row import ContinueRow
from mangareader.ui.library.nav import LibraryNav
from mangareader.ui.library.tiles import TileDelegate, TileGrid, TileModel
from mangareader.ui.toast import Toast

UNAVAILABLE = "Серия недоступна: папка или файл не найдены"


def open_in_explorer(path: Path) -> None:
    folder = path if path.is_dir() else path.parent
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def _header(text: str) -> QLabel:
    label = QLabel(text)
    font = label.font()
    font.setBold(True)
    font.setPointSizeF(font.pointSizeF() * 0.85)
    label.setFont(font)
    label.setStyleSheet(f"color: {style.muted_color().name()};")
    return label


class LibraryPage(QWidget):
    open_series = Signal(int)
    open_file_requested = Signal()
    open_folder_requested = Signal()
    settings_requested = Signal()
    refresh_requested = Signal()

    def __init__(self, services, parent=None):
        super().__init__(parent)
        self.services = services
        self.catalog = services.catalog
        self._cards: list[SeriesCard] = []
        self._visible: list[SeriesCard] = []
        self._settings: QWidget | None = None

        self.nav = LibraryNav()
        self.nav.section_selected.connect(self._on_section)
        self.nav.settings_requested.connect(self.settings_requested)
        self.nav.add_shelf_requested.connect(self._add_shelf)
        self.nav.shelf_rename_requested.connect(lambda sid: self._edit_shelf(sid, self.tr("Переименовать полку")))
        self.nav.shelf_icon_requested.connect(lambda sid: self._edit_shelf(sid, self.tr("Сменить иконку")))
        self.nav.shelf_delete_requested.connect(self._delete_shelf)
        self.nav.series_dropped.connect(self._drop_on_shelf)

        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Поиск…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self._apply())
        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        group = QButtonGroup(self)
        self.status_buttons: dict[Status | None, QToolButton] = {}
        for status, text in ((None, self.tr("Все")), (Status.READING, self.tr("Читаю")),
                             (Status.NOT_STARTED, self.tr("Не начато")), (Status.FINISHED, self.tr("Прочитано"))):
            button = QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setChecked(status is None)
            button.clicked.connect(lambda _=False: self._apply())
            group.addButton(button)
            top.addWidget(button)
            self.status_buttons[status] = button
        self.sort_combo = QComboBox()
        for sort, text in ((Sort.RECENT, self.tr("Недавно открытые")), (Sort.TITLE, self.tr("По названию")),
                           (Sort.ADDED, self.tr("Недавно добавленные"))):
            self.sort_combo.addItem(text, sort)
        self.sort_combo.currentIndexChanged.connect(lambda _: self._apply())
        top.addWidget(self.sort_combo)
        self.refresh_button = QToolButton()
        self.refresh_button.setText("⟳")
        self.refresh_button.setToolTip(self.tr("Обновить"))
        self.refresh_button.clicked.connect(self.refresh_requested)
        top.addWidget(self.refresh_button)

        self.continue_header = _header(self.tr("ПРОДОЛЖИТЬ ЧТЕНИЕ"))
        self.continue_row = ContinueRow(services.covers)
        self.continue_row.open_series.connect(self.open_series)
        self.grid = TileGrid()
        self.model = TileModel(services.covers, self)
        self.grid.setModel(self.model)
        self.grid.setItemDelegate(TileDelegate(self.grid))
        self.grid.clicked.connect(self._on_tile_clicked)
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._on_tile_menu)

        self.empty_hint = QWidget()
        hint = QHBoxLayout(self.empty_hint)
        hint.addWidget(QLabel(self.tr("Добавьте папки с мангой в Настройках — библиотека заполнится сама")))
        settings_button = QPushButton(self.tr("Открыть настройки"))
        settings_button.clicked.connect(self.settings_requested)
        hint.addWidget(settings_button)
        hint.addStretch(1)

        tiles = QWidget()
        column = QVBoxLayout(tiles)
        column.addLayout(top)
        column.addWidget(self.continue_header)
        column.addWidget(self.continue_row)
        column.addWidget(_header(self.tr("БИБЛИОТЕКА")))
        column.addWidget(self.empty_hint)
        column.addWidget(self.grid, 1)
        self.content = QStackedWidget()
        self.content.addWidget(tiles)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.nav)
        layout.addWidget(self.content, 1)

    # -- content ----------------------------------------------------------------------------------------
    def reload(self) -> None:
        self._cards = self.catalog.cards()
        self.nav.set_data(self._cards, self.catalog.shelves())
        self._apply()

    def _status(self) -> Status | None:
        return next((s for s, b in self.status_buttons.items() if b.isChecked()), None)

    def _apply(self) -> None:
        section = self.nav.section()
        self._visible = filter_cards(self._cards, section, self.search.text(), self._status(),
                                     self.sort_combo.currentData())
        self.model.set_cards(self._visible)
        ongoing = continue_reading(self._cards) if section.kind is SectionKind.ALL else []
        self.continue_row.set_cards(ongoing)
        self.continue_header.setVisible(bool(ongoing))
        self.continue_row.setVisible(bool(ongoing))
        self.empty_hint.setVisible(not self._cards and not self.catalog.roots())

    def visible_cards(self) -> list[SeriesCard]:
        return list(self._visible)

    def show_tiles(self) -> None:
        self.content.setCurrentIndex(0)

    def set_settings_page(self, widget: QWidget) -> None:
        self._settings = widget
        self.content.addWidget(widget)

    def show_settings(self) -> None:
        if self._settings is not None:
            self.content.setCurrentWidget(self._settings)

    def set_scanning(self, on: bool) -> None:
        self.refresh_button.setEnabled(not on)
        self.refresh_button.setToolTip(self.tr("Идёт обновление…") if on else self.tr("Обновить"))

    def _on_section(self, _section: Section) -> None:
        self.show_tiles()
        self._apply()

    # -- tiles --------------------------------------------------------------------------------------------
    def open_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction(self.tr("Файл…"), self.open_file_requested)
        menu.addAction(self.tr("Папку…"), self.open_folder_requested)
        return menu

    def _on_tile_clicked(self, index: QModelIndex) -> None:
        if QApplication.keyboardModifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
            return                                           # selecting several tiles, e.g. to drag them to a shelf
        card = self.model.card_at(index.row())
        if card is None:
            self.open_menu().exec(QCursor.pos())
        elif not card.available:
            Toast.show_message(self, self.tr(UNAVAILABLE))
        else:
            self.open_series.emit(card.id)

    def _on_tile_menu(self, point) -> None:
        card = self.model.card_at(self.grid.indexAt(point).row())
        if card is not None:
            self.tile_menu(card.id).exec(self.grid.viewport().mapToGlobal(point))

    def _then_reload(self, fn):
        def run(*_args) -> None:
            fn()
            self.reload()
        return run

    def tile_menu(self, series_id: int) -> QMenu:
        card = self.catalog.card(series_id)
        menu = QMenu(self)
        if card is None:
            return menu
        cat = self.catalog
        if card.favorite:
            menu.addAction(self.tr("Убрать из избранного"),
                           self._then_reload(lambda: cat.set_favorite(series_id, False)))
        else:
            menu.addAction(self.tr("В избранное"), self._then_reload(lambda: cat.set_favorite(series_id, True)))
        shelves = cat.shelves()
        on_shelf = menu.addMenu(self.tr("На полку…"))
        for shelf in shelves:
            action = on_shelf.addAction(icons.icon(shelf.icon, style.SHELF_ICON, style.text_color()), shelf.name)
            action.setCheckable(True)
            action.setChecked(shelf.id in card.shelf_ids)
            action.triggered.connect(self._then_reload(
                lambda s=shelf.id, a=action: (cat.add_to_shelf if a.isChecked() else cat.remove_from_shelf)(
                    s, [series_id])))
        if shelves:
            on_shelf.addSeparator()
        on_shelf.addAction(self.tr("Новая полка…"), lambda: self._add_shelf([series_id]))
        section = self.nav.section()
        if section.kind is SectionKind.SHELF:
            name = next((s.name for s in shelves if s.id == section.value), "")
            menu.addAction(self.tr("Убрать с полки «{}»").format(name),
                           self._then_reload(lambda: cat.remove_from_shelf(section.value, [series_id])))
        if card.status is not Status.FINISHED:
            menu.addAction(self.tr("Отметить прочитанным"), self._then_reload(lambda: cat.mark_read(series_id)))
        if card.status is not Status.NOT_STARTED:
            menu.addAction(self.tr("Отметить непрочитанным"), self._then_reload(lambda: cat.mark_unread(series_id)))
        menu.addAction(self.tr("Показать в проводнике"), lambda: open_in_explorer(card.path))
        if card.root_id is None:
            menu.addSeparator()
            menu.addAction(self.tr("Убрать из библиотеки"), self._then_reload(lambda: cat.remove_series(series_id)))
        return menu

    # -- shelves ------------------------------------------------------------------------------------------
    def _add_shelf(self, series_ids: list[int] | None = None) -> None:
        answer = shelf_dialog.ask_shelf(self, self.catalog, title=self.tr("Новая полка"))
        if not answer:
            return
        try:
            shelf_id = self.catalog.add_shelf(*answer)
        except CatalogError as e:
            Toast.show_message(self, str(e))
            return
        if series_ids:
            self.catalog.add_to_shelf(shelf_id, series_ids)
        self.reload()

    def _edit_shelf(self, shelf_id: int, title: str) -> None:
        shelf = next((s for s in self.catalog.shelves() if s.id == shelf_id), None)
        if shelf is None:
            return
        answer = shelf_dialog.ask_shelf(self, self.catalog, title=title, name=shelf.name, icon=shelf.icon,
                                        shelf_id=shelf_id)
        if not answer:
            return
        try:
            self.catalog.rename_shelf(shelf_id, answer[0])
        except CatalogError as e:
            Toast.show_message(self, str(e))
            return
        self.catalog.set_shelf_icon(shelf_id, answer[1])
        self.reload()

    def _delete_shelf(self, shelf_id: int) -> None:
        shelf = next((s for s in self.catalog.shelves() if s.id == shelf_id), None)
        if shelf is None:
            return
        if errors.confirm(self, self.tr("Удалить полку «{}»? Серии останутся в библиотеке").format(shelf.name)):
            self.catalog.delete_shelf(shelf_id)
            self.reload()

    def _drop_on_shelf(self, shelf_id: int, series_ids: list) -> None:
        shelf = next((s for s in self.catalog.shelves() if s.id == shelf_id), None)
        if shelf is None:
            return
        self.catalog.add_to_shelf(shelf_id, series_ids)
        self.reload()
        Toast.show_message(self, self.tr("Добавлено на полку «{}»").format(shelf.name))
