"""The page area: shows a group of pages (or the ribbon), zooms, scrolls and flips."""
from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QTransform
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView

from mangareader.export.geometry import Placed
from mangareader.render.loader import PRIORITY_PREFETCH, PageLoader
from mangareader.ui.reader.layout import Direction

CLICK_SLOP = 5
WHEEL_STEP = 120
SMOOTH_MS = 160          # one wheel notch glides for this long


class ZoomMode(StrEnum):
    FIT_WIDTH = "width"
    FIT_HEIGHT = "height"
    FIT_WINDOW = "window"
    ACTUAL = "actual"
    CUSTOM = "custom"


class PageItem(QGraphicsItem):
    def __init__(self, placed: Placed):
        super().__init__()
        self.placed = placed
        self.setPos(placed.x, placed.y)
        self._image: QImage | None = None
        self._image_size: tuple[int, int] | None = None
        self._error: str | None = None
        self._exact = False
        self.wanted_size: tuple[int, int] | None = None

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.placed.w, self.placed.h)

    def has_scaled_image(self) -> bool:
        return self._image is not None

    def scaled_size(self) -> tuple[int, int] | None:
        return self._image_size

    def error_text(self) -> str | None:
        return self._error

    def set_image(self, image: QImage, size: tuple[int, int], exact: bool) -> None:
        self._image, self._image_size, self._exact, self._error = image, size, exact, None
        self.update()

    def set_error(self, message: str) -> None:
        self._error = message
        self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        rect = self.boundingRect()
        if self._image is not None:
            if self._exact and self._image_size == self.wanted_size:
                # draw 1:1 in device pixels so the Lanczos-scaled copy is not resampled again
                origin = painter.worldTransform().map(QPointF(0, 0))
                dpr = self._image.devicePixelRatio()
                painter.save()
                painter.resetTransform()
                painter.drawImage(QPointF(round(origin.x() * dpr) / dpr, round(origin.y() * dpr) / dpr),
                                  self._image)
                painter.restore()
            else:
                painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
                painter.drawImage(rect, self._image)
            return
        painter.fillRect(rect, QColor(60, 60, 60) if self._error else QColor(45, 45, 45))
        painter.setPen(QColor(220, 220, 220))
        font = QFont(painter.font())
        font.setPixelSize(max(12, int(rect.height() / 40)))
        painter.setFont(font)
        painter.drawText(rect.adjusted(rect.width() * 0.05, 0, -rect.width() * 0.05, 0),
                         Qt.AlignCenter | Qt.TextWordWrap, self._error or "Загрузка…")


