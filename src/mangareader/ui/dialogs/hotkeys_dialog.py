"""The hotkey sheet: every key the reader knows, with what it does."""
from __future__ import annotations

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout


def _tr(text: str) -> str:
    return QCoreApplication.translate("hotkeys", text)


# (keys as shown, what they do, the shortcuts of the window's actions); a test checks both lists agree
HOTKEYS: list[tuple[str, str, tuple[str, ...]]] = [
    ("← / →", "Листать. При чтении справа налево ← — вперёд", ("Left", "Right")),
    ("PgDn / PgUp", "Следующая / предыдущая страница", ("PgDown", "PgUp")),
    ("Пробел / Shift+Пробел", "Прокрутить вниз / вверх, в конце страницы — перелистнуть", ("Space", "Shift+Space")),
    ("Home / End", "Первая / последняя страница файла", ("Home", "End")),
    ("Ctrl+PgDn / Ctrl+PgUp", "Следующая / предыдущая глава", ("Ctrl+PgDown", "Ctrl+PgUp")),
    ("Ctrl+G", "Перейти к странице по сквозному номеру серии (или клик по счётчику страниц)", ("Ctrl+G",)),
    ("1 / 2 / 3 / 4", "Одна страница / разворот / вертикальная лента / горизонтальная лента", ("1", "2", "3", "4")),
    ("W / H / F / Z", "Масштаб: по ширине / по высоте / целиком / 100%", ("W", "H", "F", "Z")),
    ("O", "Сдвиг разворота на одну страницу", ("O",)),
    ("D", "Сменить направление чтения", ("D",)),
    ("S", "Ножницы: выделить фрагмент", ("S",)),
    ("Enter / Esc", "С ножницами: сохранить / отменить. Esc ещё выходит из режима «только страница» и полного экрана",
     ("Return", "Enter", "Esc")),
    ("Ctrl+C", "Копировать фрагмент или страницу в буфер обмена", ("Ctrl+C",)),
    ("Ctrl+S", "Сохранить страницу или фрагмент", ("Ctrl+S",)),
    ("Ctrl+Shift+S", "Быстрое сохранение с прошлыми настройками", ("Ctrl+Shift+S",)),
    ("Tab", "Показать или скрыть панель томов и глав", ("Tab",)),
    ("F11", "Полный экран", ("F11",)),
    ("Backspace", "Вернуться в библиотеку", ("Backspace",)),
    ("Ctrl+O / Ctrl+Shift+O", "Открыть файл / папку", ("Ctrl+O", "Ctrl+Shift+O")),
    ("Колесо мыши", "Плавная прокрутка; с Ctrl — масштаб", ()),
    ("Кнопка ◧", "Только страница: спрятать панели. Верхняя полоса всплывает, если подвести мышь к верхнему краю", ()),
    ("Клик по левой / правой трети страницы", "Листать", ()),
]


class HotkeysDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_tr("Горячие клавиши"))
        self.table = QTableWidget(len(HOTKEYS), 2)
        self.table.setHorizontalHeaderLabels([_tr("Клавиши"), _tr("Что делает")])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setWordWrap(True)
        for row, (keys, text, _) in enumerate(HOTKEYS):
            self.table.setItem(row, 0, QTableWidgetItem(_tr(keys)))
            self.table.setItem(row, 1, QTableWidgetItem(_tr(text)))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.resizeRowsToContents()
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText(_tr("Закрыть"))
        buttons.rejected.connect(self.close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addWidget(buttons)
        self.resize(640, 560)


def show_hotkeys(parent) -> HotkeysDialog:
    dialog = HotkeysDialog(parent)
    dialog.setAttribute(Qt.WA_DeleteOnClose)
    dialog.show()
    return dialog
