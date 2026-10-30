"""The panel behind the reader's gear: mode, direction, zoom, brightness, book font and the hotkey sheet."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QRadioButton,
                               QSlider, QVBoxLayout, QWidget)

from mangareader.ui.reader.layout import Direction, Mode
from mangareader.ui.reader.view import MIN_BRIGHTNESS, ZoomMode


class ReaderSettingsPanel(QWidget):
    mode_chosen = Signal(str)
    zoom_chosen = Signal(str)
    direction_chosen = Signal(str)
    spread_offset_toggled = Signal()
    brightness_changed = Signal(int)
    font_size_changed = Signal(int)
    hotkeys_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._groups: list[QButtonGroup] = []
        form = QFormLayout(self)
        form.setContentsMargins(12, 10, 12, 10)

        self.mode_buttons = self._choices(form, self.tr("Режим"), [
            (Mode.SINGLE, self.tr("Одна страница (1)")), (Mode.SPREAD, self.tr("Разворот (2)")),
            (Mode.RIBBON, self.tr("Вертикальная лента (3)")), (Mode.HRIBBON, self.tr("Горизонтальная лента (4)"))],
            self.mode_chosen)
        self.offset_check = QCheckBox(self.tr("Сдвиг разворота (O)"))
        self.offset_check.clicked.connect(lambda _=False: self.spread_offset_toggled.emit())
        form.addRow("", self.offset_check)
        self.direction_buttons = self._choices(form, self.tr("Направление"), [
            (Direction.RTL, self.tr("Справа налево")), (Direction.LTR, self.tr("Слева направо"))],
            self.direction_chosen)
        self.zoom_buttons = self._choices(form, self.tr("Масштаб"), [
            (ZoomMode.FIT_WIDTH, self.tr("По ширине (W)")), (ZoomMode.FIT_HEIGHT, self.tr("По высоте (H)")),
            (ZoomMode.FIT_WINDOW, self.tr("Целиком (F)")), (ZoomMode.ACTUAL, self.tr("100% (Z)"))],
            self.zoom_chosen)

        self.brightness_slider = QSlider(Qt.Horizontal)
        self.brightness_slider.setRange(MIN_BRIGHTNESS, 100)
        self.brightness_label = QLabel()
        self.brightness_slider.valueChanged.connect(self._on_brightness)
        brightness = QHBoxLayout()
        brightness.addWidget(self.brightness_slider, 1)
        brightness.addWidget(self.brightness_label)
        form.addRow(self.tr("Яркость"), brightness)

        self.font_slider = QSlider(Qt.Horizontal)
        self.font_slider.setRange(8, 24)
        self.font_slider.valueChanged.connect(self.font_size_changed)
        self.font_row = QWidget()
        font_layout = QHBoxLayout(self.font_row)
        font_layout.setContentsMargins(0, 0, 0, 0)
        font_layout.addWidget(QLabel(self.tr("Шрифт")))
        font_layout.addWidget(self.font_slider, 1)
        form.addRow(self.font_row)

        self.hotkeys_button = QPushButton(self.tr("Горячие клавиши…"))
        self.hotkeys_button.clicked.connect(self.hotkeys_requested)
        form.addRow(self.hotkeys_button)

    def _choices(self, form: QFormLayout, title: str, options, signal) -> dict:
        group = QButtonGroup(self)
        self._groups.append(group)
        box = QVBoxLayout()
        box.setSpacing(2)
        buttons = {}
        for value, text in options:
            button = QRadioButton(text)
            button.clicked.connect(lambda _=False, v=value: signal.emit(str(v)))
            group.addButton(button)
            box.addWidget(button)
            buttons[value] = button
        form.addRow(title, box)
        return buttons

    def _on_brightness(self, value: int) -> None:
        self.brightness_label.setText(f"{value}%")
        self.brightness_changed.emit(value)

    def sync(self, mode: Mode, zoom: ZoomMode, direction: Direction, spread_offset: bool, brightness: int,
             font_size: float, is_book: bool) -> None:
        """Show the reader's current state without echoing it back as changes."""
        widgets = [*self.mode_buttons.values(), *self.zoom_buttons.values(), *self.direction_buttons.values(),
                   self.offset_check, self.brightness_slider, self.font_slider]
        for widget in widgets:
            widget.blockSignals(True)
        for group in self._groups:              # a free zoom (Ctrl+wheel) checks none of the four
            group.setExclusive(False)
        for value, button in self.mode_buttons.items():
            button.setChecked(value is mode)
        for value, button in self.zoom_buttons.items():
            button.setChecked(value is zoom)
        for value, button in self.direction_buttons.items():
            button.setChecked(value is direction)
        self.offset_check.setChecked(spread_offset)
        self.offset_check.setEnabled(mode is Mode.SPREAD)
        self.brightness_slider.setValue(brightness)
        self.brightness_label.setText(f"{self.brightness_slider.value()}%")
        self.font_slider.setValue(round(font_size))
        for group in self._groups:
            group.setExclusive(True)
        for widget in widgets:
            widget.blockSignals(False)
        self.font_row.setVisible(is_book)
