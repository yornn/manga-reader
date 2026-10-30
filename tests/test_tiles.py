from PySide6.QtCore import Qt

from helpers import card
from mangareader.ui.library.tiles import TileDelegate, TileGrid, TileModel, series_ids_from_mime


def test_open_tile_first(qtbot, services):
    model = TileModel(services.covers)
    model.set_cards([card(id=5, title="Berserk")])
    assert model.rowCount() == 2 and model.data(model.index(0)) == "Открыть" and model.card_at(1).id == 5
    assert model.card_at(0) is None and model.data(model.index(1)) == "Berserk"
    assert not model.flags(model.index(0)) & Qt.ItemIsDragEnabled and model.flags(model.index(1)) & Qt.ItemIsDragEnabled


def test_mime_roundtrip(qtbot, services):
    model = TileModel(services.covers)
    model.set_cards([card(id=5), card(id=9)])
    assert series_ids_from_mime(model.mimeData([model.index(1), model.index(2)])) == [5, 9]


def test_cover_ready_updates_row(qtbot, services):
    model = TileModel(services.covers)
    model.set_cards([card(id=5, cover_source_id=42)])
    with qtbot.waitSignal(model.dataChanged) as blocker:
        services.covers.cover_ready.emit(42)
    assert blocker.args[0].row() == 1


def test_grid_paints_all_kinds(qtbot, services):
    grid = TileGrid()
    model = TileModel(services.covers)
    grid.setModel(model)
    grid.setItemDelegate(TileDelegate(grid))
    model.set_cards([card(id=1, favorite=True), card(id=2, available=False), card(id=3, opened=1, finished=1)])
    qtbot.addWidget(grid)
    grid.resize(800, 400)
    grid.show()
    assert not grid.grab().isNull()
