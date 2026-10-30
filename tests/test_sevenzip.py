import os
from pathlib import Path
import shutil
import time

import pytest

from helpers import RAR_DIR, encode, make_7z, page_image
from mangareader.paths import find_7zz
from mangareader.sources import SourceContext, open_source
from mangareader.sources.base import PasswordRequired, SourceError
from mangareader.sources.sevenzip import SevenZip, SevenZipSource, clear_extract_root, prune_extract_root

SUBDIRS = {"sub/dir2/file2.txt", "sub/with space/long fn.txt", "sub/üȵĩöḋè/file.txt", "sub/dir1/file1.txt"}


@pytest.mark.parametrize("name", ["rar3-subdirs.rar", "rar5-subdirs.rar"])
def test_list_rar(name):
    entries = SevenZip(find_7zz()).list(RAR_DIR / name, None)
    assert {e.path for e in entries} == SUBDIRS
    assert {e.path: e.size for e in entries}["sub/dir2/file2.txt"] == 6


def test_rar_passwords():
    z = SevenZip(find_7zz())
    with pytest.raises(PasswordRequired) as e1:
        z.list(RAR_DIR / "rar5-psw.rar", None)
    with pytest.raises(PasswordRequired) as e2:
        z.list(RAR_DIR / "rar5-hpsw.rar", None)
    with pytest.raises(PasswordRequired) as e3:
        z.list(RAR_DIR / "rar5-hpsw.rar", "wrong")
    assert (e1.value.wrong, e2.value.wrong, e3.value.wrong) == (False, False, True)
    assert len(z.list(RAR_DIR / "rar5-hpsw.rar", "password")) == 2


def test_extract_solid_rar(tmp_path):
    ex = SevenZip(find_7zz()).start_extract(RAR_DIR / "rar5-solid.rar", tmp_path / "x", None)
    assert ex.wait_file("stest2.txt", 30) and (tmp_path / "x/stest2.txt").stat().st_size == 2048
    assert ex.wait_file("stest1.txt", 30) and ex.done and ex.returncode == 0


def test_extract_wrong_password(tmp_path):
    sizes = {"stest1.txt": 2048, "stest2.txt": 2048}      # listing would already reject the password
    ex = SevenZip(find_7zz()).start_extract(RAR_DIR / "rar5-psw.rar", tmp_path / "x", "nope", sizes)
    assert not ex.wait_file("stest1.txt", 30) and ex.error == "wrong_password"


def test_7z_source_pages_lazy_and_cleanup(tmp_path, ctx):
    files = {"ch1/001.jpg": encode(page_image(1), "JPEG"), "ch10/001.jpg": encode(page_image(2), "JPEG"),
             "ch2/001.png": encode(page_image(3), "PNG"), "info.txt": b"x"}
    src = open_source(make_7z(tmp_path / "Манга" / "日本語.cb7", files), ctx)       # Review Focus 2
    assert isinstance(src, SevenZipSource)
    assert [p.inner_path for p in src.pages] == ["ch1/001.jpg", "ch2/001.png", "ch10/001.jpg"]
    assert not any(ctx.extract_root.glob("*"))                     # распаковка ещё не началась
    assert src.read_original(2).data == files["ch10/001.jpg"]
    assert src.load_image(1).image.size == (600, 900) and src.page_size(1) == (600, 900)
    dest = next(ctx.extract_root.iterdir())
    src.close()
    assert not dest.exists()


def test_7z_header_password(tmp_path, ctx):
    arc = make_7z(tmp_path / "p.7z", {"1.jpg": encode(page_image(1), "JPEG")}, password="pw")
    with pytest.raises(PasswordRequired):
        open_source(arc, ctx)
    assert len(open_source(arc, ctx, password="pw").pages) == 1


