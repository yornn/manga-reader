"""The main window: the library page, the reader page (toolbar, panel, pages, slider), menus and hotkeys."""
from __future__ import annotations

import base64
import logging
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QRect, QRectF, QSize, Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMenu, QSizePolicy,
                               QSlider, QSplitter, QStackedWidget, QToolBar, QToolButton, QVBoxLayout, QWidget,
                               QWidgetAction)

from mangareader.logging_setup import LOG_NAME
from mangareader.settings import save_settings
from mangareader.sources.detect import OPENABLE_EXTS
from mangareader.library.classify import SeriesTree, suggest_chapter_number
from mangareader.library.library_scan import import_recent, record_tree, series_path_for
from mangareader.library.store import path_key
from mangareader.export import writer
from mangareader.export.encoders import EncodeOptions, OutFormat, Resize, encode_fragment, encode_page
from mangareader.export.model import load_page_image
from mangareader.export.naming import NameFields, render_name
from mangareader.export.writer import ExportError
from mangareader.library.model import Kind
from mangareader.ui.dialogs import chapter_mark_dialog, errors, hotkeys_dialog, page_dialog
from mangareader.ui.dialogs.save_dialog import SaveChoice, SaveDialog
from mangareader.ui.library.page import UNAVAILABLE, LibraryPage
from mangareader.ui.library.scan_runner import ScanRunner
from mangareader.ui.reader.controller import ReaderController, Services
from mangareader.ui.reader.layout import Direction, Mode
from mangareader.render.loader import pil_to_qimage
from mangareader.sources.base import SourceError
from mangareader.ui.reader.navigation import Position
from mangareader.ui.reader.selection import SelectionTool, pages_union, render_selection
from mangareader.ui.reader.nav_panel import NavPanel
from mangareader.ui.reader.reader_settings import ReaderSettingsPanel
from mangareader.ui.reader.view import MIN_BRIGHTNESS, PageView, ZoomMode
from mangareader.ui import style
from mangareader.ui.settings_page import SettingsPage
from mangareader.ui.toast import Toast

APP_TITLE = "Manga Reader"
log = logging.getLogger("mangareader.ui")


