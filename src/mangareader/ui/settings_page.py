"""The settings page: library folders, theme, saving and memory. Every change is applied and saved at once."""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSpinBox,
                               QToolButton, QVBoxLayout, QWidget)

from mangareader.library.catalog import CatalogError
from mangareader.settings import save_settings
from mangareader.ui.dialogs import errors
from mangareader.ui.dialogs.save_dialog import default_folder
from mangareader.ui.theme import apply_theme
from mangareader.ui.toast import Toast

ROOT_ID_ROLE = Qt.UserRole
AVAILABLE_ROLE = Qt.UserRole + 1
PATH_ROLE = Qt.UserRole + 2


def choose_folder(parent: QWidget | None, title: str) -> str:
    return QFileDialog.getExistingDirectory(parent, title)


class SettingsPage(QWidget):
    theme_changed = Signal()
    roots_changed = Signal()
    rescan_requested = Signal()

    def __init__(self, services, parent=None):
        super().__init__(parent)
        self.services = services
        settings = services.settings

        self.roots_list = QListWidget()
        self.roots_list.currentRowChanged.connect(lambda _: self._update_buttons())
        self.add_button = QPushButton(self.tr("＋ Добавить папку…"))
        self.add_button.clicked.connect(self._add_root)
        self.remove_button = QPushButton(self.tr("Убрать"))
        self.remove_button.clicked.connect(self._remove_root)
        self.rescan_button = QPushButton(self.tr("⟳ Обновить сейчас"))
        self.rescan_button.clicked.connect(self.rescan_requested)
        self.relocate_button = QPushButton(self.tr("Указать новое место…"))
        self.relocate_button.clicked.connect(self._relocate_root)
        buttons = QHBoxLayout()
        for button in (self.add_button, self.remove_button, self.rescan_button, self.relocate_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        self.failed_toggle = QToolButton()
        self.failed_toggle.setCheckable(True)
        self.failed_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.failed_toggle.setArrowType(Qt.RightArrow)
        self.failed_toggle.setAutoRaise(True)
        self.failed_toggle.toggled.connect(self._toggle_failed)
        self.failed_list = QListWidget()
        self.failed_list.setVisible(False)
        roots_box = QGroupBox(self.tr("Папки библиотеки"))
        roots_layout = QVBoxLayout(roots_box)
        roots_layout.addWidget(self.roots_list)
        roots_layout.addLayout(buttons)
        roots_layout.addWidget(self.failed_toggle)
        roots_layout.addWidget(self.failed_list)

        self.theme_combo = QComboBox()
        self.theme_combo.addItem(self.tr("Тёмная"), "dark")
        self.theme_combo.addItem(self.tr("Светлая"), "light")
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(settings.theme)))
        self.theme_combo.currentIndexChanged.connect(lambda _: self._set_theme())
        look_box = QGroupBox(self.tr("Внешний вид"))
        QFormLayout(look_box).addRow(self.tr("Тема"), self.theme_combo)

        self.folder_edit = QLineEdit(settings.export.folder or default_folder())
        self.folder_edit.setReadOnly(True)
        self.folder_button = QPushButton(self.tr("Выбрать…"))
        self.folder_button.clicked.connect(self._choose_save_folder)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(self.folder_button)
        self.template_edit = QLineEdit(settings.export.template)
        self.template_edit.editingFinished.connect(self._set_template)
        hint = QLabel(self.tr("Подстановки: {серия} {том} {глава} {страница} {файл}"))
        hint.setEnabled(False)
        save_box = QGroupBox(self.tr("Сохранение"))
        save_form = QFormLayout(save_box)
        save_form.addRow(self.tr("Папка по умолчанию"), folder_row)
        save_form.addRow(self.tr("Имя файла"), self.template_edit)
        save_form.addRow("", hint)

        self.cache_spin = QSpinBox()
        self.cache_spin.setRange(256, 8192)
        self.cache_spin.setSingleStep(256)
        self.cache_spin.setSuffix(self.tr(" МБ"))
        self.cache_spin.setValue(settings.cache_mb)
        self.cache_spin.valueChanged.connect(self._set_cache)
        memory_box = QGroupBox(self.tr("Память"))
        QFormLayout(memory_box).addRow(self.tr("Память под страницы"), self.cache_spin)

        body = QWidget()
        column = QVBoxLayout(body)
        title = QLabel(self.tr("Настройки"))
        font = title.font()
        font.setPointSizeF(font.pointSizeF() * 1.4)
        font.setBold(True)
        title.setFont(font)
        column.addWidget(title)
        for box in (roots_box, look_box, save_box, memory_box):
            column.addWidget(box)
        column.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(body)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)
        self.refresh()

    # -- library folders ------------------------------------------------------------------------------
    def refresh(self, failed: Sequence[tuple[Path, str]] = ()) -> None:
        current = self.roots_list.currentRow()
        self.roots_list.clear()
        for root in self.services.catalog.roots():
            text = str(root.path) if root.available else f"{root.path} — {self.tr('не найдена')}"
            item = QListWidgetItem(text)
            item.setData(ROOT_ID_ROLE, root.id)
            item.setData(AVAILABLE_ROLE, root.available)
            item.setData(PATH_ROLE, str(root.path))
            self.roots_list.addItem(item)
        if self.roots_list.count():
            self.roots_list.setCurrentRow(min(max(current, 0), self.roots_list.count() - 1))
        self.failed_list.clear()
        for path, reason in failed:
            self.failed_list.addItem(f"{path.name} — {reason}")
        self.failed_toggle.setText(self.tr("Не удалось открыть ({})").format(len(failed)))
        self.failed_toggle.setVisible(bool(failed))
        if not failed:
            self.failed_toggle.setChecked(False)
        self._update_buttons()

    def _selected(self) -> QListWidgetItem | None:
        return self.roots_list.currentItem()

    def _update_buttons(self) -> None:
        item = self._selected()
        self.remove_button.setEnabled(item is not None)
        self.relocate_button.setEnabled(item is not None and not item.data(AVAILABLE_ROLE))

    def _toggle_failed(self, on: bool) -> None:
        self.failed_toggle.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.failed_list.setVisible(on)

    def _add_root(self) -> None:
        folder = choose_folder(self, self.tr("Папка библиотеки"))
        if not folder:
            return
        try:
            self.services.catalog.add_root(Path(folder))
        except CatalogError as e:
            Toast.show_message(self.window(), str(e))
            return
        self.refresh()
        self.roots_changed.emit()

    def _remove_root(self) -> None:
        item = self._selected()
        if item is None:
            return
        name = Path(item.data(PATH_ROLE)).name
        if errors.confirm(self, self.tr("Убрать папку «{}» из библиотеки? Прогресс чтения сохранится").format(name)):
            self.services.catalog.remove_root(item.data(ROOT_ID_ROLE))
            self.refresh()
            self.roots_changed.emit()

    def _relocate_root(self) -> None:
        item = self._selected()
        if item is None:
            return
        folder = choose_folder(self, self.tr("Новое место папки"))
        if not folder:
            return
        try:
            self.services.catalog.relocate_root(item.data(ROOT_ID_ROLE), Path(folder))
        except CatalogError as e:
            Toast.show_message(self.window(), str(e))
            return
        self.refresh()
        self.roots_changed.emit()

    # -- preferences ----------------------------------------------------------------------------------------
    def _save(self) -> None:
        save_settings(self.services.settings, self.services.data.settings_file)

    def _set_theme(self) -> None:
        self.services.settings.theme = self.theme_combo.currentData()
        apply_theme(QApplication.instance(), self.services.settings.theme)
        self._save()
        self.theme_changed.emit()

    def _choose_save_folder(self) -> None:
        folder = choose_folder(self, self.tr("Папка для сохранения"))
        if folder:
            self.folder_edit.setText(folder)
            self.services.settings.export.folder = folder
            self._save()

    def _set_template(self) -> None:
        text = self.template_edit.text().strip()
        if text and text != self.services.settings.export.template:
            self.services.settings.export.template = text
            self._save()

    def _set_cache(self, value: int) -> None:
        self.services.settings.cache_mb = value
        self.services.cache.set_budget(value * 2**20)
        self._save()
