"""Where the program keeps its data and finds bundled tools (portable layout)."""
from __future__ import annotations

import importlib.resources
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DataLocation:
    root: Path
    is_fallback: bool

    @property
    def db(self) -> Path:
        return self.root / "library.db"

    @property
    def settings_file(self) -> Path:
        return self.root / "settings.json"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def thumbs(self) -> Path:
        return self.cache / "thumbs"

    @property
    def extract(self) -> Path:
        return self.cache / "extract"

    @property
    def logs(self) -> Path:
        return self.root / "logs"


def app_dir() -> Path:
    """Folder of MangaReader.exe in a frozen build, repository root otherwise."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _is_writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f".write-test-{uuid.uuid4().hex}"
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def _user_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "MangaReader"
    return Path.home() / ".local" / "share" / "MangaReader"


def resolve_data_location() -> DataLocation:
    override = os.environ.get("MANGAREADER_DATA")
    if override:
        loc = DataLocation(Path(override), False)
    else:
        candidate = app_dir() / "data"
        if _is_writable(candidate):
            loc = DataLocation(candidate, False)
        else:
            loc = DataLocation(_user_data_dir(), True)
    loc.root.mkdir(parents=True, exist_ok=True)
    return loc


def _7zz_name() -> str:
    return "7zz.exe" if sys.platform == "win32" else "7zz"


def find_7zz() -> Path | None:
    override = os.environ.get("MANGAREADER_7ZZ")
    if override:
        candidate = Path(override)
    elif getattr(sys, "frozen", False):
        # PyInstaller keeps bundled files in sys._MEIPASS (the "_internal" folder next to the exe)
        candidate = Path(getattr(sys, "_MEIPASS", app_dir())) / "tools" / _7zz_name()
    else:
        try:
            candidate = Path(str(importlib.resources.files("py7zz") / "bin" / _7zz_name()))
        except ModuleNotFoundError:
            return None
    return candidate if candidate.is_file() else None
