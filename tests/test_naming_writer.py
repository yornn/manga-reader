import errno
import os

import pytest

from mangareader.export.naming import DEFAULT_TEMPLATE, NameFields, render_name, sanitize_filename
from mangareader.export.writer import ExportError, unique_path, write_atomic


def test_render_name():
    f = NameFields("Berserk", "3", "21", 45, 212)
    assert render_name(DEFAULT_TEMPLATE, f) == "Berserk – Том 03 – Гл 21 – стр 045"
    assert render_name(DEFAULT_TEMPLATE, NameFields("Berserk", None, "21.5", 7, 1200)) == "Berserk – Гл 21.5 – стр 0007"
    assert render_name("{файл}", NameFields("S", file="001")) == "001"


def test_render_name_drops_leading_missing_segment():
    assert render_name("Том {том} – {серия}", NameFields("S")) == "S"
    assert render_name("{серия} – {неизвестно}", NameFields("S")) == "S – {неизвестно}"


@pytest.mark.parametrize("raw,clean", [("a/b:c?", "a_b_c_"), ("CON", "_CON"), ("x. ", "x"), ("", "page")])
def test_sanitize(raw, clean):
    assert sanitize_filename(raw) == clean


def test_sanitize_length():
    assert len(sanitize_filename("я" * 400)) == 150


def test_unique_and_atomic(tmp_path):
    write_atomic(unique_path(tmp_path, "p", ".png"), b"1")
    write_atomic(unique_path(tmp_path, "p", ".png"), b"2")
    assert sorted(f.name for f in tmp_path.iterdir()) == ["p (2).png", "p.png"]
    assert (tmp_path / "p (2).png").read_bytes() == b"2"


def test_write_error_is_russian(tmp_path, monkeypatch):
    def boom(*a):
        raise OSError(errno.ENOSPC, "full")
    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(ExportError, match="места"):
        write_atomic(tmp_path / "x.png", b"1")
    assert not list(tmp_path.iterdir())
