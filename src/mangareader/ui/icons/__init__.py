"""Shelf icons: Lucide outline icons (ISC licence, see lucide/LICENSE), tinted to the theme."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ICON_DIR = Path(__file__).parent / "lucide"
SHELF_ICONS: tuple[str, ...] = (
    "book", "book-open", "library", "bookmark", "heart", "star", "sword", "swords", "shield", "skull", "ghost",
    "flower", "leaf", "flame", "droplet", "zap", "moon", "sun", "cloud", "snowflake", "mountain", "tree-pine",
    "house", "crown", "rocket", "plane", "compass", "map", "globe", "coffee", "cake", "fish", "cat", "dog", "bird",
    "music", "camera", "gamepad-2", "puzzle", "lightbulb", "clock", "calendar", "flag", "smile", "drama", "eye",
    "key", "gem",
)
DEFAULT_SHELF_ICON = "book"

_cache: dict[tuple[str, int, str], QPixmap] = {}


def icon_pixmap(name: str, size: int, color: QColor | str) -> QPixmap:
    if name not in SHELF_ICONS:
        name = DEFAULT_SHELF_ICON
    hex_color = QColor(color).name()
    key = (name, size, hex_color)
    pixmap = _cache.get(key)
    if pixmap is None:
        svg = (ICON_DIR / f"{name}.svg").read_text(encoding="utf-8").replace("currentColor", hex_color)
        image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
        painter.end()
        pixmap = _cache[key] = QPixmap.fromImage(image)
    return pixmap


def icon(name: str, size: int, color: QColor | str) -> QIcon:
    return QIcon(icon_pixmap(name, size, color))
