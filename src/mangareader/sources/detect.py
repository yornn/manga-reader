"""Format detection by file signature (a .cbz that is really a RAR is common)."""
from __future__ import annotations

import zipfile
from enum import StrEnum
from pathlib import Path


class Format(StrEnum):
    FOLDER = "folder"
    ZIP = "zip"
    RAR = "rar"
    SEVENZIP = "7z"
    PDF = "pdf"
    EPUB = "epub"
    FB2 = "fb2"
    MOBI = "mobi"
    XPS = "xps"
    TXT = "txt"
    UNKNOWN = "unknown"


# Files that count as sources in a series folder; .txt is excluded (spec 5.1, rule 8).
SOURCE_EXTS = frozenset({".cbz", ".zip", ".cbr", ".rar", ".cb7", ".7z", ".pdf", ".epub",
                         ".fb2", ".mobi", ".xps", ".oxps"})
OPENABLE_EXTS = SOURCE_EXTS | {".txt"}

_BY_EXT = {".fb2": Format.FB2, ".mobi": Format.MOBI, ".xps": Format.XPS, ".oxps": Format.XPS,
           ".txt": Format.TXT}


def _is_epub(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            return zf.read("mimetype").strip() == b"application/epub+zip"
    except (KeyError, zipfile.BadZipFile, OSError, ValueError):
        return False


def detect_format(path: Path) -> Format:
    path = Path(path)
    if path.is_dir():
        return Format.FOLDER
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return Format.UNKNOWN
    if head.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        return Format.EPUB if _is_epub(path) else Format.ZIP
    if head.startswith(b"Rar!\x1a\x07"):
        return Format.RAR
    if head.startswith(b"7z\xbc\xaf\x27\x1c"):
        return Format.SEVENZIP
    if head.startswith(b"%PDF"):
        return Format.PDF
    return _BY_EXT.get(path.suffix.lower(), Format.UNKNOWN)
