"""Sizes and colours of the library and navigation screens, kept in one place for a later redesign."""
from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

NAV_WIDTH = 220
TILE_COVER = QSize(150, 213)
TILE_GRID = QSize(172, 292)
TILE_RADIUS = 6
PROGRESS_HEIGHT = 4
CONTINUE_COVER = QSize(54, 77)
CONTINUE_CARD_WIDTH = 250
READER_NAV_WIDTH = 300
VOLUME_COVER = QSize(32, 45)
NAV_THUMB = QSize(78, 112)
SHELF_ICON = 18
DIALOG_ICON = 28
UNAVAILABLE_OPACITY = 0.4
FAVORITE_COLOR = "#f2c94c"
ERROR_COLOR = "#ff6b6b"
BADGE_BG = QColor(0, 0, 0, 170)
PLACEHOLDER = QColor(60, 60, 60)


def _palette_color(role: QPalette.ColorRole) -> QColor:
    return QApplication.palette().color(role)


def text_color() -> QColor:
    return _palette_color(QPalette.WindowText)


def muted_color() -> QColor:
    return _palette_color(QPalette.PlaceholderText)


def accent_color() -> QColor:
    return _palette_color(QPalette.Highlight)
