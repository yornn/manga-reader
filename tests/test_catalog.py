import shutil
import sys
from pathlib import Path

import pytest

from mangareader.library.catalog import Catalog, CatalogError, Status
from mangareader.library.model import SeriesPrefs
from mangareader.library.store import Store


@pytest.fixture
def st(tmp_path):
    store = Store(tmp_path / "library.db")
    yield store
    store.close()


@pytest.fixture
def cat(st):
    return Catalog(st)


def make_series(cat, st, tmp_path, name, pages=(10, 10), root_id=None, base=None):
    folder = (base or tmp_path) / name
    folder.mkdir(parents=True)
    ids = []
    for i, n in enumerate(pages):
        f = folder / f"c{i + 1}.cbz"
        f.write_bytes(b"1")
        ids.append(st.register(f, 1, 1.0, f"{name}{i}", n, ()).id)
    sid = cat.ensure_series(folder, root_id)
    cat.update_series(sid, title=name, formats=["CBZ"], cover_source_id=ids[0], source_ids=ids)
    return sid, ids


def test_status_and_progress(cat, st, tmp_path):
    sid, ids = make_series(cat, st, tmp_path, "Berserk")
    c = cat.card(sid)
    assert (c.status, c.progress, c.pages_total) == (Status.NOT_STARTED, 0.0, 20)
    st.set_progress(ids[0], 4, False, 0.5)
    c = cat.card(sid)
    assert c.status is Status.READING and c.progress == 0.25
    for i in ids:
        st.set_progress(i, 9, True)
    assert cat.card(sid).status is Status.FINISHED and cat.card(sid).progress == 1.0


def test_mark_read_and_unread(cat, st, tmp_path):
    sid, ids = make_series(cat, st, tmp_path, "S")
    st.set_progress(ids[0], 4, False, 0.5)
    cat.touch(sid, ids[0], ["Глава 1", "стр. 5"])
    cat.mark_read(sid)
    assert cat.card(sid).status is Status.FINISHED and st.progress(ids[0]).position == 4
    cat.mark_unread(sid)
    c = cat.card(sid)
    assert c.status is Status.NOT_STARTED and c.where == () and st.progress(ids[0]) is None


def test_touch_and_favorite(cat, st, tmp_path):
    sid, ids = make_series(cat, st, tmp_path, "S")
    cat.touch(sid, ids[1], ["Глава 2", "стр. 3"])
    cat.set_favorite(sid, True)
    c = cat.card(sid)
    assert c.where == ("Глава 2", "стр. 3") and c.last_source_id == ids[1] and c.last_opened_at and c.favorite


def test_shelves_unique_multi_and_delete(cat, st, tmp_path):
    sid, _ = make_series(cat, st, tmp_path, "S")
    a = cat.add_shelf("Романтика", "heart")
    b = cat.add_shelf("Сэйнэн", "sword")
    for dup in ("романтика", "РОМАНТИКА", "  Романтика "):
        with pytest.raises(CatalogError, match="Такая полка уже есть"):
            cat.add_shelf(dup, "book")
    with pytest.raises(CatalogError, match="Введите название"):
        cat.add_shelf("  ", "book")
    with pytest.raises(CatalogError, match="Такая полка уже есть"):
        cat.rename_shelf(b, "романтика")
    cat.rename_shelf(a, "РОМАНТИКА")                                     # own name in another case is fine
    cat.add_to_shelf(a, [sid])
    cat.add_to_shelf(b, [sid])
    assert cat.card(sid).shelf_ids == {a, b}
    cat.delete_shelf(a)
    assert [s.name for s in cat.shelves()] == ["Сэйнэн"] and cat.card(sid).shelf_ids == {b}


def test_roots_reject_nested_and_remove_keeps_progress(cat, st, tmp_path):
    lib = tmp_path / "Манга"
    lib.mkdir()
    rid = cat.add_root(lib)
    for p, text in ((lib, "уже в библиотеке"), (lib / "sub", "уже внутри папки библиотеки"),
                    (tmp_path, "Внутри этой папки уже есть папка библиотеки")):
        p.mkdir(exist_ok=True)
        with pytest.raises(CatalogError, match=text):
            cat.add_root(p)
    sid, ids = make_series(cat, st, tmp_path, "S", root_id=rid, base=lib)
    st.set_progress(ids[0], 4, False, 0.5)
    shelf = cat.add_shelf("Полка", "book")
    cat.add_to_shelf(shelf, [sid])
    cat.remove_root(rid)
    assert cat.cards() == [] and st.progress(ids[0]).position == 4
    rid = cat.add_root(lib)
    sid = cat.ensure_series(lib / "S", rid)
    cat.update_series(sid, title="S", formats=["CBZ"], cover_source_id=ids[0], source_ids=ids)
    assert cat.card(sid).status is Status.READING and cat.card(sid).shelf_ids == frozenset()


def test_remove_series_only_manual(cat, st, tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    rid = cat.add_root(lib)
    manual, _ = make_series(cat, st, tmp_path, "M")
    scanned, _ = make_series(cat, st, tmp_path, "R", root_id=rid, base=lib)
    cat.remove_series(manual)
    cat.remove_series(scanned)
    assert [c.title for c in cat.cards()] == ["R"]


def test_ensure_series_adopts_root_and_marks_unavailable(cat, st, tmp_path):
    sid, _ = make_series(cat, st, tmp_path, "S")
    rid = cat.add_root(tmp_path)
    assert cat.ensure_series(tmp_path / "S", rid) == sid and cat.card(sid).root_id == rid
    shutil.rmtree(tmp_path / "S")
    assert not cat.card(sid).available


def test_relocate_root(cat, st, tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    rid = cat.add_root(old)
    sid, ids = make_series(cat, st, tmp_path, "S", root_id=rid, base=old)
    st.set_progress(ids[0], 4, False, 0.5)
    st.set_series_prefs(old / "S", SeriesPrefs("ltr", "spread"))
    new = tmp_path / "new"
    old.rename(new)
    assert not cat.roots()[0].available
    cat.relocate_root(rid, new)
    c = cat.card(sid)
    assert cat.roots()[0].path == new and c.path == new / "S" and c.available
    assert st.find_by_path(new / "S" / "c1.cbz").id == ids[0] and st.progress(ids[0]).position == 4
    assert st.series_prefs(new / "S") == SeriesPrefs("ltr", "spread")


@pytest.mark.skipif(sys.platform != "win32", reason="регистр путей различается только в Windows")
def test_same_series_in_other_case(cat, st, tmp_path):
    folder = tmp_path / "Берсерк"
    folder.mkdir()
    assert cat.ensure_series(folder) == cat.ensure_series(Path(str(folder).upper()))


def test_relocate_rejects_nesting(cat, st, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    (b / "sub").mkdir(parents=True)
    a.mkdir()
    rid = cat.add_root(a)
    cat.add_root(b)
    with pytest.raises(CatalogError, match="уже внутри папки библиотеки"):
        cat.relocate_root(rid, b / "sub")
    with pytest.raises(CatalogError, match="Внутри этой папки уже есть папка библиотеки"):
        cat.relocate_root(rid, tmp_path)
