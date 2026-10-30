"""Error and password dialogs."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QInputDialog, QLineEdit, QMessageBox, QWidget


def _tr(text: str) -> str:
    return QCoreApplication.translate("errors", text)


def show_error(parent: QWidget | None, message: str, log_path: Path | None) -> None:
    """Non-blocking error box with an "open log" button."""
    box = QMessageBox(parent)
    box.setAttribute(Qt.WA_DeleteOnClose)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(_tr("Ошибка"))
    box.setText(message)
    box.addButton(QMessageBox.Ok)
    if log_path is not None:
        button = box.addButton(_tr("Открыть журнал"), QMessageBox.ActionRole)
        button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_path))))
    box.open()


def ask_password(parent: QWidget | None, file_name: str, wrong: bool) -> str | None:
    prompt = _tr("Неверный пароль. Попробуйте ещё раз:") if wrong else _tr("Файл защищён паролем:")
    text, ok = QInputDialog.getText(parent, _tr("Пароль"), f"{file_name}\n{prompt}", QLineEdit.Password)
    return text if ok and text else None
