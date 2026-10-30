import shutil
import sqlite3
import threading

import pytest

from helpers import make_zip
from mangareader.library import store
from mangareader.library.fingerprint import fingerprint
from mangareader.library.model import ChapterMark, ChapterSpan, Kind, Progress, SeriesPrefs
from mangareader.library.store import Store
from mangareader.sources import open_source


def test_fingerprint_ignores_path_but_not_content(tmp_path, ctx):
    a = make_zip(tmp_path / "a.cbz", {"1.png": b"x" * 10})
    b = tmp_path / "b.cbz"
    shutil.copy(a, b)
    c = make_zip(tmp_path / "c.cbz", {"1.png": b"x" * 11})
    fa, fb, fc = (fingerprint(open_source(p, ctx)) for p in (a, b, c))
    assert fa == fb != fc and len(fa) == 20


def test_register_progress_marks_prefs(tmp_path):
    st = Store(tmp_path / "library.db")
    f = tmp_path / "v.cbz"
    f.write_bytes(b"1")
    r = st.register(f, 1, 1.0, "fp", 10, (ChapterSpan("Глава 1", 0, "1"),))
    assert r.chapters == (ChapterSpan("Глава 1", 0, "1"),)
    assert st.register(f, 1, 2.0, "fp", 10, ()).id == r.id
    st.set_progress(r.id, 5, False)
    st.set_chapter_mark(r.id, ChapterMark(30, "2"))
    st.set_chapter_mark(r.id, ChapterMark(7, "1", "Пролог"))
    st.set_kind_override(r.id, Kind.CHAPTER)
    st.set_spread_offset(r.id, 1)
    st.set_series_prefs(tmp_path, SeriesPrefs("rtl", "spread"))
    rec = st.find_by_path(f)
    assert st.progress(r.id).position == 5 and not st.progress(r.id).finished
    assert [m.page_index for m in st.chapter_marks(r.id)] == [7, 30]
    assert st.chapter_marks(r.id)[0] == ChapterMark(7, "1", "Пролог")
    assert (rec.kind_override, rec.spread_offset, rec.chapters, rec.mtime) == (Kind.CHAPTER, 1, (), 2.0)
    assert st.series_prefs(tmp_path) == SeriesPrefs("rtl", "spread")
    st.delete_chapter_mark(r.id, 7)
    st.set_kind_override(r.id, None)
    assert [m.page_index for m in st.chapter_marks(r.id)] == [30] and st.find_by_path(f).kind_override is None


def test_latest_progress(tmp_path):
    st = Store(tmp_path / "library.db")
    ids = []
    for n in "abc":
        f = tmp_path / n
        f.write_bytes(b"1")
        ids.append(st.register(f, 1, 1.0, n, 1, ()).id)
    assert st.latest_progress(ids) is None
    st.set_progress(ids[2], 0, False)
    st.set_progress(ids[0], 0, False)
    assert st.latest_progress(ids) == ids[0] and st.latest_progress(ids[1:]) == ids[2]


def test_relink_after_rename(tmp_path):
    st = Store(tmp_path / "library.db")
    a = tmp_path / "a.cbz"
    a.write_bytes(b"1")
    r = st.register(a, 1, 1.0, "fp", 10, ())
    st.set_chapter_mark(r.id, ChapterMark(3, "1"))
    b = tmp_path / "Новое имя.cbz"
    a.rename(b)
    assert st.register(b, 1, 1.0, "fp", 10, ()).id == r.id and st.chapter_marks(r.id)
    assert st.find_by_path(a) is None and st.find_by_path(b).path == b


def test_no_relink_for_copies(tmp_path):
    st = Store(tmp_path / "library.db")
    a = tmp_path / "a.cbz"
    a.write_bytes(b"1")
    b = tmp_path / "b.cbz"
    b.write_bytes(b"1")
    assert st.register(a, 1, 1.0, "fp", 10, ()).id != st.register(b, 1, 1.0, "fp", 10, ()).id


