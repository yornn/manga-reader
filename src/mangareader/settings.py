"""User settings stored as settings.json in the data folder (never the registry)."""
from __future__ import annotations

import dataclasses
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("mangareader.settings")

RECENT_LIMIT = 10


@dataclass
class ExportPrefs:
    fmt: str = "original"
    quality: int = 92
    preset: str = "high"
    resize_mode: str = "original"
    resize_value: int = 100
    spread_layout: str = "separate"
    folder: str = ""
    template: str = "{серия} – Том {том} – Гл {глава} – стр {страница}"


@dataclass
class Settings:
    theme: str = "dark"
    cache_mb: int = 1024
    recent: list[str] = field(default_factory=list)
    export: ExportPrefs = field(default_factory=ExportPrefs)
    book_font_size: float = 12.0
    sidebar_visible: bool = True
    window_geometry: str = ""

    def add_recent(self, path: str) -> None:
        self.recent = [path] + [p for p in self.recent if p != path]
        del self.recent[RECENT_LIMIT:]


def _known(cls, data: dict) -> dict:
    names = {f.name for f in dataclasses.fields(cls)}
    return {k: v for k, v in data.items() if k in names}


def load_settings(path: Path) -> Settings:
    if not path.exists():
        return Settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("settings root is not an object")
        export = ExportPrefs(**_known(ExportPrefs, data.get("export") or {}))
        values = _known(Settings, data)
        values["export"] = export
        return Settings(**values)
    except (ValueError, TypeError) as e:
        log.warning("settings file %s is corrupt (%s); using defaults", path, e)
        try:
            os.replace(path, path.with_name(path.name + ".bad"))
        except OSError:
            pass
        return Settings()


def save_settings(settings: Settings, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(dataclasses.asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
