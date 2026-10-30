"""Reading source info for classification, cached in the store by size and mtime."""
from __future__ import annotations

from pathlib import Path

from mangareader.library.classify import SeriesTree, SourceInfo, classify_series, internal_chapters
from mangareader.library.fingerprint import fingerprint
from mangareader.library.model import SourceRecord
from mangareader.library.store import Store
from mangareader.sources import SourceContext, open_source
from mangareader.sources.base import PasswordRequired


class SourceProber:
    def __init__(self, store: Store, ctx: SourceContext):
        self._store = store
        self._ctx = ctx

    def _info(self, record: SourceRecord) -> SourceInfo:
        return SourceInfo(record.page_count, record.chapters, record.kind_override,
                          tuple(self._store.chapter_marks(record.id)), record.id)

    def __call__(self, path: Path) -> SourceInfo:
        path = Path(path)
        stat = None
        if not path.is_dir():
            stat = path.stat()
            record = self._store.find_by_path(path)
            if record and record.size == stat.st_size and record.mtime == stat.st_mtime:
                return self._info(record)
        try:
            source = open_source(path, self._ctx)
        except PasswordRequired:
            return SourceInfo(0, (), None, (), None, locked=True)
        try:
            size = stat.st_size if stat else source.file_size
            mtime = stat.st_mtime if stat else 0.0
            record = self._store.register(path, size, mtime, fingerprint(source), len(source.pages),
                                          tuple(internal_chapters(source.pages)))
        finally:
            source.close()
        return self._info(record)


def scan_series(root: Path, store: Store, ctx: SourceContext) -> SeriesTree:
    return classify_series(Path(root), SourceProber(store, ctx))
