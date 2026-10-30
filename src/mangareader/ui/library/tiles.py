"""The tile grid of the library: the «Открыть» tile first, then one tile per series."""
from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QAbstractListModel, QMimeData, QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QAbstractItemView, QListView, QStyle, QStyledItemDelegate

from mangareader.library.catalog import SeriesCard, tile_caption
from mangareader.render.covers import CoverLoader
from mangareader.ui import style

SERIES_MIME = "application/x-mangareader-series"
CARD_ROLE = Qt.UserRole + 1


def series_ids_from_mime(mime: QMimeData) -> list[int]:
    raw = bytes(mime.data(SERIES_MIME)).decode("ascii", "ignore")
    return [int(part) for part in raw.split(",") if part.strip().isdigit()]


class TileModel(QAbstractListModel):
    def __init__(self, covers: CoverLoader, parent=None):
        super().__init__(parent)
        self._covers = covers
        self._cards: list[SeriesCard] = []
        self._rows_by_cover: dict[int, list[int]] = {}
        covers.cover_ready.connect(self._on_cover)

    def set_cards(self, cards: Sequence[SeriesCard]) -> None:
        self.beginResetModel()
        self._cards = list(cards)
        self._rows_by_cover = {}
        for row, card in enumerate(self._cards, start=1):
            if card.cover_source_id is not None:
                self._rows_by_cover.setdefault(card.cover_source_id, []).append(row)
        self.endResetModel()

    def card_at(self, row: int) -> SeriesCard | None:
        return self._cards[row - 1] if 1 <= row <= len(self._cards) else None

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._cards) + 1

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        card = self.card_at(index.row())
        if role == Qt.DisplayRole:
            return card.title if card else self.tr("Открыть")
        if card is None:
            return None
        if role == Qt.ToolTipRole:
            return str(card.path)
        if role == CARD_ROLE:
            return card
        if role == Qt.DecorationRole:
            return self._covers.cover(card.cover_source_id)
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.NoItemFlags
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        return flags | Qt.ItemIsDragEnabled if index.row() > 0 else flags

    def mimeTypes(self) -> list[str]:
        return [SERIES_MIME]

    def mimeData(self, indexes) -> QMimeData:
        ids = [self.card_at(i.row()).id for i in indexes if self.card_at(i.row()) is not None]
        mime = QMimeData()
        mime.setData(SERIES_MIME, ",".join(map(str, ids)).encode("ascii"))
        return mime

    def supportedDragActions(self) -> Qt.DropActions:
        return Qt.CopyAction

    def _on_cover(self, source_id: int) -> None:
        for row in self._rows_by_cover.get(source_id, []):
            index = self.index(row)
            self.dataChanged.emit(index, index, [Qt.DecorationRole])


class TileDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index) -> QSize:
        return style.TILE_GRID

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        frame = option.rect.adjusted(3, 3, -3, -3)
        cover = QRect(frame.center().x() - style.TILE_COVER.width() // 2, frame.top() + 6,
                      style.TILE_COVER.width(), style.TILE_COVER.height())
        line = option.fontMetrics.height()
        title_rect = QRect(cover.left(), cover.bottom() + 6, cover.width(), line)
        bar = QRect(cover.left(), title_rect.bottom() + 5, cover.width(), style.PROGRESS_HEIGHT)
        caption_rect = QRect(cover.left(), bar.bottom() + 4, cover.width(), line)
        if option.state & QStyle.State_Selected:
            painter.setPen(QPen(style.accent_color(), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(frame, style.TILE_RADIUS, style.TILE_RADIUS)
        card = index.data(CARD_ROLE)
        if card is None:
            self._paint_open(painter, option, cover, title_rect, caption_rect)
        else:
            if not card.available:
                painter.setOpacity(style.UNAVAILABLE_OPACITY)
            self._paint_cover(painter, cover, index.data(Qt.DecorationRole))
            self._paint_marks(painter, option, cover, card)
            painter.setPen(style.text_color())
            painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter,
                             option.fontMetrics.elidedText(card.title, Qt.ElideRight, title_rect.width()))
            painter.setPen(Qt.NoPen)
            painter.setBrush(style.PLACEHOLDER)
            painter.drawRoundedRect(bar, 2, 2)
            if card.progress > 0:
                painter.setBrush(style.accent_color())
                painter.drawRoundedRect(QRect(bar.left(), bar.top(), max(2, round(bar.width() * card.progress)),
                                              bar.height()), 2, 2)
            painter.setPen(style.muted_color())
            painter.drawText(caption_rect, Qt.AlignLeft | Qt.AlignVCenter,
                             option.fontMetrics.elidedText(tile_caption(card), Qt.ElideRight, caption_rect.width()))
        painter.restore()

    def _paint_open(self, painter: QPainter, option, cover: QRect, title_rect: QRect, caption_rect: QRect) -> None:
        pen = QPen(style.muted_color(), 2, Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(cover, style.TILE_RADIUS, style.TILE_RADIUS)
        big = QFont(option.font)
        big.setPointSizeF(option.font.pointSizeF() * 3)
        painter.setFont(big)
        painter.setPen(style.text_color())
        painter.drawText(cover, Qt.AlignCenter, "＋")
        painter.setFont(option.font)
        painter.drawText(title_rect, Qt.AlignCenter, self.tr("Открыть"))
        painter.setPen(style.muted_color())
        painter.drawText(caption_rect, Qt.AlignCenter, self.tr("файл или папку"))

    def _paint_cover(self, painter: QPainter, cover: QRect, image) -> None:
        if image is None or image.isNull():
            painter.setPen(Qt.NoPen)
            painter.setBrush(style.PLACEHOLDER)
            painter.drawRoundedRect(cover, style.TILE_RADIUS, style.TILE_RADIUS)
            return
        size = image.size().scaled(cover.size(), Qt.KeepAspectRatio)
        target = QRect(0, 0, size.width(), size.height())
        target.moveCenter(cover.center())
        painter.drawImage(target, image)

    def _paint_marks(self, painter: QPainter, option, cover: QRect, card: SeriesCard) -> None:
        small = QFont(option.font)
        small.setPointSizeF(max(6.0, option.font.pointSizeF() * 0.8))
        small.setBold(True)
        painter.setFont(small)
        metrics = painter.fontMetrics()
        if card.main_format:
            badge = QRect(cover.left() + 4, cover.top() + 4, metrics.horizontalAdvance(card.main_format) + 8,
                          metrics.height() + 2)
            painter.setPen(Qt.NoPen)
            painter.setBrush(style.BADGE_BG)
            painter.drawRoundedRect(badge, 3, 3)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(badge, Qt.AlignCenter, card.main_format)
        if card.favorite:
            star = QRect(cover.right() - metrics.height() - 6, cover.top() + 4, metrics.height() + 2,
                         metrics.height() + 2)
            painter.setPen(Qt.NoPen)
            painter.setBrush(style.BADGE_BG)
            painter.drawRoundedRect(star, 3, 3)
            painter.setPen(QColor(style.FAVORITE_COLOR))
            painter.drawText(star, Qt.AlignCenter, "★")
        painter.setFont(option.font)


class TileGrid(QListView):
    tile_activated = Signal(QModelIndex)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QListView.NoFrame)
        self.setViewMode(QListView.IconMode)
        self.setMovement(QListView.Static)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.Adjust)
        self.setUniformItemSizes(True)
        self.setGridSize(style.TILE_GRID)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setMouseTracking(True)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.currentIndex().isValid():
            self.tile_activated.emit(self.currentIndex())
            return
        super().keyPressEvent(event)
