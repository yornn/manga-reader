"""Asking for a manual chapter mark: number and optional title."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit


class ChapterMarkDialog(QDialog):
    def __init__(self, parent, number: str, title: str = ""):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Начало главы"))
        self.number_edit = QLineEdit(number)
        self.title_edit = QLineEdit(title)
        self.title_edit.setPlaceholderText(self.tr("необязательно"))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout(self)
        form.addRow(self.tr("Номер главы"), self.number_edit)
        form.addRow(self.tr("Название"), self.title_edit)
        form.addRow(buttons)


def ask_chapter_mark(parent, number: str, title: str = "") -> tuple[str, str] | None:
    dialog = ChapterMarkDialog(parent, number, title)
    if not dialog.exec():
        return None
    value = dialog.number_edit.text().strip()
    return (value, dialog.title_edit.text().strip()) if value else None
