"""RAR/CBR and 7z/CB7 through the bundled 7-Zip console (7zz).

The archive listing is read on open; the archive is unpacked once, lazily, into a
temporary folder by a background 7zz process, and pages become readable as soon
as they are written (the only fast way for solid archives).
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from mangareader.sources.base import (Original, PageSource, PasswordRequired, SourceError, is_image_name,
                                      is_junk, make_page_ref)
from mangareader.sources.natsort import natural_path_key

EXTRACT_LIMIT = 4 * 1024**3
_PASSWORD_MARKERS = ("Wrong password", "Cannot open encrypted archive")

_open_dirs: set[Path] = set()
_open_dirs_lock = threading.Lock()


def _popen_kwargs() -> dict:
    kw: dict = {"stdin": subprocess.DEVNULL}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kw


@dataclass(frozen=True)
class ArchiveEntry:
    path: str
    size: int
    encrypted: bool


def _parse_listing(text: str) -> list[ArchiveEntry]:
    entries = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        fields = {}
        for line in block.split("\n"):
            key, sep, value = line.partition(" = ")
            if sep:
                fields[key.strip()] = value
        if "Path" not in fields or fields.get("Folder") == "+":
            continue
        size = fields.get("Size", "").strip()
        entries.append(ArchiveEntry(fields["Path"].replace("\\", "/"), int(size) if size.isdigit() else 0,
                                    fields.get("Encrypted") == "+"))
    return entries


class Extraction:
    """A running `7zz x`; tells when each file is completely written."""

    def __init__(self, args: list[str], dest: Path, sizes: Mapping[str, int]):
        self._dest = dest
        self._sizes = dict(sizes)
        self._cond = threading.Condition()
        self._complete: set[str] = set()
        self._all_ok = False
        self.done = False
        self.returncode: int | None = None
        self.error: str | None = None
        dest.mkdir(parents=True, exist_ok=True)
        self._proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **_popen_kwargs())
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _written(self, inner: str) -> bool:
        expected = self._sizes.get(inner)
        try:
            actual = (self._dest / inner).stat().st_size
        except OSError:
            return False
        return expected is None or actual == expected

    def _pump(self) -> None:
        wrong_password = False
        current = None
        for raw in self._proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith("- "):
                name = line[2:].replace("\\", "/")
                with self._cond:
                    if current and self._written(current):
                        self._complete.add(current)
                    current = name
                    self._cond.notify_all()
            elif any(m in line for m in _PASSWORD_MARKERS):
                wrong_password = True
        rc = self._proc.wait()
        with self._cond:
            if rc == 0:
                self._all_ok = True
            else:
                self._complete = {p for p in self._sizes if self._written(p)}
                self.error = "wrong_password" if wrong_password else "Не удалось распаковать архив"
            self.returncode = rc
            self.done = True
            self._cond.notify_all()

    def wait_file(self, inner_path: str, timeout: float | None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            while True:
                if inner_path in self._complete or (self.done and self._all_ok):
                    return True
                if self.done:
                    return False
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._cond.wait(remaining)

    def cancel(self) -> None:
        if self._proc.poll() is None:
            self._proc.kill()
        self._thread.join(timeout=5)


class SevenZip:
    def __init__(self, exe: Path):
        self.exe = Path(exe)

    def list(self, archive: Path, password: str | None) -> list[ArchiveEntry]:
        args = [str(self.exe), "l", "-slt", "-ba", "-sccUTF-8", f"-p{password or ''}", str(archive)]
        r = subprocess.run(args, capture_output=True, **_popen_kwargs())
        out = r.stdout.decode("utf-8", "replace")
        messages = out + "\n" + r.stderr.decode("utf-8", "replace")
        if any(m in messages for m in _PASSWORD_MARKERS):
            raise PasswordRequired(wrong=bool(password))
        if r.returncode != 0:
            raise SourceError("Архив повреждён или не поддерживается")
        entries = _parse_listing(out)
        if not password and any(e.encrypted for e in entries):
            raise PasswordRequired(wrong=False)
        return entries

    def start_extract(self, archive: Path, dest: Path, password: str | None,
                      sizes: Mapping[str, int] | None = None) -> Extraction:
        if sizes is None:
            sizes = {e.path: e.size for e in self.list(archive, password)}
        args = [str(self.exe), "x", "-y", "-aoa", f"-o{dest}", f"-p{password or ''}", "-bb1", "-bso1",
                "-bse1", "-bsp0", "-sccUTF-8", str(archive)]
        return Extraction(args, dest, sizes)


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def prune_extract_root(root: Path, limit_bytes: int = EXTRACT_LIMIT, in_use=frozenset()) -> None:
    if not root.is_dir():
        return
    dirs = [(d, d.stat().st_mtime, _dir_size(d)) for d in root.iterdir() if d.is_dir()]
    total = sum(size for _, _, size in dirs)
    for d, _, size in sorted(dirs, key=lambda item: item[1]):
        if total <= limit_bytes:
            break
        if d in in_use:
            continue
        shutil.rmtree(d, ignore_errors=True)
        total -= size


def clear_extract_root(root: Path) -> None:
    if not root.is_dir():
        return
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)


class SevenZipSource(PageSource):
    def __init__(self, path: Path, ctx, password: str | None = None):
        super().__init__(path)
        if ctx.seven_zip is None:
            raise SourceError("Не найден 7-Zip (7zz) рядом с программой — RAR и 7z не открываются")
        self._zip = SevenZip(ctx.seven_zip)
        self._extract_root = Path(ctx.extract_root)
        self._password = password
        entries = self._zip.list(self.path, password)
        self._sizes = {e.path: e.size for e in entries}
        images = sorted((e for e in entries if is_image_name(e.path) and not is_junk(e.path)),
                        key=lambda e: natural_path_key(e.path))
        self.pages = [make_page_ref(i, e.path, e.size) for i, e in enumerate(images)]
        self.file_size = self.path.stat().st_size
        self._lock = threading.Lock()
        self._extraction: Extraction | None = None
        self._dest: Path | None = None

    def _ensure_extraction(self) -> Extraction:
        with self._lock:
            if self._extraction is None:
                st = self.path.stat()
                key = hashlib.sha1(f"{self.path.resolve()}|{st.st_size}|{st.st_mtime}".encode()).hexdigest()[:16]
                self._dest = self._extract_root / f"{key}-{uuid.uuid4().hex[:6]}"
                self._extract_root.mkdir(parents=True, exist_ok=True)
                with _open_dirs_lock:
                    prune_extract_root(self._extract_root, in_use=set(_open_dirs))
                    _open_dirs.add(self._dest)
                self._extraction = self._zip.start_extract(self.path, self._dest, self._password, self._sizes)
            return self._extraction

    def _disk_path(self, inner: str) -> Path:
        base = self._dest.resolve()
        p = (base / inner).resolve()
        if not p.is_relative_to(base):
            raise SourceError("Недопустимый путь внутри архива")
        return p

    def _wait(self, i: int, timeout: float | None) -> bool:
        return self._ensure_extraction().wait_file(self.pages[i].inner_path, timeout)

    def wait_ready(self, i: int, timeout: float | None = None) -> bool:
        return self._wait(i, timeout)

    def read_original(self, i: int) -> Original:
        if not self._wait(i, None):
            if self._extraction.error == "wrong_password":
                raise PasswordRequired(wrong=True)
            raise SourceError("Не удалось распаковать страницу")
        try:
            return Original(self._disk_path(self.pages[i].inner_path).read_bytes(), self.pages[i].ext)
        except OSError as e:
            raise SourceError("Не удалось прочитать страницу: файл недоступен") from e

    def _read_head(self, i: int, n: int = 65536) -> bytes | None:
        if not self._wait(i, 0):
            return None
        try:
            with open(self._disk_path(self.pages[i].inner_path), "rb") as f:
                return f.read(n)
        except OSError:
            return None

    def page_size(self, i: int) -> tuple[int, int] | None:
        if not self._wait(i, 0):
            return None
        return super().page_size(i)

    def close(self) -> None:
        with self._lock:
            if self._extraction is not None:
                self._extraction.cancel()
                shutil.rmtree(self._dest, ignore_errors=True)
                with _open_dirs_lock:
                    _open_dirs.discard(self._dest)
                self._extraction = None
