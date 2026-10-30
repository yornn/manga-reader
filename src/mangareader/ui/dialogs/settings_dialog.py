"""The ⚙ dialog: theme and memory limit."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QSpinBox

from mangareader.settings import Settings


class SettingsDialog(QDialog):
    def __init__(self, parent, settings: Settings):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Настройки"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItem(self.tr("Тёмная"), "dark")
        self.theme_combo.addItem(self.tr("Светлая"), "light")
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(settings.theme)))
        self.cache_spin = QSpinBox()
        self.cache_spin.setRange(256, 8192)
        self.cache_spin.setSingleStep(256)
        self.cache_spin.setSuffix(self.tr(" МБ"))
        self.cache_spin.setValue(settings.cache_mb)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout(self)
        form.addRow(self.tr("Тема"), self.theme_combo)
        form.addRow(self.tr("Память под страницы"), self.cache_spin)
        form.addRow(buttons)

    def apply_to(self, settings: Settings) -> None:
        settings.theme = self.theme_combo.currentData()
        settings.cache_mb = self.cache_spin.value()
