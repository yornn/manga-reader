"""The main window: toolbar, page area, page slider, menus and hotkeys."""
from __future__ import annotations

import base64
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt, QThreadPool, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QLabel, QMainWindow, QMenu, QSizePolicy, QSlider,
                               QSplitter, QToolBar, QToolButton, QVBoxLayout, QWidget)

from mangareader.logging_setup import LOG_NAME
from mangareader.settings import save_settings
from mangareader.sources.detect import OPENABLE_EXTS
from mangareader.library.classify import suggest_chapter_number
from mangareader.export import writer
from mangareader.export.encoders import EncodeOptions, OutFormat, Resize, encode_fragment, encode_page
from mangareader.export.model import load_page_image
from mangareader.export.naming import NameFields, render_name
from mangareader.export.writer import ExportError
from mangareader.library.model import Kind
from mangareader.ui.dialogs import chapter_mark_dialog, errors
from mangareader.ui.dialogs.save_dialog import SaveChoice, SaveDialog
from mangareader.ui.dialogs.settings_dialog import SettingsDialog
from mangareader.ui.reader.controller import ReaderController, Services
from mangareader.ui.reader.layout import Direction, Mode
from mangareader.render.loader import pil_to_qimage
from mangareader.sources.base import SourceError
from mangareader.ui.reader.navigation import Position
from mangareader.ui.reader.selection import SelectionTool, pages_union, render_selection
from mangareader.ui.reader.sidebar import Sidebar
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
        self.selection = SelectionTool(self.view)
        self.selection.save_requested.connect(self.save_current)
        self.controller.password_provider = lambda path, wrong: errors.ask_password(self, path.name, wrong)
        self.controller.state_changed.connect(self._refresh_labels)
        self.controller.source_changed.connect(lambda title: Toast.show_message(self, title))
        self.controller.error.connect(self._show_error)
        self.controller.source_opened.connect(self._on_source_opened)
        self.controller.tree_changed.connect(self._on_tree_changed)
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
        self.sidebar = Sidebar(self.services.loader)
        self.sidebar.position_selected.connect(lambda e, p: self.controller.go_to(Position(e, p)))
        self.sidebar.mark_requested.connect(self._add_mark)
        self.sidebar.mark_edit_requested.connect(self._edit_mark)
        self.sidebar.mark_delete_requested.connect(self.controller.delete_chapter_mark)
        self.sidebar.kind_override_requested.connect(
            lambda index, kind: self.controller.set_kind_override(index, Kind(kind) if kind else None))
        self.sidebar.setVisible(self.services.settings.sidebar_visible)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.view)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([280, 1000])
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
        self._action(self.tr("Показать или скрыть панель"), self._toggle_sidebar, "Tab", view_menu)
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
        self._action(self.tr("Отмена"), self._escape, "Esc")
        edit_menu = self.menuBar().addMenu(self.tr("Правка"))
        self.snip_action = self._action(self.tr("Ножницы"), self.selection.toggle, "S", edit_menu)
        self._action(self.tr("Копировать"), self.copy_to_clipboard, "Ctrl+C", edit_menu)
        self._action(self.tr("Сохранить…"), lambda: self.save_current(), "Ctrl+S", edit_menu)
        self._action(self.tr("Быстрое сохранение"), lambda: self.save_current(quick=True), "Ctrl+Shift+S", edit_menu)
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

    def _toggle_sidebar(self) -> None:
        visible = not self.sidebar.isVisible()
        self.sidebar.setVisible(visible)
        self.services.settings.sidebar_visible = visible

    # -- sidebar -----------------------------------------------------------------------------------
    def _on_source_opened(self) -> None:
        c = self.controller
        self.sidebar.set_tree(c.display_tree())
        self.sidebar.set_source(c.source_key, len(c.source.pages), c.marks(), c.markable())

    def _on_tree_changed(self) -> None:
        self.sidebar.set_tree(self.controller.display_tree())
        self.sidebar.set_marks(self.controller.marks())
        self.sidebar.set_current(self.controller.position)

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
        else:
            self._leave_fullscreen()

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
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            return render_selection(self.controller.source, self.view.placed(), rect)
        finally:
            QApplication.restoreOverrideCursor()

    def copy_to_clipboard(self) -> None:
        if self.controller.source is None:
            return
        try:
            image, _ = self._render_target()
        except SourceError as e:
            self._show_error(str(e))
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
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if fragment or is_spread:
                image, sources = self._render_target()
                estimate = lambda o: len(encode_fragment(image, sources, o).data)  # noqa: E731
            else:
                page_image = load_page_image(c.source, group[0])
                estimate = lambda o: len(encode_page(page_image, o).data)  # noqa: E731
        except SourceError as e:
            QApplication.restoreOverrideCursor()
            self._show_error(str(e))
            return []
        QApplication.restoreOverrideCursor()
        choice = self._choose(quick, default_name=default_name, is_spread=is_spread, is_fragment=fragment,
                              jpeg_source=jpeg_source, estimate=estimate)
        if choice is None:
            return []
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
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
        except (ExportError, SourceError) as e:
            QApplication.restoreOverrideCursor()
            errors.show_error(self, str(e), self.services.data.logs / LOG_NAME)
            return []
        QApplication.restoreOverrideCursor()
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
        self.sidebar.set_current(c.position)

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