def test_truncated_7z(tmp_path, ctx):                          # Review Focus 4
    arc = make_7z(tmp_path / "t.7z", {f"{i}.png": encode(page_image(i), "PNG") for i in range(5)})
    arc.write_bytes(arc.read_bytes()[: arc.stat().st_size // 2])
    with pytest.raises(SourceError) as e:
        open_source(arc, ctx)
    assert not isinstance(e.value, PasswordRequired)


def test_prune(tmp_path):
    for i, age in enumerate([300, 200, 100]):
        d = tmp_path / f"d{i}"
        d.mkdir()
        (d / "f").write_bytes(b"0" * 3_000_000)
        os.utime(d, (time.time() - age, time.time() - age))
    prune_extract_root(tmp_path, limit_bytes=5_000_000, in_use={tmp_path / "d0"})
    assert sorted(p.name for p in tmp_path.iterdir()) == ["d0"]


def test_clear(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a/f").write_bytes(b"1")
    clear_extract_root(tmp_path)
    assert not any(tmp_path.iterdir())


def test_no_7zz(tmp_path):
    shutil.copy(RAR_DIR / "rar5-solid.rar", tmp_path / "a.cbr")
    with pytest.raises(SourceError, match="7-Zip"):
        open_source(tmp_path / "a.cbr", SourceContext(tmp_path / "e", None))


def test_read_after_close_does_not_restart_extraction(tmp_path, ctx):
    arc = make_7z(tmp_path / "a.cb7", {"1.png": encode(page_image(1), "PNG")})
    src = open_source(arc, ctx)
    src.read_original(0)
    src.close()
    with pytest.raises(SourceError):
        src.read_original(0)
    assert src.page_size(0) is None
    assert not any(ctx.extract_root.iterdir())


def test_second_instance_keeps_running_extraction(tmp_path):
    from mangareader.sources.sevenzip import claim_extract_dir, release_extract_dir
    root = tmp_path / "extract"
    first = claim_extract_dir(root)
    (first.path / "x").mkdir()
    (first.path / "x" / "f").write_bytes(b"1")
    (root / "leftover").mkdir()                      # left by a crashed run, nobody holds it
    second = claim_extract_dir(root)                 # another program start cleans only stale folders
    assert (first.path / "x" / "f").exists() and not (root / "leftover").exists()
    assert first.path != second.path
    release_extract_dir(first)
    assert not first.path.exists() and second.path.exists()
    release_extract_dir(second)


def test_services_use_own_extract_folder(tmp_path):
    from mangareader.paths import resolve_data_location
    from mangareader.ui.reader.controller import make_services
    data = resolve_data_location()
    a, b = make_services(data), make_services(data)
    assert a.ctx.extract_root.parent == data.extract and a.ctx.extract_root != b.ctx.extract_root
    assert a.ctx.extract_root.exists()


def test_resolve_names_renamed_by_7zip_on_windows(tmp_path):
    from mangareader.sources.sevenzip import resolve_extracted
    for rel in ("Ch 1_ Start/001.png", "Wait.._/x.png", "_CON/y.png"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"1")
    assert resolve_extracted(tmp_path, "Ch 1: Start/001.png") == tmp_path / "Ch 1_ Start" / "001.png"
    assert resolve_extracted(tmp_path, "Wait.../x.png") == tmp_path / "Wait.._" / "x.png"
    assert resolve_extracted(tmp_path, "CON/y.png") == tmp_path / "_CON" / "y.png"
    assert resolve_extracted(tmp_path, "missing.png") is None


def test_archive_with_windows_unsafe_names(tmp_path, ctx):   # renamed on Windows, kept on Linux
    shutil.copy(Path(__file__).parent / "fixtures" / "odd-names.7z", tmp_path / "odd.cb7")
    src = open_source(tmp_path / "odd.cb7", ctx)
    assert len(src.pages) == 4
    assert all(src.load_image(i).image.size == (40, 60) for i in range(4))


def test_wrong_password_rejected_when_only_data_is_encrypted(tmp_path, ctx):
    z = SevenZip(find_7zz())
    with pytest.raises(PasswordRequired) as e:
        z.list(RAR_DIR / "rar5-psw.rar", "wrong")
    assert e.value.wrong
    assert len(z.list(RAR_DIR / "rar5-psw.rar", "password")) == 2
    arc = make_7z(tmp_path / "e.cbz", {"1.jpg": encode(page_image(1), "JPEG")}, password="pw", fmt="zip")
    with pytest.raises(PasswordRequired) as e2:
        open_source(arc, ctx, password="WRONG")
    assert e2.value.wrong
