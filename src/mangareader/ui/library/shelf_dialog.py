"""The shelf window: a name and one of the 48 icons."""
from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox, QFormLayout, QGridLayout, QLabel, QLineEdit,
                               QToolButton, QWidget)

from mangareader.library.catalog import Catalog
from mangareader.ui import icons, style
from mangareader.ui.icons import DEFAULT_SHELF_ICON

ICONS_PER_ROW = 8


class ShelfDialog(QDialog):
    def __init__(self, parent, catalog: Catalog, *, title: str, name: str = "", icon: str = DEFAULT_SHELF_ICON,
                 shelf_id: int | None = None):
        super().__init__(parent)
        self._catalog = catalog
        self._shelf_id = shelf_id
        self._icon = icon if icon in icons.SHELF_ICONS else DEFAULT_SHELF_ICON
        self.setWindowTitle(title)
        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText(self.tr("Название"))
        self.name_edit.textChanged.connect(lambda _: self.error_label.clear())
        grid_box = QWidget()
        grid = QGridLayout(grid_box)
        grid.setContentsMargins(0, 0, 0, 0)
        group = QButtonGroup(self)
        self.icon_buttons: dict[str, QToolButton] = {}
        for n, icon_name in enumerate(icons.SHELF_ICONS):
            button = QToolButton()
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setToolTip(icon_name)
            button.setIcon(icons.icon(icon_name, style.DIALOG_ICON, style.text_color()))
            button.setIconSize(QSize(style.DIALOG_ICON, style.DIALOG_ICON))
            button.setChecked(icon_name == self._icon)
            button.clicked.connect(lambda _=False, i=icon_name: self._choose(i))
            group.addButton(button)
            grid.addWidget(button, n // ICONS_PER_ROW, n % ICONS_PER_ROW)
            self.icon_buttons[icon_name] = button
        self.error_label = QLabel()
        self.error_label.setStyleSheet(f"color: {style.ERROR_COLOR};")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(self.tr("Сохранить"))
        buttons.button(QDialogButtonBox.Cancel).setText(self.tr("Отмена"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout(self)
        form.addRow(self.tr("Название"), self.name_edit)
        form.addRow(self.tr("Иконка"), grid_box)
        form.addRow(self.error_label)
        form.addRow(buttons)

    def _choose(self, name: str) -> None:
        self._icon = name

    def accept(self) -> None:
        error = self._catalog.check_shelf_name(self.name_edit.text(), self._shelf_id)
        if error:
            self.error_label.setText(self.tr(error))
            return
        super().accept()

    def value(self) -> tuple[str, str]:
        return self.name_edit.text().strip(), self._icon


def ask_shelf(parent, catalog: Catalog, *, title: str, name: str = "", icon: str = DEFAULT_SHELF_ICON,
              shelf_id: int | None = None) -> tuple[str, str] | None:
    dialog = ShelfDialog(parent, catalog, title=title, name=name, icon=icon, shelf_id=shelf_id)
    return dialog.value() if dialog.exec() == QDialog.Accepted else None
