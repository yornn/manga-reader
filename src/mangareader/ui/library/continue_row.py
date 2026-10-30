"""The «Продолжить чтение» row: up to five series in progress, freshest first."""
from __future__ import annotations

import time
from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPalette, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from mangareader.library.catalog import SeriesCard, continue_caption, when_text
from mangareader.render.covers import CoverLoader
from mangareader.ui import style


class ContinueCard(QFrame):
    clicked = Signal(int)

    def __init__(self, card: SeriesCard, now: float, parent=None):
        super().__init__(parent)
        self.series_id = card.id
        self.cover_source_id = card.cover_source_id
        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(style.CONTINUE_CARD_WIDTH)
        self.setToolTip(str(card.path))
        self.cover_label = QLabel()
        self.cover_label.setFixedSize(style.CONTINUE_COVER)
        self.cover_label.setAlignment(Qt.AlignCenter)
        self.cover_label.setStyleSheet(f"background: {style.PLACEHOLDER.name()};")
        self.title_label = QLabel(card.title)
        font = self.title_label.font()
        font.setBold(True)
        self.title_label.setFont(font)
        self.where_label = QLabel(continue_caption(card))
        self.when_label = QLabel(when_text(card.last_opened_at or now, now))
        self.when_label.setForegroundRole(QPalette.PlaceholderText)
        text = QVBoxLayout()
        text.setSpacing(2)
        for label in (self.title_label, self.where_label, self.when_label):
            label.setMinimumWidth(10)
            text.addWidget(label)
        text.addStretch(1)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.cover_label)
        layout.addLayout(text, 1)

    def set_cover(self, image) -> None:
        if image is not None and not image.isNull():
            pixmap = QPixmap.fromImage(image).scaled(style.CONTINUE_COVER, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.cover_label.setPixmap(pixmap)
            self.cover_label.setStyleSheet("")

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.series_id)
        super().mouseReleaseEvent(event)


class ContinueRow(QWidget):
    open_series = Signal(int)

    def __init__(self, covers: CoverLoader, parent=None):
        super().__init__(parent)
        self._covers = covers
        self._cards: list[ContinueCard] = []
        inner = QWidget()
        self._layout = QHBoxLayout(inner)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addStretch(1)
        # the row scrolls sideways, so five cards never make the window wider than the screen
        self._scroll = QScrollArea()
        self._scroll.setWidget(inner)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._scroll)
        covers.cover_ready.connect(self._on_cover)

    def set_cards(self, cards: Sequence[SeriesCard], now: float | None = None) -> None:
        now = time.time() if now is None else now
        for widget in self._cards:
            self._layout.removeWidget(widget)
            widget.hide()
            widget.deleteLater()
        self._cards = []
        for n, card in enumerate(cards):
            widget = ContinueCard(card, now)
            widget.clicked.connect(self.open_series)
            widget.set_cover(self._covers.cover(card.cover_source_id))
            self._layout.insertWidget(n, widget)
            widget.show()
            self._cards.append(widget)
        bar = self._scroll.horizontalScrollBar().sizeHint().height()
        height = max((w.sizeHint().height() for w in self._cards), default=0)
        self._scroll.setFixedHeight(height + bar + 2)

    def cards(self) -> list[ContinueCard]:
        return list(self._cards)

    def _on_cover(self, source_id: int) -> None:
        for widget in self._cards:
            if widget.cover_source_id == source_id:
                widget.set_cover(self._covers.cover(source_id))
