"""The go-to-page window: a page number across the whole series."""
from __future__ import annotations

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout


def _tr(text: str) -> str:
    return QCoreApplication.translate("page_dialog", text)


class PageDialog(QDialog):
    def __init__(self, parent, current: int, total: int):
        super().__init__(parent)
        self.setWindowTitle(_tr("Перейти к странице"))
        self.edit = QLineEdit(str(current))
        self.edit.setValidator(QIntValidator(0, 10**9, self))
        self.edit.selectAll()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(_tr("Перейти"))
        buttons.button(QDialogButtonBox.Cancel).setText(_tr("Отмена"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(_tr("Страница (1–{})").format(total)))
        layout.addWidget(self.edit)
        layout.addWidget(buttons)

    def value(self) -> int | None:
        text = self.edit.text().strip()
        return int(text) if text.isdigit() else None


def ask_page(parent, current: int, total: int) -> int | None:
    """A number the person typed (the reader clamps it to the series), or None."""
    dialog = PageDialog(parent, current, total)
    return dialog.value() if dialog.exec() == QDialog.Accepted else None