class ElidedLabel(QLabel):
    """A label that takes the free toolbar width and shortens its text with "…" instead of crowding."""

    def __init__(self):
        super().__init__()
        self._full = ""
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._elide()

    def minimumSizeHint(self) -> QSize:
        return QSize(60, super().minimumSizeHint().height())

    def sizeHint(self) -> QSize:
        return QSize(self.fontMetrics().horizontalAdvance(self._full) + 8, super().sizeHint().height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        self.setText(self.fontMetrics().elidedText(self._full, Qt.ElideMiddle, max(0, self.width() - 4)))


class _Pages(QStackedWidget):
    """Only the page on screen sets the window's minimum size: reading must fit half a laptop screen."""

    def __init__(self):
        super().__init__()
        self.currentChanged.connect(lambda _: self.updateGeometry())

    def minimumSizeHint(self) -> QSize:
        page = self.currentWidget()
        return page.minimumSizeHint() if page is not None else super().minimumSizeHint()

    def sizeHint(self) -> QSize:
        page = self.currentWidget()
        return page.sizeHint() if page is not None else super().sizeHint()


@contextmanager
def _wait_cursor():
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        yield
    finally:
        QApplication.restoreOverrideCursor()


class MainWindow(QMainWindow):
    def __init__(self, services: Services):
        super().__init__()
        self.services = services
        self.setWindowTitle(APP_TITLE)
        self.setAcceptDrops(True)
        self.view = PageView(services.loader)
        self.controller = ReaderController(services, self.view, self)
        self.selection = SelectionTool(self.view)
        self.selection.save_requested.connect(self.save_current)
        self.controller.password_provider = lambda path, wrong: errors.ask_password(self, path.name, wrong)
        self.controller.state_changed.connect(self._refresh_labels)
        self.controller.source_changed.connect(lambda title: Toast.show_message(self, title))
        self.controller.error.connect(self._show_error)
        self.controller.source_opened.connect(self._on_source_opened)
        self.controller.tree_changed.connect(self._on_tree_changed)
        self.controller.state_changed.connect(self._touch)
        self.controller.tree_scanned.connect(self._record_tree)
        self._slider_busy = False
        self._fallback_warned = False
        self._series_id: int | None = None
        self._series_path: Path | None = None
        self._reader_actions: list[QAction] = []
        self._focus = False
        self._nav_was_shown = True
        self.scanner = ScanRunner(services, self)
        if not services.settings.recent_imported:
            # files opened before the library existed become series once
            import_recent(services.catalog, services.settings.recent)
            services.settings.recent_imported = True
            try:
                save_settings(services.settings, services.data.settings_file)
            except OSError:
                pass
        self._build_ui()
        self._build_actions()
        self._build_library()
        self._show_library()
        if services.settings.window_geometry:
            self.restoreGeometry(QByteArray(base64.b64decode(services.settings.window_geometry)))
        if services.catalog.roots():
            QTimer.singleShot(0, self.scanner.start)

    # -- layout ---------------------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.toolbar = QToolBar(self.tr("Панель"))
        self.toolbar.setMovable(False)
        self.home_button = QToolButton()
        self.home_button.setText(self.tr("⌂ Главная"))
        self.home_button.setToolTip(self.tr("Главная (Backspace)"))
        self.home_button.clicked.connect(self.go_home)
        self.toolbar.addWidget(self.home_button)
        self.focus_button = QToolButton()
        self.focus_button.setText("◧")
        self.focus_button.setToolTip(self.tr("Только страница: спрятать панели (вернуть — эта кнопка или Esc)"))
        self.focus_button.clicked.connect(lambda: self.set_focus_mode(not self._focus))
        self.toolbar.addWidget(self.focus_button)
        self.toolbar.addSeparator()
        self.crumb_label = ElidedLabel()
        self.toolbar.addWidget(self.crumb_label)
        self.prev_chapter_button = QToolButton()
        self.prev_chapter_button.setText(self.tr("‹ Глава"))
        self.prev_chapter_button.setToolTip(self.tr("Предыдущая глава (Ctrl+PgUp)"))
        self.prev_chapter_button.clicked.connect(lambda: self.controller.prev_chapter())
        self.page_label = QToolButton()
        self.page_label.setAutoRaise(True)
        self.page_label.setToolTip(self.tr("Перейти к странице (Ctrl+G)"))
        self.page_label.clicked.connect(self._go_to_page)
        self.next_chapter_button = QToolButton()
        self.next_chapter_button.setText(self.tr("Глава ›"))
        self.next_chapter_button.setToolTip(self.tr("Следующая глава (Ctrl+PgDn)"))
        self.next_chapter_button.clicked.connect(lambda: self.controller.next_chapter())
        for widget in (self.prev_chapter_button, self.page_label, self.next_chapter_button):
            self.toolbar.addWidget(widget)
        services = self.services
        self.nav_panel = NavPanel(services.loader, services.covers, services.store)
        self.nav_panel.position_selected.connect(lambda e, p: self.controller.go_to(Position(e, p)))
        self.nav_panel.mark_requested.connect(self._add_mark)
        self.nav_panel.mark_edit_requested.connect(self._edit_mark)
        self.nav_panel.mark_delete_requested.connect(self.controller.delete_chapter_mark)
        self.nav_panel.kind_override_requested.connect(
            lambda index, kind: self.controller.set_kind_override(index, Kind(kind) if kind else None))
        self.nav_panel.setVisible(services.settings.sidebar_visible)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.nav_panel)
        self.splitter.addWidget(self.view)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([style.READER_NAV_WIDTH, 1000])
        self.view.viewport().setMouseTracking(True)       # the page-only mode watches for the top edge
        self.view.viewport().installEventFilter(self)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.valueChanged.connect(self._on_slider)
        self.reader_page = QWidget()
        layout = QVBoxLayout(self.reader_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.splitter, 1)
        self.bottom_bar = QHBoxLayout()
        self.bottom_bar.setContentsMargins(0, 0, 0, 0)
        self.bottom_bar.addWidget(self.slider, 1)
        layout.addLayout(self.bottom_bar)
        self.library_page = LibraryPage(self.services)
        self.settings_page = SettingsPage(self.services)
        self.library_page.set_settings_page(self.settings_page)
        self.pages = _Pages()
        self.pages.addWidget(self.library_page)
        self.pages.addWidget(self.reader_page)
        self.setCentralWidget(self.pages)

    def _build_library(self) -> None:
        page, scanner = self.library_page, self.scanner
        page.open_series.connect(self.open_series)
        page.open_file_requested.connect(self._open_file_dialog)
        page.open_folder_requested.connect(self._open_folder_dialog)
        page.settings_requested.connect(self.show_settings)
        page.refresh_requested.connect(scanner.start)
        self.settings_page.roots_changed.connect(self._on_roots_changed)
        self.settings_page.rescan_requested.connect(scanner.start)
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(300)
        self._reload_timer.timeout.connect(page.reload)
        scanner.started.connect(lambda: page.set_scanning(True))
        scanner.series_updated.connect(self._reload_timer.start)
        scanner.finished.connect(self._on_scan_finished)
        page.reload()

    def _action(self, text: str, slot, shortcut, reader: bool = True) -> QAction:
        """A hotkey of the window; reader ones work only while the reader is shown."""
        action = QAction(text, self)
        if reader:
            self._reader_actions.append(action)
        shortcuts = shortcut if isinstance(shortcut, list) else [shortcut]
        action.setShortcuts([QKeySequence(s) for s in shortcuts])
        action.setShortcutContext(Qt.WindowShortcut)
        action.triggered.connect(slot)
        self.addAction(action)
        return action

    def _build_actions(self) -> None:
        # no menu bar: every action is a hotkey, listed in the hotkey sheet behind the reader's gear
        c = self.controller
        self._action(self.tr("Открыть файл…"), self._open_file_dialog, "Ctrl+O", reader=False)
        self._action(self.tr("Открыть папку…"), self._open_folder_dialog, "Ctrl+Shift+O", reader=False)
        self._action(self.tr("Полный экран"), self._toggle_fullscreen, "F11", reader=False)
        self._action(self.tr("Главная"), self.go_home, "Backspace")
        for key, mode in (("1", Mode.SINGLE), ("2", Mode.SPREAD), ("3", Mode.RIBBON), ("4", Mode.HRIBBON)):
            self._action(mode.value, lambda _=False, m=mode: self._set_mode(m), key)
        for key, zoom in (("W", ZoomMode.FIT_WIDTH), ("H", ZoomMode.FIT_HEIGHT), ("F", ZoomMode.FIT_WINDOW),
                          ("Z", ZoomMode.ACTUAL)):
            self._action(zoom.value, lambda _=False, z=zoom: self.view.set_zoom_mode(z), key)
        self._action(self.tr("Сменить направление чтения"), c.toggle_direction, "D")
        self._action(self.tr("Сдвиг разворота"), c.toggle_spread_offset, "O")
        self._action(self.tr("Показать или скрыть панель"), self._toggle_sidebar, "Tab")
        self._action(self.tr("Влево"), lambda: self._arrow(left=True), "Left")
        self._action(self.tr("Вправо"), lambda: self._arrow(left=False), "Right")
        self._action(self.tr("Вперёд"), lambda: self._space(True), "Space")
        self._action(self.tr("Назад"), lambda: self._space(False), "Shift+Space")
        self._action(self.tr("Следующая страница"), c.next, "PgDown")
        self._action(self.tr("Предыдущая страница"), c.prev, "PgUp")
        self._action(self.tr("Первая страница"), c.first_page, "Home")
        self._action(self.tr("Последняя страница"), c.last_page, "End")
        self._action(self.tr("Следующая глава"), c.next_chapter, "Ctrl+PgDown")
        self._action(self.tr("Предыдущая глава"), c.prev_chapter, "Ctrl+PgUp")
        self._action(self.tr("Перейти к странице"), self._go_to_page, "Ctrl+G")
        self._action(self.tr("Отмена"), self._escape, "Esc")
        self.snip_action = self._action(self.tr("Ножницы"), self.selection.toggle, "S")
        self._action(self.tr("Копировать"), self.copy_to_clipboard, "Ctrl+C")
        self._action(self.tr("Сохранить…"), lambda: self.save_current(), "Ctrl+S")
        self._action(self.tr("Быстрое сохранение"), lambda: self.save_current(quick=True), "Ctrl+Shift+S")
        self._action(self.tr("Сохранить выделение"), self._enter, ["Return", "Enter"])

        bar = self.toolbar
        bar.addSeparator()
        snip_button = QToolButton()
        snip_button.setText("✂")
        snip_button.setToolTip(self.tr("Ножницы (S)"))
        snip_button.clicked.connect(self.selection.toggle)
        bar.addWidget(snip_button)
        save_button = QToolButton()
        save_button.setText("💾")
        save_button.setToolTip(self.tr("Сохранить (Ctrl+S)"))
        save_button.clicked.connect(lambda: self.save_current())
        bar.addWidget(save_button)
        self._build_gear()

    def _build_gear(self) -> None:
        panel = self.reader_settings = ReaderSettingsPanel()
        c = self.controller
        panel.mode_chosen.connect(lambda mode: self._set_mode(Mode(mode)))
        panel.zoom_chosen.connect(lambda zoom: self.view.set_zoom_mode(ZoomMode(zoom)))
        panel.direction_chosen.connect(
            lambda d: c.toggle_direction() if Direction(d) is not c.direction else None)
        panel.spread_offset_toggled.connect(c.toggle_spread_offset)
        panel.brightness_changed.connect(self._set_brightness)
        panel.hotkeys_requested.connect(self._show_hotkeys)
        self.font_slider = panel.font_slider
        self._font_timer = QTimer(self)
        self._font_timer.setSingleShot(True)
        self._font_timer.setInterval(300)
        self._font_timer.timeout.connect(lambda: self.controller.set_font_size(self.font_slider.value()))
        panel.font_size_changed.connect(lambda _: self._font_timer.start())
        menu = QMenu(self)
        holder = QWidgetAction(menu)
        holder.setDefaultWidget(panel)
        menu.addAction(holder)
        menu.aboutToShow.connect(self._sync_reader_settings)
        self.gear_button = QToolButton()
        self.gear_button.setText("⚙")
        self.gear_button.setToolTip(self.tr("Настройки чтения"))
        self.gear_button.setMenu(menu)
        self.gear_button.setPopupMode(QToolButton.InstantPopup)
        self.toolbar.addWidget(self.gear_button)
        self.view.set_brightness(self.services.settings.brightness)
        self._sync_reader_settings()

    def _sync_reader_settings(self) -> None:
        c = self.controller
        self.reader_settings.sync(c.mode, self.view.zoom_mode, c.direction,
                                  bool(c.record and c.record.spread_offset), self.services.settings.brightness,
                                  self.services.settings.book_font_size,
                                  bool(c.source and c.source.is_reflowable))

    def _set_mode(self, mode: Mode) -> None:
        self.controller.set_mode(mode)
        self._sync_reader_settings()

    def _set_brightness(self, percent: int) -> None:
        settings = self.services.settings
        settings.brightness = max(MIN_BRIGHTNESS, min(100, percent))
        self.view.set_brightness(settings.brightness)
        save_settings(settings, self.services.data.settings_file)

    def _go_to_page(self) -> None:
        c = self.controller
        if c.source is None:
            return
        number = page_dialog.ask_page(self, c.series_page(), c.series_page_count())
        if number is not None:
            c.go_to_series_page(number)

    def _show_hotkeys(self) -> None:
        self.gear_button.menu().close()
        hotkeys_dialog.show_hotkeys(self)

    # -- pages ---------------------------------------------------------------------------------------
    def is_library_shown(self) -> bool:
        return self.pages.currentWidget() is self.library_page

    def _set_reader_actions(self, enabled: bool) -> None:
        for action in self._reader_actions:
            action.setEnabled(enabled)

    def _show_library(self) -> None:
        self.pages.setCurrentWidget(self.library_page)
        self._set_reader_actions(False)
        self.setWindowTitle(APP_TITLE)

    def _show_reader(self) -> None:
        self.pages.setCurrentWidget(self.reader_page)
        self._set_reader_actions(True)
        self.view.setFocus()

    def go_home(self) -> None:
        if self.selection.active:
            self.selection.deactivate()
        self.set_focus_mode(False)
        self.controller.close_source()
        self._series_id = None
        self._series_path = None
        self._show_library()
        self.library_page.show_tiles()
        self.library_page.reload()
        self.library_page.grid.setFocus()

    def show_settings(self) -> None:
        if not self.is_library_shown():
            self.go_home()
        self.settings_page.refresh(self.scanner.failed)
        self.library_page.show_settings()

    def _on_roots_changed(self) -> None:
        self.library_page.reload()
        self.scanner.start()

    def _on_scan_finished(self) -> None:
        self.library_page.set_scanning(self.scanner.running)
        self.library_page.reload()
        self.settings_page.refresh(self.scanner.failed)

    # -- opening ------------------------------------------------------------------------------------
    def open_paths(self, paths) -> bool:
        paths = [Path(p) for p in paths]
        if not paths:
            return False
        path = paths[0]
        roots = self.services.catalog.roots()
        if any(path_key(path) == path_key(root.path) for root in roots):
            Toast.show_message(self, self.tr("Это папка библиотеки — её серии уже на главной"))
            return False
        series, root_id = series_path_for(path, roots)
        return self._open(path, series, root_id=root_id)

    def open_series(self, series_id: int) -> bool:
        card = self.services.catalog.card(series_id)
        if card is None:
            return False
        if not card.available:
            Toast.show_message(self, self.tr(UNAVAILABLE))
            return False
        return self._open(card.path, card.path, series_id=card.id)

    def _open(self, path: Path, series: Path, *, root_id: int | None = None, series_id: int | None = None) -> bool:
        previous = self._series_id, self._series_path
        from_library = self.is_library_shown()
        self._series_id = None                       # the old series must not get the new file's position
        # a hidden stacked page keeps a stale size: show the reader first, so a book is laid out for the real view
        self.pages.setCurrentWidget(self.reader_page)
        if not self.controller.open_path(path, series=series):
            self._series_id, self._series_path = previous
            if from_library:
                self.pages.setCurrentWidget(self.library_page)
            return False
        catalog = self.services.catalog
        self._series_id = series_id if series_id is not None else catalog.ensure_series(series, root_id)
        self._series_path = series
        if self.controller.tree is not None:
            self._record_tree(self.controller.tree)
        self._touch()
        self._show_reader()
        save_settings(self.services.settings, self.services.data.settings_file)
        return True

    def _touch(self) -> None:
        c = self.controller
        if self._series_id is not None and c.record is not None and c.source is not None:
            self.services.catalog.touch(self._series_id, c.record.id, c.where_parts())

    def _record_tree(self, tree: SeriesTree) -> None:
        if self._series_id is not None and self._series_path is not None and path_key(tree.root) == path_key(
                self._series_path):
            record_tree(self.services.catalog, self._series_id, tree)

    def _open_file_dialog(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in sorted(OPENABLE_EXTS))
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Открыть файл"), "",
                                              self.tr("Манга и книги") + f" ({patterns})")
        if path:
            self.open_paths([path])

    def _open_folder_dialog(self) -> None:
        path = QFileDialog.getExistingDirectory(self, self.tr("Открыть папку"))
        if path:
            self.open_paths([path])

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.open_paths(paths)

    # -- navigation helpers ----------------------------------------------------------------------
    def _arrow(self, left: bool) -> None:
        forward = left == (self.controller.direction is Direction.RTL)
        self.controller.next() if forward else self.controller.prev()

    def _space(self, forward: bool) -> None:
        bar = self.view.verticalScrollBar()
        step = int(self.view.viewport().height() * 0.9)
        if forward and bar.value() < bar.maximum():
            bar.setValue(bar.value() + step)
        elif not forward and bar.value() > bar.minimum():
            bar.setValue(bar.value() - step)
        else:
            self.controller.next() if forward else self.controller.prev()

    def _on_slider(self, value: int) -> None:
        if not self._slider_busy:
            self.controller.go_to(Position(self.controller.entry_index, value))

    def _toggle_sidebar(self) -> None:
        visible = not self.nav_panel.isVisible()
        self.nav_panel.setVisible(visible)
        self.services.settings.sidebar_visible = visible

    # -- navigation panel -----------------------------------------------------------------------------------
    def _on_source_opened(self) -> None:
        c = self.controller
        self._sync_reader_settings()
        self.nav_panel.set_tree(c.display_tree())
        self.nav_panel.set_source(c.source_key, c.entry_index, len(c.source.pages), c.marks(), c.markable())

    def _on_tree_changed(self) -> None:
        c = self.controller
        self.nav_panel.set_marks(c.marks())
        if c.source is not None:
            self.nav_panel.set_source(c.source_key, c.entry_index, len(c.source.pages), c.marks(), c.markable())
        self.nav_panel.set_tree(c.display_tree())
        self.nav_panel.set_current(c.position)

    def _add_mark(self, page: int) -> None:
        entry = self.controller.entry
        number = suggest_chapter_number(entry.chapters if entry else [], page)
        answer = chapter_mark_dialog.ask_chapter_mark(self, number)
        if answer:
            self.controller.add_chapter_mark(page, *answer)

    def _edit_mark(self, page: int) -> None:
        mark = self.controller.marks().get(page)
        if mark is None:
            return
        answer = chapter_mark_dialog.ask_chapter_mark(self, mark.number, mark.title)
        if answer:
            self.controller.add_chapter_mark(page, *answer)

    def _escape(self) -> None:
        if self.selection.active:
            self.selection.deactivate()
        elif self._focus:
            self.set_focus_mode(False)
        else:
            self._leave_fullscreen()

    # -- page-only mode ---------------------------------------------------------------------------------
    @property
    def focus_mode(self) -> bool:
        return self._focus

    def set_focus_mode(self, on: bool) -> None:
        """Hide the panel, the top bar and the slider; the bar floats back over the page at the top edge."""
        if on == self._focus:
            return
        self._focus = on
        layout = self.reader_page.layout()
        if on:
            self._nav_was_shown = not self.nav_panel.isHidden()
            self.nav_panel.hide()
            self.slider.hide()
            layout.removeWidget(self.toolbar)
            self.toolbar.hide()
        else:
            layout.insertWidget(0, self.toolbar)
            self.toolbar.show()
            self.slider.show()
            self.nav_panel.setVisible(self._nav_was_shown)

    def eventFilter(self, watched, event) -> bool:
        if self._focus and watched is self.view.viewport() and event.type() == QEvent.MouseMove:
            y = event.position().y()
            if y < style.FOCUS_EDGE and self.toolbar.isHidden():
                height = self.toolbar.sizeHint().height()
                self.toolbar.setGeometry(QRect(0, 0, self.reader_page.width(), height))
                self.toolbar.show()
                self.toolbar.raise_()
            elif y > self.toolbar.height() + style.FOCUS_EDGE * 2 and not self.toolbar.isHidden():
                self.toolbar.hide()
        return super().eventFilter(watched, event)

    def _enter(self) -> None:
        if self.selection.active and self.selection.rect() is not None:
            self.selection.save_requested.emit()

    # -- snipping ------------------------------------------------------------------------------------
    def _target_placed(self):
        # without a selection, save/copy applies to the shown group (or the focused ribbon page)
        placed = self.view.placed()
        return [p for p in placed if p.page in self.controller.current_group] or placed

    def _render_target(self):
        rect = self.selection.rect() if self.selection.active else None
        if rect is None:
            rect = pages_union(self._target_placed())
        with _wait_cursor():
            return render_selection(self.controller.source, self.view.placed(), rect)

    def copy_to_clipboard(self) -> None:
        if self.controller.source is None:
            return
        try:
            image, _ = self._render_target()
        except SourceError as e:
            self._show_error(str(e))
            return
        except Exception:
            log.exception("copy failed")
            self._show_error(self.tr("Не удалось скопировать: непредвиденная ошибка"))
            return
        QGuiApplication.clipboard().setImage(pil_to_qimage(image))
        Toast.show_message(self, self.tr("Скопировано в буфер обмена"))

    # -- saving ------------------------------------------------------------------------------------------
    def default_name_fields(self, page: int | None = None) -> NameFields:
        c = self.controller
        page = c.page if page is None else page
        entry = c.entry
        tree = c.display_tree()
        node = next((n for n in (tree.nodes if tree else []) if entry in n.entries), None)
        volume = node.number if node is not None and node.kind is Kind.VOLUME else None
        chapter = None
        if entry is not None and entry.chapters:
            before = [span for span in entry.chapters if span.start_page <= page]
            chapter = before[-1].number if before else None
        elif entry is not None and entry.kind is Kind.CHAPTER:
            chapter = entry.number
        ref = c.source.pages[page]
        file = Path(ref.inner_path).stem if c.source.kind == "images" else None
        series = tree.title if tree else ""
        return NameFields(series, volume, chapter, page + 1, len(c.source.pages), file)

    def _choose(self, quick: bool, *, default_name: str, is_spread: bool, is_fragment: bool, jpeg_source: bool,
                estimate) -> SaveChoice | None:
        prefs = self.services.settings.export
        if quick and prefs.folder:
            options = EncodeOptions(OutFormat(prefs.fmt), prefs.quality, Resize(prefs.resize_mode, prefs.resize_value))
            return SaveChoice(options, prefs.spread_layout, Path(prefs.folder), default_name)
        dialog = SaveDialog(self, prefs, default_name=default_name, is_spread=is_spread, is_fragment=is_fragment,
                            jpeg_source=jpeg_source, estimate=estimate)
        if not dialog.exec():
            return None
        dialog.store_into(prefs)
        return dialog.choice()

    def save_current(self, quick: bool = False) -> list[Path]:
        try:
            return self._save_current(quick)
        except (ExportError, SourceError) as e:
            errors.show_error(self, str(e), self.services.data.logs / LOG_NAME)
        except Exception:
            log.exception("saving failed")
            errors.show_error(self, self.tr("Не удалось сохранить: непредвиденная ошибка"),
                              self.services.data.logs / LOG_NAME)
        return []

    def _save_current(self, quick: bool) -> list[Path]:
        c = self.controller
        if c.source is None:
            return []
        prefs = self.services.settings.export
        fragment = self.selection.active and self.selection.rect() is not None
        group = list(c.current_group)
        is_spread = not fragment and len(group) > 1
        default_name = render_name(prefs.template, self.default_name_fields(group[0] if group else c.page))
        if fragment:
            pages = [p.page for p in self.view.placed() if
                     QRectF(p.x, p.y, p.w, p.h).intersects(self.selection.rect())]
        else:
            pages = group
        jpeg_source = all(c.source.pages[p].ext in (".jpg", ".jpeg") for p in pages) if pages else False
        with _wait_cursor():
            if fragment or is_spread:
                image, sources = self._render_target()
                estimate = lambda o: len(encode_fragment(image, sources, o).data)  # noqa: E731
            else:
                page_image = load_page_image(c.source, group[0])
                estimate = lambda o: len(encode_page(page_image, o).data)  # noqa: E731
        choice = self._choose(quick, default_name=default_name, is_spread=is_spread, is_fragment=fragment,
                              jpeg_source=jpeg_source, estimate=estimate)
        if choice is None:
            return []
        with _wait_cursor():
            if fragment or (is_spread and choice.spread_layout == "stitched"):
                outputs = [(choice.filename, encode_fragment(image, sources, choice.options))]
            elif is_spread:
                outputs = [(render_name(prefs.template, self.default_name_fields(p)),
                            encode_page(load_page_image(c.source, p), choice.options)) for p in group]
            else:
                outputs = [(choice.filename, encode_page(page_image, choice.options))]
            written = []
            for name, encoded in outputs:
                path = writer.unique_path(choice.folder, name, encoded.ext)
                writer.write_atomic(path, encoded.data)
                written.append(path)
        save_settings(self.services.settings, self.services.data.settings_file)
        folder = choice.folder
        Toast.show_message(self, self.tr("Сохранено: ") + ", ".join(p.name for p in written),
                           (self.tr("Открыть папку"), lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))))
        if fragment:
            self.selection.deactivate()
        return written

    def _toggle_fullscreen(self) -> None:
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def _leave_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()

    # -- labels ---------------------------------------------------------------------------------------
    def page_label_text(self) -> str:
        return self.controller.page_label()

    def breadcrumb_text(self) -> str:
        return " › ".join(self.controller.breadcrumb())

    def _refresh_labels(self) -> None:
        c = self.controller
        self.crumb_label.set_full_text(self.breadcrumb_text())
        self.page_label.setText(self.page_label_text())
        series = c.tree.title if c.tree else (c.series_root.name if c.series_root else "")
        self.setWindowTitle(f"{APP_TITLE} — {series}" if series else APP_TITLE)
        self._slider_busy = True
        total = len(c.source.pages) if c.source else 1
        self.slider.setMaximum(max(0, total - 1))
        self.slider.setInvertedAppearance(c.direction is Direction.RTL)
        self.slider.setValue(c.page)
        self._slider_busy = False
        self.nav_panel.set_current(c.position)

    def _show_error(self, message: str) -> None:
        errors.show_error(self, message, self.services.data.logs / LOG_NAME)

    # -- lifecycle --------------------------------------------------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.services.data.is_fallback and not self._fallback_warned:
            self._fallback_warned = True
            Toast.show_message(self, self.tr("Рядом с программой нельзя сохранять данные, поэтому они хранятся в: ")
                               + str(self.services.data.root), ms=8000)

    def closeEvent(self, event) -> None:
        settings = self.services.settings
        settings.window_geometry = base64.b64encode(bytes(self.saveGeometry())).decode("ascii")
        try:
            save_settings(settings, self.services.data.settings_file)
        except OSError:
            pass
        self.scanner.stop()
        self.scanner.blockSignals(True)           # a scan finishing now must not reload from the closed store
        self._reload_timer.stop()
        self.controller.close_source()
        self.controller.blockSignals(True)        # a series scan finishing now must not touch the closed store
        QThreadPool.globalInstance().waitForDone(5000)
        self.services.shutdown()
        super().closeEvent(event)
