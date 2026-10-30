import shutil

from helpers import encode, library, make_zip, page_image
from mangareader.library.catalog import Catalog, Root
from mangareader.library.library_scan import scan_library, series_path_for
from mangareader.library.store import Store


def test_series_from_root(tmp_path, ctx):
    st = Store(tmp_path / "db")
    cat = Catalog(st)
    lib = library(tmp_path)
    rid = cat.add_root(lib)
    report = scan_library(cat, st, ctx)
    cards = {c.title: c for c in cat.cards()}
    assert sorted(cards) == ["Artbook", "Berserk", "Ведьмак"] and len(report.series_ids) == 3
    assert cards["Berserk"].formats == ("CBZ",) and cards["Berserk"].pages_total == 6 and cards["Berserk"].sources == 2
    assert cards["Artbook"].formats == ("Папка",) and cards["Ведьмак"].formats == ("EPUB",)
    assert all(c.root_id == rid and c.cover_source_id for c in cards.values())


def test_rescan_keeps_vanished_series_and_missing_root(tmp_path, ctx):
    st = Store(tmp_path / "db")
    cat = Catalog(st)
    lib = library(tmp_path)
    cat.add_root(lib)
    scan_library(cat, st, ctx)
    shutil.rmtree(lib / "Berserk")
    scan_library(cat, st, ctx)
    assert not next(c for c in cat.cards() if c.title == "Berserk").available
    shutil.rmtree(lib)                                                   # the whole library folder is gone
    scan_library(cat, st, ctx)
    assert len(cat.cards()) == 3 and not cat.roots()[0].available


def test_broken_file_reported_others_scanned(tmp_path, ctx):
    st = Store(tmp_path / "db")
    cat = Catalog(st)
    lib = library(tmp_path)
    (lib / "Berserk" / "Vol 03.cbz").write_bytes(b"not a zip")
    cat.add_root(lib)
    report = scan_library(cat, st, ctx)
    assert [p.name for p, _ in report.failed] == ["Vol 03.cbz"] and len(cat.cards()) == 3


def test_cancelled_scan_stops(tmp_path, ctx):
    st = Store(tmp_path / "db")
    cat = Catalog(st)
    cat.add_root(library(tmp_path))
    assert scan_library(cat, st, ctx, cancelled=lambda: True).series_ids == [] and cat.cards() == []


def test_record_tree_unlinks_removed_sources(tmp_path, ctx):
    st = Store(tmp_path / "db")
    cat = Catalog(st)
    lib = library(tmp_path)
    cat.add_root(lib)
    scan_library(cat, st, ctx)
    (lib / "Berserk" / "Vol 02.cbz").unlink()
    scan_library(cat, st, ctx)
    assert next(c for c in cat.cards() if c.title == "Berserk").sources == 1


def test_series_path_for(tmp_path):
    lib = tmp_path / "lib"
    (lib / "S" / "Vol 1").mkdir(parents=True)
    root = Root(5, lib, 0.0)
    assert series_path_for(lib / "S" / "Vol 1" / "c1.cbz", [root]) == (lib / "S", 5)
    assert series_path_for(lib / "Книга.epub", [root]) == (lib / "Книга.epub", 5)
    dl = tmp_path / "Загрузки"
    dl.mkdir()
    assert series_path_for(dl / "Книга.epub", [root]) == (dl / "Книга.epub", None)
    assert series_path_for(dl / "c1.cbz", [root]) == (dl, None)
    vol = tmp_path / "Series" / "Том 1"
    vol.mkdir(parents=True)
    make_zip(vol / "Глава 1.cbz", {"1.png": encode(page_image(1), "PNG")})
    assert series_path_for(vol, [root]) == (tmp_path / "Series", None)


def test_import_recent_adds_series_once(tmp_path):
    from mangareader.library.library_scan import import_recent
    st = Store(tmp_path / "db")
    cat = Catalog(st)
    a = make_zip(tmp_path / "A" / "c1.cbz", {"1.png": encode(page_image(1), "PNG")})
    b = make_zip(tmp_path / "B" / "c1.cbz", {"1.png": encode(page_image(1), "PNG")})
    paths = [str(a), str(b), str(tmp_path / "gone.cbz")]
    assert import_recent(cat, paths) == 2
    assert sorted(c.title for c in cat.cards()) == ["A", "B"] and all(c.root_id is None for c in cat.cards())
    assert import_recent(cat, paths) == 0
