from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QDialog

from helpers import card
from mangareader.library.catalog import Catalog, Section, SectionKind, Shelf
from mangareader.library.store import Store
from mangareader.ui.library.nav import LibraryNav
from mangareader.ui.library.shelf_dialog import ShelfDialog
from mangareader.ui.library.tiles import TileModel


def texts(item):
    return item.text(0), item.text(1)


def test_items_and_counts(qtbot):
    nav = LibraryNav()
    qtbot.addWidget(nav)
    nav.set_data([card(id=1, favorite=True, formats=("CBZ",), shelf_ids=frozenset({3})),
                  card(id=2, formats=("EPUB", "CBZ"))], [Shelf(3, "Сэйнэн", "sword", 0)])
    assert texts(nav.item_for(Section())) == ("▦ Все", "2")
    assert texts(nav.item_for(Section(SectionKind.FAVORITES))) == ("★ Избранное", "1")
    assert texts(nav.item_for(Section(SectionKind.FORMAT, "EPUB"))) == ("EPUB", "1")
    assert nav.item_for(Section(SectionKind.FORMAT, "PDF")) is None
    assert texts(nav.item_for(Section(SectionKind.SHELF, 3))) == ("Сэйнэн", "1")


def test_click_emits_sections_and_actions(qtbot):
    nav = LibraryNav()
    qtbot.addWidget(nav)
    nav.set_data([], [Shelf(3, "Сэйнэн", "sword", 0)])
    with qtbot.waitSignal(nav.section_selected) as b:
        nav.tree.itemClicked.emit(nav.item_for(Section(SectionKind.SHELF, 3)), 0)
    assert b.args == [Section(SectionKind.SHELF, 3)]
    tree = nav.tree
    add = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
               if "Добавить категорию" in tree.topLevelItem(i).text(0))
    with qtbot.waitSignal(nav.add_shelf_requested):
        tree.itemClicked.emit(add, 0)
    with qtbot.waitSignal(nav.settings_requested):
        nav.settings_button.click()
    assert [a.text() for a in nav.shelf_menu(3).actions()] == ["Переименовать…", "Сменить иконку…", "Удалить полку"]


def test_drop_series_on_shelf(qtbot, services):
    nav = LibraryNav()
    qtbot.addWidget(nav)
    nav.set_data([card(id=7)], [Shelf(3, "Сэйнэн", "sword", 0)])
    nav.show()
    model = TileModel(services.covers)
    model.set_cards([card(id=7)])
    pos = nav.tree.visualItemRect(nav.item_for(Section(SectionKind.SHELF, 3))).center()
    mime = model.mimeData([model.index(1)])                # keep a reference: the event does not own it
    event = QDropEvent(QPointF(pos), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    with qtbot.waitSignal(nav.series_dropped) as b:
        nav.tree.dropEvent(event)
    assert b.args == [3, [7]]


def test_shelf_dialog_duplicate_stays_open(qtbot, tmp_path):
    cat = Catalog(Store(tmp_path / "db"))
    cat.add_shelf("Романтика", "heart")
    dlg = ShelfDialog(None, cat, title="Новая полка")
    qtbot.addWidget(dlg)
    dlg.name_edit.setText("романтика")
    dlg.accept()
    assert dlg.result() != QDialog.Accepted and dlg.error_label.text() == "Такая полка уже есть"
    dlg.name_edit.setText("Сэйнэн")
    dlg.icon_buttons["sword"].click()
    dlg.accept()
    assert dlg.result() == QDialog.Accepted and dlg.value() == ("Сэйнэн", "sword") and len(dlg.icon_buttons) == 48
