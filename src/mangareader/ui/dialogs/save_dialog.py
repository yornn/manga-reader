"""The save window: format, quality, size, spread layout, folder and file name (spec 8.2)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QStandardPaths, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton, QSlider, QSpinBox,
                               QVBoxLayout, QWidget)
from PySide6.QtCore import Qt

from mangareader.export.encoders import LOSSY, PRESET_LABELS, QUALITY_PRESETS, EncodeOptions, OutFormat, Resize
from mangareader.settings import ExportPrefs

FORMAT_LABELS = [(OutFormat.ORIGINAL, "Как в оригинале"), (OutFormat.PNG, "PNG"), (OutFormat.JPEG, "JPEG"),
                 (OutFormat.WEBP, "WEBP"), (OutFormat.AVIF, "AVIF"), (OutFormat.TIFF, "TIFF"),
                 (OutFormat.BMP, "BMP"), (OutFormat.PDF, "PDF")]
CUSTOM = "custom"


@dataclass
class SaveChoice:
    options: EncodeOptions
    spread_layout: str
    folder: Path
    filename: str


def format_size(nbytes: int) -> str:
    mb = nbytes / 1024 / 1024
    if mb >= 1:
        return f"≈ {mb:.1f} МБ".replace(".", ",")
    return f"≈ {max(1, round(nbytes / 1024))} КБ"


def default_folder() -> str:
    return QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or str(Path.home())


class _EstimateSignals(QObject):
    done = Signal(int, int)


class _EstimateTask(QRunnable):
    def __init__(self, fn, options, ticket: int, signals: _EstimateSignals):
        super().__init__()
        self._fn, self._options, self._ticket, self._signals = fn, options, ticket, signals

    def run(self) -> None:
        try:
            size = self._fn(self._options)
        except Exception:
            size = -1
        try:
            self._signals.done.emit(self._ticket, size)
        except RuntimeError:
            pass


class SaveDialog(QDialog):
    def __init__(self, parent, prefs: ExportPrefs, *, default_name: str, is_spread: bool, is_fragment: bool,
                 jpeg_source: bool, estimate: Callable[[EncodeOptions], int] | None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Сохранить"))
        self.setMinimumWidth(560)
        self._is_fragment, self._jpeg_source, self._estimate = is_fragment, jpeg_source, estimate
        self._updating = False
        self._ticket = 0

        self.format_combo = QComboBox()
        for fmt, label in FORMAT_LABELS:
            self.format_combo.addItem(self.tr(label), fmt)
        self.preset_combo = QComboBox()
        for key, label in PRESET_LABELS.items():
            self.preset_combo.addItem(self.tr(label), key)
        self.preset_combo.addItem(self.tr("Своё"), CUSTOM)
        self.quality_slider = QSlider(Qt.Horizontal)
        self.quality_slider.setRange(1, 100)
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(1, 100)
        self.quality_slider.valueChanged.connect(self.quality_spin.setValue)
        self.quality_spin.valueChanged.connect(self.quality_slider.setValue)
        quality_row = QHBoxLayout()
        quality_row.addWidget(self.preset_combo)
        quality_row.addWidget(self.quality_slider, 1)
        quality_row.addWidget(self.quality_spin)

        self.resize_combo = QComboBox()
        self.resize_combo.addItem(self.tr("Оригинал"), "original")
        self.resize_combo.addItem(self.tr("Процент"), "percent")
        self.resize_combo.addItem(self.tr("Длинная сторона"), "long_side")
        self.resize_spin = QSpinBox()
        resize_row = QHBoxLayout()
        resize_row.addWidget(self.resize_combo)
        resize_row.addWidget(self.resize_spin)

        self.layout_group = QGroupBox(self.tr("Разворот"))
        self.layout_separate = QRadioButton(self.tr("Две отдельные страницы"))
        self.layout_stitched = QRadioButton(self.tr("Склеить в одну картинку"))
        group_layout = QVBoxLayout(self.layout_group)
        group_layout.addWidget(self.layout_separate)
        group_layout.addWidget(self.layout_stitched)
        self.layout_group.setVisible(is_spread and not is_fragment)

        self.folder_edit = QLineEdit(prefs.folder or default_folder())
        browse = QPushButton(self.tr("Обзор…"))
        browse.clicked.connect(self._browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(browse)
        self.name_edit = QLineEdit(default_name)
        self._default_name = default_name

        self.size_label = QLabel()
        self.hint_label = QLabel(self.tr("Фрагмент из JPEG сохраняется с минимальными потерями. "
                                         "Для нулевых потерь выберите PNG."))
        self.hint_label.setWordWrap(True)

        form = QFormLayout()
        form.addRow(self.tr("Формат"), self.format_combo)
        form.addRow(self.tr("Качество"), self._wrap(quality_row))
        form.addRow(self.tr("Размер"), self._wrap(resize_row))
        form.addRow(self.tr("Папка"), self._wrap(folder_row))
        form.addRow(self.tr("Имя файла"), self.name_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(self.tr("Сохранить"))
        buttons.button(QDialogButtonBox.Cancel).setText(self.tr("Отмена"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(self.layout_group)
        root.addWidget(self.hint_label)
        root.addWidget(self.size_label)
        root.addWidget(buttons)

        self._estimate_signals = _EstimateSignals()
        self._estimate_signals.done.connect(self._on_estimate)
        self._estimate_timer = QTimer(self)
        self._estimate_timer.setSingleShot(True)
        self._estimate_timer.setInterval(500)
        self._estimate_timer.timeout.connect(self._run_estimate)

        self._load(prefs)
        self.format_combo.currentIndexChanged.connect(self._on_format)
        self.preset_combo.currentIndexChanged.connect(self._on_preset)
        self.quality_slider.valueChanged.connect(self._on_quality)
        self.resize_combo.currentIndexChanged.connect(self._on_resize_mode)
        self.resize_spin.valueChanged.connect(self._changed)
        self.layout_separate.toggled.connect(self._changed)
        self._sync()

    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(layout)
        return w

    def _load(self, prefs: ExportPrefs) -> None:
        self._updating = True
        self.format_combo.setCurrentIndex(max(0, self.format_combo.findData(OutFormat(prefs.fmt))))
        self.preset_combo.setCurrentIndex(max(0, self.preset_combo.findData(prefs.preset)))
        self.quality_slider.setValue(prefs.quality)
        self.resize_combo.setCurrentIndex(max(0, self.resize_combo.findData(prefs.resize_mode)))
        self._configure_resize_spin()
        self.resize_spin.setValue(prefs.resize_value)
        (self.layout_stitched if prefs.spread_layout == "stitched" else self.layout_separate).setChecked(True)
        self._updating = False

    # -- state ----------------------------------------------------------------------------------
    def fmt(self) -> OutFormat:
        return OutFormat(self.format_combo.currentData())  # Qt stores the enum as a plain str

    def _apply_preset_value(self) -> None:
        preset = self.preset_combo.currentData()
        if preset != CUSTOM and self.fmt() in LOSSY:
            self._updating = True
            self.quality_slider.setValue(QUALITY_PRESETS[preset][self.fmt()])
            self._updating = False

    def _sync(self) -> None:
        lossy = self.fmt() in LOSSY
        for w in (self.preset_combo, self.quality_slider, self.quality_spin):
            w.setEnabled(lossy)
        self.hint_label.setVisible(self._is_fragment and self._jpeg_source and self.fmt() is OutFormat.ORIGINAL)
        self.resize_spin.setEnabled(self.resize_combo.currentData() != "original")
        self._changed()

    def _on_format(self) -> None:
        self._apply_preset_value()
        self._sync()

    def _on_preset(self) -> None:
        self._apply_preset_value()
        self._changed()

    def _on_quality(self) -> None:
        if not self._updating:
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentIndex(self.preset_combo.findData(CUSTOM))
            self.preset_combo.blockSignals(False)
        self._changed()

    def _configure_resize_spin(self) -> None:
        mode = self.resize_combo.currentData()
        if mode == "percent":
            self.resize_spin.setRange(1, 100)
            self.resize_spin.setSuffix(" %")
        else:
            self.resize_spin.setRange(16, 20000)
            self.resize_spin.setSuffix(self.tr(" px"))

    def _on_resize_mode(self) -> None:
        self._configure_resize_spin()
        if self.resize_combo.currentData() == "percent":
            self.resize_spin.setValue(50)
        elif self.resize_combo.currentData() == "long_side":
            self.resize_spin.setValue(2000)
        self._sync()

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self.tr("Папка для сохранения"), self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)

    def choice(self) -> SaveChoice:
        resize = Resize(self.resize_combo.currentData(), self.resize_spin.value())
        options = EncodeOptions(self.fmt(), self.quality_slider.value(), resize)
        layout = "stitched" if self.layout_stitched.isChecked() else "separate"
        return SaveChoice(options, layout, Path(self.folder_edit.text()),
                          self.name_edit.text().strip() or self._default_name)

    def store_into(self, prefs: ExportPrefs) -> None:
        c = self.choice()
        prefs.fmt = c.options.fmt.value
        prefs.preset = self.preset_combo.currentData()
        prefs.quality = c.options.quality
        prefs.resize_mode, prefs.resize_value = c.options.resize.mode, c.options.resize.value
        prefs.spread_layout = c.spread_layout
        prefs.folder = str(c.folder)

    # -- size estimate ------------------------------------------------------------------------------
    def _estimate_hidden(self) -> bool:
        return self._estimate is None or (self.layout_group.isVisibleTo(self) and self.layout_separate.isChecked())

    def _changed(self, *_args) -> None:
        if self._estimate_hidden():
            self.size_label.clear()
            return
        self.size_label.setText(self.tr("Размер файла: считаю…"))
        self._estimate_timer.start()

    def _run_estimate(self) -> None:
        if self._estimate_hidden():
            return
        self._ticket += 1
        QThreadPool.globalInstance().start(
            _EstimateTask(self._estimate, self.choice().options, self._ticket, self._estimate_signals))

    def _on_estimate(self, ticket: int, size: int) -> None:
        if ticket == self._ticket:
            self.size_label.setText(self.tr("Размер файла: ") + format_size(size) if size >= 0 else "")
