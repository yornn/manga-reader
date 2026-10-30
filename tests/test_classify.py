from pathlib import Path

import pytest

from helpers import encode, page_image
from mangareader.library.classify import (SourceInfo, chapter_spans, classify_series, extract_number,
                                          find_series_root, internal_chapters, name_kind, suggest_chapter_number)
from mangareader.library.model import ChapterMark, ChapterSpan, Kind
from mangareader.sources.base import PageRef, SourceError

TINY_PNG = encode(page_image(1, (8, 8)), "PNG")


def touch(root: Path, rels):
    for rel in rels:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(TINY_PNG if p.suffix.lower() in {".jpg", ".png"} else b"x")


def fake_probe(pages, default, override=None, fail=frozenset(), locked=frozenset()):
    override = override or {}

    def probe(path: Path) -> SourceInfo:
        if path.name in fail:
            raise SourceError("битый")
        if path.name in locked:
            return SourceInfo(0, (), None, (), None, locked=True)
        return SourceInfo(pages.get(path.name, default), (), override.get(path.name), (), None)
    return probe


@pytest.mark.parametrize("name,kind", [
    ("Berserk v03", Kind.VOLUME), ("Vol.3", Kind.VOLUME), ("Том 2", Kind.VOLUME), ("第3巻", Kind.VOLUME),
    ("Tome 1", Kind.VOLUME), ("т. 3", Kind.VOLUME), ("Ch.021.5", Kind.CHAPTER), ("c015", Kind.CHAPTER),
    ("Глава 7", Kind.CHAPTER), ("第12話", Kind.CHAPTER), ("Episode 5", Kind.CHAPTER),
    ("Vol.03 Ch.021", Kind.CHAPTER), ("Berserk", None), ("cover", None), ("Chainsaw Man", None), ("Vivid", None)])
def test_name_kind(name, kind):
    assert name_kind(name) == kind


@pytest.mark.parametrize("name,kind,num", [
    ("Berserk v03 (2003) [Group]", Kind.VOLUME, "3"), ("Ch.021.5", Kind.CHAPTER, "21.5"),
    ("Vol.03 Ch.021", Kind.CHAPTER, "21"), ("Vol.03 Ch.021", Kind.VOLUME, "3"), ("第12話", None, "12"),
    ("Глава 007", None, "7"), ("Extra", None, None), ("0", None, "0"),
    ("Kaiju No. 8 - 012", Kind.CHAPTER, "12"), ("Kaiju No. 8 - 012", None, "12"), ("Berserk 03 (2003)", None, "3")])
def test_extract_number(name, kind, num):
    assert extract_number(name, kind) == num


def refs(folders):
    return [PageRef(i, f"{f}/{i}.jpg" if f else f"{i}.jpg", f, ".jpg", 1) for i, f in enumerate(folders)]


def test_internal_chapters():
    assert internal_chapters(refs(["w/ch1"] * 3 + ["w/ch2"] * 2)) == [
        ChapterSpan("Глава 1", 0, "1"), ChapterSpan("Глава 2", 3, "2")]
    assert internal_chapters(refs(["wrap"] * 5)) == []
    spans = internal_chapters(refs([""] + ["Prologue"] * 2 + ["Side"] * 2))
    assert [(s.title, s.start_page) for s in spans] == [("Начало", 0), ("Prologue", 1), ("Side", 3)]


def test_marks_become_chapters():
    spans = chapter_spans([], [ChapterMark(5, "1"), ChapterMark(30, "2", "Битва")])
    assert [(s.title, s.start_page, s.is_mark) for s in spans] == [
        ("Начало", 0, False), ("Глава 1", 5, True), ("Глава 2 — Битва", 30, True)]
    assert suggest_chapter_number(spans, 40) == "3" and suggest_chapter_number([], 0) == "1"
    assert suggest_chapter_number([ChapterSpan("Глава 21.5", 0, "21.5")], 3) == "22"


def test_mark_overrides_internal_span_on_same_page():
    internal = [ChapterSpan("Глава 1", 0, "1"), ChapterSpan("Глава 2", 3, "2")]
    spans = chapter_spans(internal, [ChapterMark(3, "2", "Новое")])
    assert [(s.title, s.is_mark) for s in spans] == [("Глава 1", False), ("Глава 2 — Новое", True)]


