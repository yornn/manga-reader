"""The main window: toolbar, page area, page slider, menus and hotkeys."""
from __future__ import annotations

import base64
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QThreadPool
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QLabel, QMainWindow, QMenu, QSizePolicy, QSlider,
                               QSplitter, QToolBar, QToolButton, QVBoxLayout, QWidget)

from mangareader.logging_setup import LOG_NAME
from mangareader.settings import save_settings
from mangareader.sources.detect import OPENABLE_EXTS
from mangareader.ui.dialogs import errors
from mangareader.ui.dialogs.settings_dialog import SettingsDialog
from mangareader.ui.reader.controller import ReaderController, Services
from mangareader.ui.reader.layout import Direction, Mode
from mangareader.ui.reader.navigation import Position
from mangareader.ui.reader.view import PageView, ZoomMode
from mangareader.ui.theme import apply_theme
from mangareader.ui.toast import Toast

APP_TITLE = "Manga Reader"


class MainWindow(QMainWindow):
    def __init__(self, services: Services):
        super().__init__()
        self.services = services
        self.setWindowTitle(APP_TITLE)
        self.setAcceptDrops(True)
        self.view = PageView(services.loader)
        self.controller = ReaderController(services, self.view, self)
        self.controller.password_provider = lambda path, wrong: errors.ask_password(self, path.name, wrong)
        self.controller.state_changed.connect(self._refresh_labels)
        self.controller.source_changed.connect(lambda title: Toast.show_message(self, title))
        self.controller.error.connect(self._show_error)
        self._slider_busy = False
        self._fallback_warned = False
        self._build_ui()
        self._build_actions()
        if services.settings.window_geometry:
            self.restoreGeometry(QByteArray(base64.b64decode(services.settings.window_geometry)))

    # -- layout ---------------------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.toolbar = QToolBar(self.tr("Панель"))
        self.toolbar.setMovable(False)
        self.addToolBar(self.toolbar)
        self.crumb_label = QLabel()
        self.crumb_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.page_label = QLabel()
        self.toolbar.addWidget(self.crumb_label)
        self.toolbar.addWidget(self.page_label)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.view)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.valueChanged.connect(self._on_slider)
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.splitter, 1)
        layout.addWidget(self.slider)
        self.setCentralWidget(central)

    def _action(self, text: str, slot, shortcut=None, menu: QMenu | None = None, checkable=False) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            shortcuts = shortcut if isinstance(shortcut, list) else [shortcut]
            action.setShortcuts([QKeySequence(s) for s in shortcuts])
            action.setShortcutContext(Qt.WindowShortcut)
        action.setCheckable(checkable)
        action.triggered.connect(slot)
        self.addAction(action)
        if menu is not None:
            menu.addAction(action)
        return action

    def _build_actions(self) -> None:
        c = self.controller
        file_menu = self.menuBar().addMenu(self.tr("Файл"))
        self._action(self.tr("Открыть файл…"), self._open_file_dialog, "Ctrl+O", file_menu)
        self._action(self.tr("Открыть папку…"), self._open_folder_dialog, "Ctrl+Shift+O", file_menu)
        self.recent_menu = file_menu.addMenu(self.tr("Недавние"))
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        file_menu.addSeparator()
        self._action(self.tr("Выход"), self.close, None, file_menu)

        view_menu = self.menuBar().addMenu(self.tr("Вид"))
        self.mode_menu = view_menu.addMenu(self.tr("Режим"))
        for key, mode, text in (("1", Mode.SINGLE, self.tr("Одна страница")), ("2", Mode.SPREAD, self.tr("Разворот")),
                                ("3", Mode.RIBBON, self.tr("Вертикальная лента"))):
            self._action(text, lambda _=False, m=mode: c.set_mode(m), key, self.mode_menu)
        self.zoom_menu = view_menu.addMenu(self.tr("Масштаб"))
        for key, zoom, text in (("W", ZoomMode.FIT_WIDTH, self.tr("По ширине")),
                                ("H", ZoomMode.FIT_HEIGHT, self.tr("По высоте")),
                                ("F", ZoomMode.FIT_WINDOW, self.tr("Целиком в окне")),
                                ("Z", ZoomMode.ACTUAL, self.tr("100%"))):
            self._action(text, lambda _=False, z=zoom: self.view.set_zoom_mode(z), key, self.zoom_menu)
        self._action(self.tr("Сменить направление чтения"), c.toggle_direction, "D", view_menu)
        self._action(self.tr("Сдвиг разворота"), c.toggle_spread_offset, "O", view_menu)
        view_menu.addSeparator()
        self._action(self.tr("Полный экран"), self._toggle_fullscreen, "F11", view_menu)
        self._action(self.tr("Настройки…"), self._open_settings, None, view_menu)

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
        self._action(self.tr("Выйти из полного экрана"), self._leave_fullscreen, "Esc")

        bar = self.toolbar
        bar.addSeparator()
        for title, menu in ((self.tr("Режим"), self.mode_menu), (self.tr("Масштаб"), self.zoom_menu)):
            button = QToolButton()
            button.setText(title)
            button.setMenu(menu)
            button.setPopupMode(QToolButton.InstantPopup)
            bar.addWidget(button)
        self.direction_button = QToolButton()
        self.direction_button.clicked.connect(c.toggle_direction)
        bar.addWidget(self.direction_button)
        settings_button = QToolButton()
        settings_button.setText("⚙")
        settings_button.setToolTip(self.tr("Настройки"))
        settings_button.clicked.connect(self._open_settings)
        bar.addWidget(settings_button)

    # -- opening ------------------------------------------------------------------------------------
    def open_paths(self, paths) -> bool:
        paths = [Path(p) for p in paths]
        if not paths:
            return False
        ok = self.controller.open_path(paths[0])
        if ok:
            save_settings(self.services.settings, self.services.data.settings_file)
        return ok

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

    def _fill_recent(self) -> None:
        self.recent_menu.clear()
        for path in self.services.settings.recent:
            action = self.recent_menu.addAction(path)
            action.triggered.connect(lambda _=False, p=path: self.open_paths([p]))
        if not self.services.settings.recent:
            self.recent_menu.addAction(self.tr("Пусто")).setEnabled(False)

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

    def _toggle_fullscreen(self) -> None:
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def _leave_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self, self.services.settings)
        if dialog.exec():
            dialog.apply_to(self.services.settings)
            self.services.cache.set_budget(self.services.settings.cache_mb * 2**20)
            apply_theme(QApplication.instance(), self.services.settings.theme)
            save_settings(self.services.settings, self.services.data.settings_file)

    # -- labels ---------------------------------------------------------------------------------------
    def page_label_text(self) -> str:
        return self.controller.page_label()

    def breadcrumb_text(self) -> str:
        return " › ".join(self.controller.breadcrumb())

    def _refresh_labels(self) -> None:
        c = self.controller
        self.crumb_label.setText(self.breadcrumb_text())
        self.page_label.setText(self.page_label_text())
        series = c.tree.title if c.tree else (c.series_root.name if c.series_root else "")
        self.setWindowTitle(f"{APP_TITLE} — {series}" if series else APP_TITLE)
        self.direction_button.setText(self.tr("Справа налево") if c.direction is Direction.RTL
                                      else self.tr("Слева направо"))
        self._slider_busy = True
        total = len(c.source.pages) if c.source else 1
        self.slider.setMaximum(max(0, total - 1))
        self.slider.setInvertedAppearance(c.direction is Direction.RTL)
        self.slider.setValue(c.page)
        self._slider_busy = False

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
        self.controller.close_source()
        QThreadPool.globalInstance().waitForDone(5000)
        self.services.store.close()
        super().closeEvent(event)
