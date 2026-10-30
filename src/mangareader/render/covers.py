"""Series and volume covers: the thumbnail of a source's first page, made in the background."""
from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

from mangareader.library.store import Store
from mangareader.render.loader import pil_to_qimage
from mangareader.render.thumbs import ThumbnailStore
from mangareader.sources import SourceContext, open_source

log = logging.getLogger("mangareader.covers")

COVER_CACHE = 300


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], None]):
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        self._fn()


class CoverLoader(QObject):
    cover_ready = Signal(int)
    _loaded = Signal(int, object)

    def __init__(self, store: Store, thumbs: ThumbnailStore, ctx: SourceContext, parent: QObject | None = None):
        super().__init__(parent)
        self._store = store
        self._thumbs = thumbs
        self._ctx = ctx
        self._images: OrderedDict[int, QImage] = OrderedDict()
        self._failed: set[int] = set()
        self.pending: set[int] = set()
        self._loaded.connect(self._on_loaded)

    def cover(self, source_id: int | None) -> QImage | None:
        if source_id is None:
            return None
        image = self._images.get(source_id)
        if image is not None:
            self._images.move_to_end(source_id)
            return image
        if source_id not in self._failed and source_id not in self.pending:
            self.pending.add(source_id)
            QThreadPool.globalInstance().start(_Task(lambda: self._load(source_id)))
        return None

    def _load(self, source_id: int) -> None:
        image = None
        try:
            record = self._store.source_by_id(source_id)
            if record is not None:
                thumb = self._thumbs.get(record.fingerprint, 0)
                if thumb is None:
                    with open_source(record.path, self._ctx) as source:
                        thumb = self._thumbs.create(source, 0, record.fingerprint)
                image = pil_to_qimage(thumb)
        except Exception as e:  # a missing, locked or broken file simply has no cover
            log.info("no cover for source %s: %r", source_id, e)
        try:
            self._loaded.emit(source_id, image)
        except RuntimeError:  # the loader is already gone
            pass

    def _on_loaded(self, source_id: int, image: QImage | None) -> None:
        self.pending.discard(source_id)
        if image is None:
            self._failed.add(source_id)
            return
        self._images[source_id] = image
        while len(self._images) > COVER_CACHE:
            self._images.popitem(last=False)
        self.cover_ready.emit(source_id)
