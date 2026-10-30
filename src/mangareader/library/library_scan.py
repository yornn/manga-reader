"""Scanning library folders into series, and deciding which series an opened file belongs to."""
from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from mangareader.library.catalog import Catalog, Root, series_formats
from mangareader.library.classify import SeriesTree, find_series_root, is_inside, is_visible, is_volume_folder
from mangareader.library.scanner import scan_series
from mangareader.library.store import Store
from mangareader.sources import SourceContext
from mangareader.sources.detect import SOURCE_EXTS
from mangareader.sources.folder import has_direct_images
from mangareader.sources.natsort import natural_key

log = logging.getLogger("mangareader.library_scan")

DOCUMENT_EXTS = frozenset({".pdf", ".epub", ".fb2", ".mobi", ".xps", ".oxps", ".txt"})
UNREADABLE = "Файл повреждён или не поддерживается"


@dataclass
class ScanReport:
    series_ids: list[int] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)


def series_candidates(root: Path) -> list[Path]:
    try:
        children = sorted(Path(root).iterdir(), key=lambda p: natural_key(p.name))
    except OSError:
        return []
    found = []
    for child in children:
        if not is_visible(child):
            continue
        if child.is_dir() or (child.is_file() and child.suffix.lower() in SOURCE_EXTS):
            found.append(child)
    return found


def record_tree(catalog: Catalog, series_id: int, tree: SeriesTree) -> None:
    entries = tree.reading_order()
    source_ids = [e.record_id for e in entries if e.record_id is not None]
    cover = next((e.record_id for e in entries if e.record_id is not None and not e.locked), None)
    catalog.update_series(series_id, title=tree.title, formats=series_formats(e.path for e in entries),
                          cover_source_id=cover, source_ids=source_ids)


def scan_root(catalog: Catalog, store: Store, ctx: SourceContext, root: Root,
              on_series: Callable[[int], None] = lambda _: None,
              cancelled: Callable[[], bool] = lambda: False) -> ScanReport:
    report = ScanReport()
    if not root.available:
        return report
    for candidate in series_candidates(root.path):
        if cancelled():
            break
        try:
            tree = scan_series(candidate, store, ctx)
            report.failed.extend(tree.failed)
            if not tree.nodes:
                continue
            series_id = catalog.ensure_series(candidate, root.id)
            record_tree(catalog, series_id, tree)
        except Exception as e:  # one bad folder must not stop the rest of the library
            log.warning("cannot scan %s: %r", candidate, e)
            report.failed.append((candidate, UNREADABLE))
            continue
        report.series_ids.append(series_id)
        on_series(series_id)
    return report


def scan_library(catalog: Catalog, store: Store, ctx: SourceContext,
                 on_series: Callable[[int], None] = lambda _: None,
                 cancelled: Callable[[], bool] = lambda: False) -> ScanReport:
    report = ScanReport()
    for root in catalog.roots():
        if cancelled():
            break
        part = scan_root(catalog, store, ctx, root, on_series, cancelled)
        report.series_ids.extend(part.series_ids)
        report.failed.extend(part.failed)
    return report


def series_path_for(path: Path, roots: Sequence[Root]) -> tuple[Path, int | None]:
    path = Path(path)
    for root in roots:
        if is_inside(path, root.path):
            return root.path / Path(os.path.relpath(path, root.path)).parts[0], root.id
    if path.suffix.lower() in DOCUMENT_EXTS and not path.is_dir():
        return path, None
    if path.is_dir() and not has_direct_images(path):
        return (path.parent if is_volume_folder(path) else path), None
    return find_series_root(path), None