def test_layout_mixed(tmp_path):                                # раскладки A–D и мусор (Review Focus 3)
    touch(tmp_path, ["Vol 01.cbz", "Vol 02/c010.cbz", "c020.cbz", "c011.cbz", "readme.txt", "notes.nfo",
                     "empty.zip", ".hidden/x.cbz", "__MACOSX/y.cbz", "ch05/001.jpg", "big.cbz", "small.cbz"])
    tree = classify_series(tmp_path, fake_probe({"empty.zip": 0, "big.cbz": 150, "small.cbz": 20}, default=40))
    assert [n.title for n in tree.nodes] == ["Том 1", "Том 2", "big", "Глава 5", "Глава 11", "Глава 20", "small"]
    assert tree.nodes[1].folder == tmp_path / "Vol 02" and tree.nodes[1].entries[0].in_volume_folder
    assert tree.nodes[1].entries[0].kind == Kind.CHAPTER and tree.nodes[1].entries[0].title == "Глава 10"
    names = [e.path.name for e in tree.reading_order()]
    assert not {"readme.txt", "notes.nfo", "empty.zip", "x.cbz", "y.cbz"} & set(names)
    assert tree.title == tmp_path.name and tree.index_of(tmp_path / "c011.cbz") == 4


def test_volume_with_internal_chapters_and_marks(tmp_path):
    touch(tmp_path, ["Something.cbz", "Other.cbz"])
    internal = (ChapterSpan("Глава 1", 0, "1"), ChapterSpan("Глава 2", 3, "2"))

    def probe(path):
        if path.name == "Something.cbz":
            return SourceInfo(10, internal, None, (), 7)
        return SourceInfo(10, (), None, (ChapterMark(4, "1"),), 8)
    tree = classify_series(tmp_path, probe)
    by_name = {e.path.name: e for e in tree.reading_order()}
    assert by_name["Something.cbz"].kind == Kind.VOLUME and by_name["Something.cbz"].record_id == 7
    assert [c.title for c in by_name["Something.cbz"].chapters] == ["Глава 1", "Глава 2"]
    assert by_name["Other.cbz"].kind == Kind.CHAPTER and by_name["Other.cbz"].chapters == []


def test_override_failed_locked(tmp_path):
    touch(tmp_path, ["Vol 01.cbz", "bad.cbz", "locked.cbr"])
    probe = fake_probe({}, default=200, override={"Vol 01.cbz": Kind.CHAPTER}, fail={"bad.cbz"},
                       locked={"locked.cbr"})
    tree = classify_series(tmp_path, probe)
    assert tree.failed[0][0].name == "bad.cbz" and tree.failed[0][1] == "битый"
    assert [(e.path.name, e.kind, e.locked) for e in tree.reading_order()] == [
        ("Vol 01.cbz", Kind.CHAPTER, False), ("locked.cbr", Kind.CHAPTER, True)]


def test_find_series_root(tmp_path):
    touch(tmp_path, ["Berserk/Vol 01/ch01.cbz", "Berserk/Berserk v02.cbz", "S/01/ch01.cbz", "S/01/ch02.cbz",
                     "T/01/x.cbz"])
    assert find_series_root(tmp_path / "Berserk/Vol 01/ch01.cbz") == tmp_path / "Berserk"
    assert find_series_root(tmp_path / "Berserk/Berserk v02.cbz") == tmp_path / "Berserk"
    assert find_series_root(tmp_path / "S/01/ch01.cbz") == tmp_path / "S"
    assert find_series_root(tmp_path / "T/01/x.cbz") == tmp_path / "T/01"


def test_unexpected_probe_error_does_not_sink_scan(tmp_path):
    touch(tmp_path, ["c001.cbz", "c002.cbz"])

    def probe(path):
        if path.name == "c001.cbz":
            raise RuntimeError("code=8: opening and closing tag mismatch")
        return SourceInfo(10, (), None, (), None)
    tree = classify_series(tmp_path, probe)
    assert [e.path.name for e in tree.reading_order()] == ["c002.cbz"]
    assert tree.failed[0][0].name == "c001.cbz" and tree.failed[0][1]
