"""Dark and light palettes on the Fusion style."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def apply_theme(app: QApplication, theme: str) -> None:
    app.setStyle("Fusion")
    if theme != "dark":
        app.setPalette(app.style().standardPalette())
        return
    p = QPalette()
    colors = {
        QPalette.Window: "#2b2b2b", QPalette.WindowText: "#e6e6e6", QPalette.Base: "#1e1e1e",
        QPalette.AlternateBase: "#2b2b2b", QPalette.ToolTipBase: "#3a3a3a", QPalette.ToolTipText: "#e6e6e6",
        QPalette.Text: "#e6e6e6", QPalette.Button: "#353535", QPalette.ButtonText: "#e6e6e6",
        QPalette.BrightText: "#ff5555", QPalette.Highlight: "#3d7bd9", QPalette.HighlightedText: "#ffffff",
        QPalette.Link: "#6ea8ff", QPalette.PlaceholderText: "#8a8a8a",
    }
    for role, color in colors.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor("#777777"))
    app.setPalette(p)
