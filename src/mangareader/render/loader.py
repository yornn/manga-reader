"""Background loading of full pages, display-sized copies and thumbnails."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Hashable, Iterable

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

from mangareader.imaging import Decoded, resize_lanczos
from mangareader.render.cache import ImageCache, image_nbytes
from mangareader.render.thumbs import ThumbnailStore
from mangareader.sources.base import PageSource, SourceError

log = logging.getLogger("mangareader.loader")

PRIORITY_VISIBLE = 10
PRIORITY_PREFETCH = 0
PRIORITY_THUMB = -5


def pil_to_qimage(img: Image.Image) -> QImage:
    if img.mode == "LA":
        img = img.convert("RGBA")
    elif img.mode not in ("L", "RGB", "RGBA"):
        img = img.convert("RGB")
    fmt, channels = {"L": (QImage.Format_Grayscale8, 1), "RGB": (QImage.Format_RGB888, 3),
                     "RGBA": (QImage.Format_RGBA8888, 4)}[img.mode]
    data = img.tobytes()
    return QImage(data, img.width, img.height, img.width * channels, fmt).copy()


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], None]):
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        self._fn()


class PageLoader(QObject):
    full_ready = Signal(str, int)
    scaled_ready = Signal(str, int)
    thumb_ready = Signal(str, int)
    failed = Signal(str, int, str)
    size_known = Signal(str, int, int, int)

    def __init__(self, cache: ImageCache, thumbs: ThumbnailStore, parent: QObject | None = None):
        super().__init__(parent)
        self._cache = cache
        self._thumbs = thumbs
        self._pool = QThreadPool.globalInstance()
        self._sources: dict[str, tuple[PageSource, str]] = {}
        self._pending: set[Hashable] = set()
        self._errors: dict[tuple[str, int], str] = {}
        self._lock = threading.Lock()

    # -- registration ---------------------------------------------------------
    def register(self, key: str, source: PageSource, fingerprint: str) -> None:
        with self._lock:
            self._sources[key] = (source, fingerprint)

    def unregister(self, key: str) -> None:
        with self._lock:
            self._sources.pop(key, None)
            self._errors = {k: v for k, v in self._errors.items() if k[0] != key}
        self._cache.discard_where(lambda k: isinstance(k, tuple) and len(k) > 1 and k[1] == key)

    def _source(self, key: str) -> tuple[PageSource, str] | None:
        with self._lock:
            return self._sources.get(key)

    def error(self, key: str, page: int) -> str | None:
        with self._lock:
            return self._errors.get((key, page))

    # -- scheduling -------------------------------------------------------------
    def _schedule(self, task_key: Hashable, fn: Callable[[], None], priority: int) -> None:
        with self._lock:
            if task_key in self._pending:
                return
            self._pending.add(task_key)

        def run() -> None:
            try:
                fn()
            except Exception:  # never let a worker crash the app
                log.exception("background task %s failed", task_key)
            finally:
                with self._lock:
                    self._pending.discard(task_key)
        self._pool.start(_Task(run), priority)

    def _ensure_full(self, key: str, page: int) -> Decoded | None:
        cached = self._cache.get(("full", key, page))
        if cached is not None:
            return cached
        entry = self._source(key)
        if entry is None:
            return None
        try:
            decoded = entry[0].load_image(page)
        except SourceError as e:
            message = str(e)
        except Exception:
            log.exception("loading page %s of %s failed", page, key)
            message = "Не удалось прочитать страницу"
        else:
            if self._source(key) is entry:
                self._cache.put(("full", key, page), decoded, image_nbytes(decoded.image))
                with self._lock:
                    self._errors.pop((key, page), None)
                self.size_known.emit(key, page, decoded.image.width, decoded.image.height)
                self.full_ready.emit(key, page)
            return decoded
        with self._lock:
            self._errors[(key, page)] = message
        self.failed.emit(key, page, message)
        return None

    # -- public requests ----------------------------------------------------------
    def full(self, key: str, page: int) -> Decoded | None:
        cached = self._cache.get(("full", key, page))
        if cached is None:
            self._schedule(("full", key, page), lambda: self._ensure_full(key, page), PRIORITY_VISIBLE)
        return cached

    def prefetch(self, key: str, pages: Iterable[int]) -> None:
        for page in pages:
            if self._cache.get(("full", key, page)) is None:
                self._schedule(("full", key, page), lambda p=page: self._ensure_full(key, p), PRIORITY_PREFETCH)

    def scaled(self, key: str, page: int, w: int, h: int) -> QImage | None:
        cache_key = ("scaled", key, page, w, h)
        cached = self._cache.get(cache_key)
        if cached is None:
            self._schedule(cache_key, lambda: self._make_scaled(key, page, w, h), PRIORITY_VISIBLE)
        return cached

    def _make_scaled(self, key: str, page: int, w: int, h: int) -> None:
        decoded = self._ensure_full(key, page)
        if decoded is None or w <= 0 or h <= 0:
            return
        img = decoded.image
        if img.size != (w, h):
            img = resize_lanczos(img, w, h)
        q = pil_to_qimage(img)
        cache_key = ("scaled", key, page, w, h)
        if self._source(key) is None:
            return
        self._cache.discard_where(lambda k: isinstance(k, tuple) and k[:3] == ("scaled", key, page) and k != cache_key)
        self._cache.put(cache_key, q, image_nbytes(q))
        self.scaled_ready.emit(key, page)

    def thumbnail(self, key: str, page: int) -> QImage | None:
        cache_key = ("thumb", key, page)
        cached = self._cache.get(cache_key)
        if cached is None:
            self._schedule(cache_key, lambda: self._make_thumb(key, page), PRIORITY_THUMB)
        return cached

    def _make_thumb(self, key: str, page: int) -> None:
        entry = self._source(key)
        if entry is None:
            return
        source, fingerprint = entry
        try:
            img = self._thumbs.get(fingerprint, page) or self._thumbs.create(source, page, fingerprint)
        except SourceError:
            return
        q = pil_to_qimage(img)
        if self._source(key) is entry:
            self._cache.put(("thumb", key, page), q, image_nbytes(q))
            self.thumb_ready.emit(key, page)

    def probe_sizes(self, key: str) -> None:
        def run() -> None:
            entry = self._source(key)
            if entry is None:
                return
            for page in range(len(entry[0].pages)):
                if self._source(key) is not entry:
                    return
                size = entry[0].page_size(page)
                if size:
                    self.size_known.emit(key, page, size[0], size[1])
        self._schedule(("sizes", key), run, PRIORITY_PREFETCH)
