"""ZIP/CBZ pages, including archives with legacy (Shift-JIS, CP866) file names."""
from __future__ import annotations

import re
import threading
import zipfile
import zlib
from pathlib import Path

from mangareader.sources.base import Original, PageSource, SourceError, is_image_name, is_junk, make_page_ref
from mangareader.sources.natsort import natural_path_key

_JAPANESE = re.compile(r"[぀-ヿ㐀-䶿一-鿿]")
_SUPPORTED_METHODS = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA}
_READ_ERRORS = (zipfile.BadZipFile, zlib.error, EOFError, OSError, NotImplementedError, RuntimeError)


def _decodes(raw_names: list[bytes], encoding: str) -> list[str] | None:
    try:
        return [n.decode(encoding) for n in raw_names]
    except UnicodeDecodeError:
        return None


def choose_zip_encoding(raw_names: list[bytes]) -> str:
    if _decodes(raw_names, "utf-8") is not None:
        return "utf-8"
    names = _decodes(raw_names, "cp932")
    if names is not None and any(_JAPANESE.search(n) for n in names):
        return "cp932"
    return "cp866"


def zip_needs_7z(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            return any(i.flag_bits & 0x1 or i.compress_type not in _SUPPORTED_METHODS for i in zf.infolist())
    except (zipfile.BadZipFile, OSError):
        return False


def _open_zip(path: Path) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(path)
        legacy = [i.orig_filename.encode("cp437") for i in zf.infolist() if not i.flag_bits & 0x800]
        if legacy:
            zf.close()
            zf = zipfile.ZipFile(path, metadata_encoding=choose_zip_encoding(legacy))
        return zf
    except (zipfile.BadZipFile, OSError, ValueError, UnicodeEncodeError) as e:
        raise SourceError("Архив повреждён или не поддерживается") from e


class ZipSource(PageSource):
    def __init__(self, path: Path):
        super().__init__(path)
        self._zf = _open_zip(self.path)
        self._lock = threading.Lock()
        members = [i for i in self._zf.infolist()
                   if not i.is_dir() and is_image_name(i.filename) and not is_junk(i.filename)]
        members.sort(key=lambda i: natural_path_key(i.filename))
        self._names = [i.filename for i in members]
        self.pages = [make_page_ref(n, i.filename, i.file_size) for n, i in enumerate(members)]
        self.file_size = self.path.stat().st_size

    def read_original(self, i: int) -> Original:
        try:
            with self._lock:
                data = self._zf.read(self._names[i])
        except _READ_ERRORS as e:
            raise SourceError("Не удалось прочитать страницу: файл повреждён") from e
        return Original(data, self.pages[i].ext)

    def _read_head(self, i: int, n: int = 65536) -> bytes | None:
        try:
            with self._lock, self._zf.open(self._names[i]) as f:
                return f.read(n)
        except _READ_ERRORS as e:
            raise SourceError("Не удалось прочитать страницу: файл повреждён") from e

    def close(self) -> None:
        with self._lock:
            self._zf.close()