class PageView(QGraphicsView):
    flip_requested = Signal(bool)
    visible_page_changed = Signal(int)
    resized = Signal()
    pages_shown = Signal()

    def __init__(self, loader: PageLoader, parent=None):
        super().__init__(parent)
        self._loader = loader
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor(30, 30, 30))
        self.setAlignment(Qt.AlignCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setFocusPolicy(Qt.StrongFocus)
        self._key: str | None = None
        self._placed: list[Placed] = []
        self._items: dict[int, PageItem] = {}
        self._direction = Direction.RTL
        self._ribbon = False
        self._zoom_mode = ZoomMode.FIT_WINDOW
        self._custom_scale = 1.0
        self._press: QPoint | None = None
        self._horizontal = False
        self._scroll_target: QPointF | None = None
        self._scroll_anim = QVariantAnimation(self)
        self._scroll_anim.setDuration(SMOOTH_MS)
        self._scroll_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._scroll_anim.valueChanged.connect(self._on_scroll_step)
        self._visible_page: int | None = None
        self.selection_mode = False
        self._refresh = QTimer(self)
        self._refresh.setSingleShot(True)
        self._refresh.setInterval(50)
        self._refresh.timeout.connect(self._request_images)
        loader.scaled_ready.connect(self._on_scaled)
        loader.failed.connect(self._on_failed)
        self.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        self.horizontalScrollBar().valueChanged.connect(self._on_scrolled)

    # -- content ------------------------------------------------------------------
    def show_pages(self, key: str, placed: list[Placed], direction: Direction, ribbon: bool = False,
                   focus_page: int | None = None, anchor: tuple[int, float] | None = None,
                   horizontal: bool = False) -> None:
        self._scroll_anim.stop()                    # a glide must not carry over to the next page
        self.scene().clear()
        self._key, self._placed, self._direction, self._ribbon = key, list(placed), direction, ribbon
        self._horizontal = ribbon and horizontal
        self._items = {}
        for p in placed:
            item = PageItem(p)
            message = self._loader.error(key, p.page)
            if message:
                item.set_error(message)
            self.scene().addItem(item)
            self._items[p.page] = item
        bounds = QRectF()
        for p in placed:
            bounds = bounds.united(QRectF(p.x, p.y, p.w, p.h))
        self.scene().setSceneRect(bounds)
        self._visible_page = None
        self._apply_zoom()
        if ribbon and anchor is not None:
            self.scroll_to_page(anchor[0], anchor[1])
        elif ribbon and focus_page is not None:
            self.scroll_to_page(focus_page)
        else:
            self.verticalScrollBar().setValue(self.verticalScrollBar().minimum())
            h = self.horizontalScrollBar()
            h.setValue(h.maximum() if direction is Direction.RTL else h.minimum())
        self._request_images()          # cached copies appear at once, without a placeholder flash
        self.pages_shown.emit()

    def placed(self) -> list[Placed]:
        return list(self._placed)

    def page_item(self, page: int) -> PageItem:
        return self._items[page]

    def current_key(self) -> str | None:
        return self._key

    # -- zoom -----------------------------------------------------------------------
    @property
    def zoom_mode(self) -> ZoomMode:
        return self._zoom_mode

    def scale_factor(self) -> float:
        return self.transform().m11()

    def set_zoom_mode(self, mode: ZoomMode) -> None:
        self._zoom_mode = mode
        self._apply_zoom()

    def zoom_by(self, factor: float) -> None:
        self._custom_scale = max(0.05, min(self.scale_factor() * factor, 20.0))
        self._zoom_mode = ZoomMode.CUSTOM
        self._apply_zoom()

    def _fit_basis(self, placed: list[Placed], ribbon: bool) -> tuple[float, float]:
        # the width and height the fit modes match: the whole group, or in a ribbon the page being read
        width = max(p.x + p.w for p in placed) - min(p.x for p in placed)
        height = max(p.y + p.h for p in placed) - min(p.y for p in placed)
        if ribbon:
            page = self._visible_page if self._visible_page is not None else placed[0].page
            current = next((p for p in placed if p.page == page), placed[0])
            if self._horizontal:
                width = current.w
            else:
                height = current.h
        return width, height

    def _target_scale(self) -> float:
        return self.scale_for(self._placed, self._ribbon)

    def scale_for(self, placed: list[Placed], ribbon: bool = False) -> float:
        # the scale the current zoom mode gives to this group of pages
        if self._zoom_mode is ZoomMode.CUSTOM:
            return self._custom_scale
        if self._zoom_mode is ZoomMode.ACTUAL:
            return 1 / self.devicePixelRatioF()
        if not placed:
            return 1.0
        width, height = self._fit_basis(placed, ribbon)
        if width <= 0 or height <= 0:
            return 1.0
        vp = self.viewport()
        by_width = vp.width() / width
        by_height = vp.height() / height
        if self._zoom_mode is ZoomMode.FIT_WIDTH:
            return by_width
        if self._zoom_mode is ZoomMode.FIT_HEIGHT:
            return by_height
        return min(by_width, by_height)

    def _apply_zoom(self) -> None:
        s = self._target_scale()
        self.setTransform(QTransform.fromScale(s, s))
        self._refresh.start()

    # -- images ---------------------------------------------------------------------
    def visible_pages(self) -> list[int]:
        area = self.mapToScene(self.viewport().rect()).boundingRect()
        if self._ribbon and self._horizontal:
            area.adjust(-area.width(), 0, area.width(), 0)
        elif self._ribbon:
            area.adjust(0, -area.height(), 0, area.height())
        return [p.page for p in self._placed if area.intersects(QRectF(p.x, p.y, p.w, p.h))]

    def _wanted_size(self, p: Placed, scale: float | None = None) -> tuple[int, int]:
        k = (self.scale_factor() if scale is None else scale) * self.devicePixelRatioF()
        return min(round(p.w * k), p.orig_w) or 1, min(round(p.h * k), p.orig_h) or 1

    def wanted_sizes(self, placed: list[Placed]) -> dict[int, tuple[int, int]]:
        scale = self.scale_for(placed)
        return {p.page: self._wanted_size(p, scale) for p in placed}

    def prepare(self, key: str, placed: list[Placed]) -> None:
        # build display copies of a group that is likely to be shown next
        for page, size in self.wanted_sizes(placed).items():
            self._loader.scaled(key, page, *size, priority=PRIORITY_PREFETCH)

    def _request_images(self) -> None:
        if self._key is None:
            return
        for page in self.visible_pages():
            item = self._items[page]
            item.wanted_size = self._wanted_size(item.placed)
            if item.error_text():
                continue
            image = self._loader.scaled(self._key, page, *item.wanted_size)
            if image is not None:
                self._set_item_image(item, image)
        self.viewport().update()

    def _set_item_image(self, item: PageItem, image: QImage) -> None:
        image = QImage(image)
        k = self.scale_factor() * self.devicePixelRatioF()
        exact = (image.width(), image.height()) == (round(item.placed.w * k), round(item.placed.h * k))
        image.setDevicePixelRatio(self.devicePixelRatioF() if exact else 1.0)
        item.set_image(image, (image.width(), image.height()), exact)

    def _on_scaled(self, key: str, page: int) -> None:
        item = self._items.get(page)
        if key != self._key or item is None or item.wanted_size is None:
            return
        image = self._loader.scaled(key, page, *item.wanted_size)
        if image is not None:
            self._set_item_image(item, image)

    def _on_failed(self, key: str, page: int, message: str) -> None:
        item = self._items.get(page)
        if key == self._key and item is not None:
            item.set_error(message)

    # -- scrolling ------------------------------------------------------------------
    def scroll_to_page(self, page: int, fraction: float = 0.0) -> None:
        # put the given point of the page (0 = its top) at the top of the view
        target = next((p for p in self._placed if p.page == page), None)
        if target is None:
            return
        if self._horizontal:
            # the page's leading edge (its right edge when reading right to left) to the view's leading edge
            bar = self.horizontalScrollBar()
            if self._direction is Direction.RTL:
                edge = self.mapFromScene(QPointF(target.x + (1 - fraction) * target.w, 0)).x()
                bar.setValue(bar.value() + edge - self.viewport().width())
            else:
                bar.setValue(bar.value() + self.mapFromScene(QPointF(target.x + fraction * target.w, 0)).x())
            self._visible_page = page
            return
        top = self.mapFromScene(QPointF(target.x, target.y + fraction * target.h))
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + top.y())
        self._visible_page = page

    def ribbon_anchor(self) -> tuple[int, float] | None:
        # which page is at the top of the view (the leading edge of a horizontal ribbon), and how far into it
        if self._horizontal:
            rtl = self._direction is Direction.RTL
            x = self.mapToScene(QPoint(self.viewport().width() if rtl else 0, 0)).x()
            for p in self._placed:
                if p.x <= x < p.x + p.w or (rtl and p.x < x <= p.x + p.w):
                    return p.page, ((p.x + p.w - x) if rtl else (x - p.x)) / p.w
            return None
        top = self.mapToScene(QPoint(0, 0)).y()
        for p in self._placed:
            if p.y <= top < p.y + p.h:
                return p.page, (top - p.y) / p.h
        return None

    def _on_scrolled(self, _value: int) -> None:
        self._refresh.start()
        if not self._ribbon or not self._placed:
            return
        center = self.mapToScene(self.viewport().rect().center())
        if self._horizontal:
            page = next((p.page for p in self._placed if p.x <= center.x() < p.x + p.w), None)
        else:
            page = next((p.page for p in self._placed if p.y <= center.y() < p.y + p.h), None)
        if page is not None and page != self._visible_page:
            self._visible_page = page
            self.visible_page_changed.emit(page)

    # -- input --------------------------------------------------------------------------
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._zoom_mode is not ZoomMode.CUSTOM:
            self._apply_zoom()
        self.resized.emit()

    def _along_ribbon(self, dx: float, dy: float) -> tuple[float, float]:
        # in the horizontal ribbon the wheel moves along the reading direction
        if not self._horizontal:
            return dx, dy
        return dx + (dy if self._direction is Direction.LTR else -dy), 0.0

    def smooth_scroll(self, dx: float, dy: float) -> None:
        h, v = self.horizontalScrollBar(), self.verticalScrollBar()
        start = QPointF(h.value(), v.value())
        running = self._scroll_anim.state() == QVariantAnimation.Running
        base = self._scroll_target if running and self._scroll_target is not None else start
        target = QPointF(min(max(base.x() + dx, h.minimum()), h.maximum()),
                         min(max(base.y() + dy, v.minimum()), v.maximum()))
        if target == start:
            return
        self._scroll_target = target
        self._scroll_anim.stop()
        self._scroll_anim.setStartValue(start)
        self._scroll_anim.setEndValue(target)
        self._scroll_anim.start()

    def _on_scroll_step(self, value: QPointF) -> None:
        self.horizontalScrollBar().setValue(round(value.x()))
        self.verticalScrollBar().setValue(round(value.y()))

    def wheelEvent(self, event) -> None:
        # the wheel only scrolls (spec 2.1); pages turn with the keys and the side clicks
        dy = event.angleDelta().y()
        if event.modifiers() & Qt.ControlModifier:
            self.zoom_by(1.25 ** (dy / WHEEL_STEP))
            event.accept()
            return
        event.accept()
        pixels = event.pixelDelta()
        if not pixels.isNull():                       # a touchpad already scrolls smoothly
            self._scroll_anim.stop()
            dx, dy = self._along_ribbon(-pixels.x(), -pixels.y())
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + round(dx))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + round(dy))
            return
        step = max(80.0, self.viewport().height() * 0.2)
        dx, dy = self._along_ribbon(-event.angleDelta().x() / WHEEL_STEP * step, -dy / WHEEL_STEP * step)
        self.smooth_scroll(dx, dy)

    def set_selection_mode(self, on: bool) -> None:
        self.selection_mode = on
        self.setDragMode(QGraphicsView.NoDrag if on else QGraphicsView.ScrollHandDrag)
        self.viewport().setCursor(Qt.CrossCursor if on else Qt.OpenHandCursor)

    def mousePressEvent(self, event) -> None:
        self._press = event.position().toPoint() if event.button() == Qt.LeftButton else None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        press, self._press = self._press, None
        if self.selection_mode or press is None or event.button() != Qt.LeftButton:
            return
        if (event.position().toPoint() - press).manhattanLength() > CLICK_SLOP:
            return
        third = self.viewport().width() / 3
        x = event.position().x()
        if x < third:
            self.flip_requested.emit(self._direction is Direction.RTL)
        elif x > 2 * third:
            self.flip_requested.emit(self._direction is Direction.LTR)
