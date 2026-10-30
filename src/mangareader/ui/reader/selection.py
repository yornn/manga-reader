"""The snipping tool: a resizable selection rectangle over the shown pages."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsRectItem

from mangareader.export.geometry import Placed, crops_for_selection, output_size, stitch
from mangareader.export.model import PageImage, load_page_image
from mangareader.sources.base import PageSource
from mangareader.ui.reader.view import PageView

HANDLE_PX = 9
ACCENT = QColor("#3d7bd9")
_HANDLES = ("tl", "t", "tr", "r", "br", "b", "bl", "l")


def pages_union(placed: list[Placed]) -> QRectF:
    rect = QRectF()
    for p in placed:
        rect = rect.united(QRectF(p.x, p.y, p.w, p.h))
    return rect


def render_selection(source: PageSource, placed: list[Placed], rect: QRectF):
    sel = (rect.x(), rect.y(), rect.width(), rect.height())
    pages: dict[int, PageImage] = {c.page: load_page_image(source, c.page)
                                   for c in crops_for_selection(placed, sel)}
    # the layout may still use a guessed size for a page; map through the real one
    placed = [replace(p, orig_w=pages[p.page].decoded.image.width, orig_h=pages[p.page].decoded.image.height)
              if p.page in pages else p for p in placed]
    crops = crops_for_selection(placed, sel)
    image = stitch(placed, crops, {page: pi.decoded.image for page, pi in pages.items()})
    return image, [pages[c.page] for c in crops]


class _SizeLabel(QGraphicsItem):
    def __init__(self):
        super().__init__()
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.text = ""

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, 9 * max(len(self.text), 1) + 12, 24)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        rect = self.boundingRect()
        painter.fillRect(rect, QColor(20, 20, 20, 210))
        painter.setPen(QColor("white"))
        painter.drawText(rect, Qt.AlignCenter, self.text)


class SelectionTool(QObject):
    save_requested = Signal()
    copy_requested = Signal()
    finished = Signal()

    def __init__(self, view: PageView):
        super().__init__(view)
        self.view = view
        self.active = False
        self._rect: QRectF | None = None
        self._drag: str | None = None
        self._anchor = QPointF()
        self._start_rect = QRectF()
        self._items: dict = {}
        self._viewport = view.viewport()
        self._viewport.installEventFilter(self)
        view.pages_shown.connect(self._on_pages_shown)
        view.destroyed.connect(self._on_view_destroyed)

    def _on_view_destroyed(self) -> None:
        self.active = False
        self._viewport = None

    # -- state ------------------------------------------------------------------------------
    def activate(self) -> None:
        self.active = True
        self.view.set_selection_mode(True)

    def deactivate(self) -> None:
        was_active = self.active
        self.active = False
        self._rect = None
        self._drag = None
        self._remove_items()
        self.view.set_selection_mode(False)
        if was_active:
            self.finished.emit()

    def toggle(self) -> None:
        self.deactivate() if self.active else self.activate()

    def rect(self) -> QRectF | None:
        return QRectF(self._rect) if self._rect is not None else None

    def set_rect(self, rect: QRectF) -> None:
        bounds = pages_union(self.view.placed())
        clamped = rect.normalized().intersected(bounds)
        self._rect = clamped if clamped.width() > 0 and clamped.height() > 0 else None
        self._update_items()

    def size_label(self) -> str:
        if self._rect is None:
            return ""
        r = self._rect
        w, h = output_size(self.view.placed(), crops_for_selection(self.view.placed(),
                                                                   (r.x(), r.y(), r.width(), r.height())))
        return f"{w} × {h}"

    # -- visuals -----------------------------------------------------------------------------
    def _remove_items(self) -> None:
        scene = self.view.scene()
        for item in self._items.values():
            if item.scene() is scene:
                scene.removeItem(item)
        self._items = {}

    def _on_pages_shown(self) -> None:
        # the scene was cleared, so the old items are gone
        self._items = {}
        self._rect = None
        self._drag = None

    def _handle_rects(self) -> dict[str, QRectF]:
        r = self._rect
        k = HANDLE_PX / max(self.view.scale_factor(), 1e-6)
        points = {"tl": r.topLeft(), "t": QPointF(r.center().x(), r.top()), "tr": r.topRight(),
                  "r": QPointF(r.right(), r.center().y()), "br": r.bottomRight(),
                  "b": QPointF(r.center().x(), r.bottom()), "bl": r.bottomLeft(),
                  "l": QPointF(r.left(), r.center().y())}
        return {name: QRectF(p.x() - k / 2, p.y() - k / 2, k, k) for name, p in points.items()}

    def _update_items(self) -> None:
        if self._rect is None:
            self._remove_items()
            return
        scene = self.view.scene()
        if not self._items:
            shade = QGraphicsPathItem()
            shade.setBrush(QBrush(QColor(0, 0, 0, 110)))
            shade.setPen(Qt.NoPen)
            frame = QGraphicsRectItem()
            pen = QPen(ACCENT, 2, Qt.DashLine)
            pen.setCosmetic(True)
            frame.setPen(pen)
            self._items = {"shade": shade, "frame": frame, "label": _SizeLabel()}
            for name in _HANDLES:
                handle = QGraphicsRectItem()
                handle.setBrush(QBrush(QColor("white")))
                pen = QPen(ACCENT, 1)
                pen.setCosmetic(True)
                handle.setPen(pen)
                self._items[name] = handle
            for z, item in enumerate(self._items.values()):
                item.setZValue(100 + z)
                scene.addItem(item)
        path = QPainterPath()
        path.addRect(pages_union(self.view.placed()))
        inner = QPainterPath()
        inner.addRect(self._rect)
        self._items["shade"].setPath(path.subtracted(inner))
        self._items["frame"].setRect(self._rect)
        for name, rect in self._handle_rects().items():
            self._items[name].setRect(rect)
        label = self._items["label"]
        label.prepareGeometryChange()
        label.text = self.size_label()
        label.setPos(self._rect.bottomRight())
        label.update()

    # -- mouse ------------------------------------------------------------------------------------
    def _hit(self, point: QPointF) -> str | None:
        if self._rect is None:
            return None
        for name, rect in self._handle_rects().items():
            if rect.adjusted(-rect.width(), -rect.height(), rect.width(), rect.height()).contains(point):
                return name
        return "move" if self._rect.contains(point) else None

    def _drag_to(self, point: QPointF) -> None:
        r = QRectF(self._start_rect)
        dx, dy = point.x() - self._anchor.x(), point.y() - self._anchor.y()
        if self._drag == "new":
            r = QRectF(self._anchor, point)
        elif self._drag == "move":
            r.translate(dx, dy)
            bounds = pages_union(self.view.placed())
            r.moveLeft(min(max(r.left(), bounds.left()), bounds.right() - r.width()))
            r.moveTop(min(max(r.top(), bounds.top()), bounds.bottom() - r.height()))
        else:
            if "l" in self._drag:
                r.setLeft(r.left() + dx)
            if "r" in self._drag:
                r.setRight(r.right() + dx)
            if "t" in self._drag:
                r.setTop(r.top() + dy)
            if "b" in self._drag:
                r.setBottom(r.bottom() + dy)
        self.set_rect(r)

    def eventFilter(self, obj, event) -> bool:
        if not self.active or obj is not self._viewport:
            return False
        kind = event.type()
        if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            point = self.view.mapToScene(event.position().toPoint())
            self._drag = self._hit(point) or "new"
            self._anchor = point
            self._start_rect = QRectF(self._rect) if self._rect is not None else QRectF()
            return True
        if kind == QEvent.MouseMove and self._drag:
            self._drag_to(self.view.mapToScene(event.position().toPoint()))
            return True
        if kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton and self._drag:
            self._drag_to(self.view.mapToScene(event.position().toPoint()))
            self._drag = None
            return True
        return False
