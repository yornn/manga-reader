"""Short messages that appear over the window and fade by themselves."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class Toast(QWidget):
    _last_text: str | None = None
    _current: "Toast | None" = None

    def __init__(self, parent: QWidget, text: str, action: tuple[str, Callable[[], None]] | None, ms: int):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setStyleSheet("#toast { background: rgba(20, 20, 20, 220); border-radius: 8px; }"
                           "QLabel { color: white; padding: 4px; } QPushButton { padding: 4px 10px; }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.addWidget(QLabel(text))
        if action:
            button = QPushButton(action[0])
            button.clicked.connect(action[1])
            button.clicked.connect(self.close)
            layout.addWidget(button)
        self.adjustSize()
        self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - 60)
        QTimer.singleShot(ms, self.close)

    @classmethod
    def show_message(cls, parent: QWidget, text: str, action: tuple[str, Callable[[], None]] | None = None,
                     ms: int = 3000) -> "Toast":
        cls._last_text = text
        if cls._current is not None:
            try:
                cls._current.close()
            except RuntimeError:
                pass
        toast = cls(parent, text, action, ms)
        toast.show()
        toast.raise_()
        cls._current = toast
        return toast

    @classmethod
    def last_text(cls) -> str | None:
        return cls._last_text