def test_reopen_keeps_data(tmp_path):
    f = tmp_path / "v.cbz"
    f.write_bytes(b"1")
    st = Store(tmp_path / "library.db")
    rid = st.register(f, 1, 1.0, "fp", 10, ()).id
    st.set_progress(rid, 4, True)
    st.close()
    st2 = Store(tmp_path / "library.db")
    assert st2.progress(rid).position == 4 and st2.progress(rid).finished


def test_migration_makes_backup(tmp_path, monkeypatch):
    Store(tmp_path / "library.db").close()
    monkeypatch.setattr(store, "MIGRATIONS", store.MIGRATIONS + ["CREATE TABLE extra(x);"])
    Store(tmp_path / "library.db").close()
    assert (tmp_path / "library.db.bak").exists()


def test_corrupt_db_replaced(tmp_path):
    (tmp_path / "library.db").write_bytes(b"garbage" * 100)
    st = Store(tmp_path / "library.db")
    f = tmp_path / "x"
    f.write_bytes(b"1")
    assert st.register(f, 1, 1.0, "fp", 1, ()).id and list(tmp_path.glob("library.db.corrupt-*"))


def test_threads(tmp_path):
    st = Store(tmp_path / "library.db")
    f = tmp_path / "x"
    f.write_bytes(b"1")
    rid = st.register(f, 1, 1.0, "fp", 1, ()).id
    errors = []

    def work(n):
        try:
            for k in range(50):
                st.set_progress(rid, n * 100 + k, False)
                st.progress(rid)
        except Exception as e:  # pragma: no cover - reported below
            errors.append(e)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors


def test_migration_v1_keeps_progress_marks_and_fills_fraction(tmp_path):
    db = tmp_path / "library.db"
    conn = sqlite3.connect(db)
    conn.executescript(store.MIGRATIONS[0])
    conn.execute("PRAGMA user_version = 1")
    for sid, fp in ((1, "a"), (2, "b")):
        conn.execute("INSERT INTO sources(id, path, path_key, size, mtime, fingerprint, page_count, last_seen)"
                     " VALUES (?, ?, ?, 1, 1, ?, 10, 0)", (sid, fp, fp, fp))
    conn.execute("INSERT INTO progress VALUES (1, 4, 0, 1.0)")
    conn.execute("INSERT INTO progress VALUES (2, 9, 1, 2.0)")
    conn.execute("INSERT INTO chapter_marks VALUES (1, 3, '1', '')")
    conn.commit()
    conn.close()
    st = Store(db)
    assert st.progress(1) == Progress(4, False, 1.0, 0.5) and st.progress(2).fraction == 1.0
    assert st.chapter_marks(1) == [ChapterMark(3, "1")] and (tmp_path / "library.db.bak").exists()
    tables = {r[0] for r in st.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"roots", "series", "shelves", "shelf_series"} <= tables


def test_fraction_saved_and_clamped(tmp_path):
    st = Store(tmp_path / "library.db")
    f = tmp_path / "v.cbz"
    f.write_bytes(b"1")
    rid = st.register(f, 1, 1.0, "fp", 10, ()).id
    st.set_progress(rid, 3, False, 0.4)
    assert st.progress(rid).fraction == 0.4
    st.set_progress(rid, 9, True, 0.2)
    assert st.progress(rid).fraction == 1.0
    st.set_progress(rid, 1, False, 1.7)
    assert st.progress(rid).fraction == 1.0
    assert st.source_by_id(rid).path == f and st.source_by_id(rid + 100) is None


def test_transaction_rolls_back(tmp_path):
    st = Store(tmp_path / "library.db")
    with pytest.raises(RuntimeError):
        with st.transaction() as conn:
            conn.execute("INSERT INTO roots(path, path_key, added_at) VALUES ('r', 'r', 0)")
            raise RuntimeError
    assert st.query("SELECT COUNT(*) FROM roots") == [(0,)]
