from pathlib import Path

from mangareader.ui.icons import DEFAULT_SHELF_ICON, ICON_DIR, SHELF_ICONS, icon_pixmap


def test_all_shelf_icons_render(qapp):
    assert len(SHELF_ICONS) == 48 == len(set(SHELF_ICONS))
    for name in SHELF_ICONS:
        image = icon_pixmap(name, 24, "#ff0000").toImage()
        assert (ICON_DIR / f"{name}.svg").exists() and not image.isNull()
        assert any(image.pixelColor(x, y).red() > 200 for x in range(24) for y in range(24)), name


def test_unknown_icon_falls_back(qapp):
    assert icon_pixmap("no-such", 24, "#fff").toImage() == icon_pixmap(DEFAULT_SHELF_ICON, 24, "#fff").toImage()


def test_licence_and_packaging():
    assert "ISC" in (ICON_DIR / "LICENSE").read_text(encoding="utf-8")
    root = Path(__file__).parents[1]
    assert "icons" in (root / "packaging" / "mangareader.spec").read_text(encoding="utf-8")
    assert "lucide/*.svg" in (root / "pyproject.toml").read_text(encoding="utf-8")
