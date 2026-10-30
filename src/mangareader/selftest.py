"""`MangaReader --self-test`: checks that a build can open, render and export everything."""
from __future__ import annotations

import base64
import io
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

from mangareader.paths import DataLocation, find_7zz


def _page(i: int, fmt: str) -> bytes:
    img = Image.new("RGB", (600, 900), ((i * 53) % 256, (i * 97) % 256, (i * 31) % 256))
    ImageDraw.Draw(img).rectangle((10, 10, 60, 60), fill="white")
    buf = io.BytesIO()
    img.save(buf, fmt)
    return buf.getvalue()


def _no_window() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


def _check_zip(tmp: Path) -> Path:
    from mangareader.sources import SourceContext, open_source

    path = tmp / "sample.cbz"
    with zipfile.ZipFile(path, "w") as z:
        for i, fmt in enumerate(("JPEG", "PNG", "WEBP")):
            z.writestr(f"{i + 1:03}.{fmt.lower()}", _page(i, fmt))
    with open_source(path, SourceContext(tmp / "extract", find_7zz())) as source:
        assert len(source.pages) == 3
        for i in range(3):
            assert source.load_image(i).image.size == (600, 900)
    return path


def _check_7z(tmp: Path) -> None:
    from mangareader.sources import SourceContext, open_source

    exe = find_7zz()
    assert exe is not None, "7zz не найден"
    stage = tmp / "stage7z"
    stage.mkdir()
    (stage / "001.jpg").write_bytes(_page(1, "JPEG"))
    subprocess.run([str(exe), "a", "-t7z", str(tmp / "sample.cb7"), "001.jpg"], cwd=stage, check=True,
                   stdin=subprocess.DEVNULL, capture_output=True, **_no_window())
    with open_source(tmp / "sample.cb7", SourceContext(tmp / "extract", exe)) as source:
        assert source.read_original(0).data == (stage / "001.jpg").read_bytes()


# rar5-solid.rar from the rarfile test suite (ISC licence, see tests/fixtures/rar/README.md)
_RAR5_SAMPLE = base64.b64decode("UmFyIRoHAQAJ78hvCwEFBwQGAQGAgIAA3vVwchwCAroABIAQtoMCoua3xYAbAQpzdGVzdDEudHh0waw3REQj+iP2l/1iU1G+TJGBQQKMwQN5XL9Ho6otoDaT3aBYAEACANRQBHb2xH8y6p8ypcTM14PfABDoLYkcAgKNAASAELaDAqLmt8XAGwEKc3Rlc3QyLnR4dEUVCmABAAgD37f79vwdd1ZRAwUEAA==")


def _check_rar(tmp: Path) -> None:
    from mangareader.sources.sevenzip import SevenZip

    exe = find_7zz()
    assert exe is not None, "7zz не найден"
    (tmp / "sample.rar").write_bytes(_RAR5_SAMPLE)
    seven = SevenZip(exe)
    assert {e.path for e in seven.list(tmp / "sample.rar", None)} == {"stest1.txt", "stest2.txt"}
    assert seven.start_extract(tmp / "sample.rar", tmp / "rar-out", None).wait_file("stest2.txt", 30)


def _check_pdf(tmp: Path) -> None:
    import pymupdf

    from mangareader.sources import SourceContext, open_source

    jpeg = _page(2, "JPEG")
    doc = pymupdf.open()
    page = doc.new_page(width=144, height=216)
    page.insert_image(page.rect, stream=jpeg)
    doc.save(tmp / "sample.pdf")
    with open_source(tmp / "sample.pdf", SourceContext(tmp / "extract", None)) as source:
        assert source.read_original(0).data == jpeg


def _check_codec(fmt: str) -> None:
    from mangareader.imaging import decode

    assert decode(_page(3, fmt)).format == fmt


def _check_export(tmp: Path, cbz: Path) -> None:
    from mangareader.export.encoders import EncodeOptions, OutFormat, encode_fragment, encode_page
    from mangareader.export.model import load_page_image
    from mangareader.export.writer import unique_path, write_atomic
    from mangareader.sources import SourceContext, open_source

    out = tmp / "export"
    with open_source(cbz, SourceContext(tmp / "extract", None)) as source:
        page = load_page_image(source, 0)
        fragment = page.decoded.image.crop((5, 5, 205, 305))
        for fmt in OutFormat:
            for name, encoded in (("page", encode_page(page, EncodeOptions(fmt, 85))),
                                  ("fragment", encode_fragment(fragment, [page], EncodeOptions(fmt, 85)))):
                write_atomic(unique_path(out, f"{name}-{fmt.value}", encoded.ext), encoded.data)


def _check_window(tmp: Path, cbz: Path) -> None:
    from PySide6.QtWidgets import QApplication

    from mangareader.ui.main_window import MainWindow
    from mangareader.ui.reader.controller import make_services

    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = MainWindow(make_services(DataLocation(tmp / "data", False)))
    window.resize(900, 700)
    window.show()
    try:
        assert window.open_paths([cbz])
        deadline = time.monotonic() + 15
        while not window.view.page_item(0).has_scaled_image():
            assert time.monotonic() < deadline, "страница не отрисовалась за 15 секунд"
            app.processEvents()
            time.sleep(0.02)
        assert not window.grab().isNull()
    finally:
        window.close()


def run(report: Path) -> int:
    report.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    failed = False
    with tempfile.TemporaryDirectory(prefix="mangareader-selftest-") as tmp_name:
        tmp = Path(tmp_name)
        cbz: Path | None = None
        steps = [
            ("zip", lambda: _check_zip(tmp)),
            ("7z", lambda: _check_7z(tmp)),
            ("rar", lambda: _check_rar(tmp)),
            ("pdf", lambda: _check_pdf(tmp)),
            ("avif", lambda: _check_codec("AVIF")),
            ("jxl", lambda: _check_codec("JXL")),
            ("export", lambda: _check_export(tmp, cbz)),
            ("window", lambda: _check_window(tmp, cbz)),
        ]
        for name, step in steps:
            try:
                result = step()
                if name == "zip":
                    cbz = result
                lines.append(f"OK {name}")
            except Exception as e:  # report every failure, keep checking the rest
                failed = True
                lines.append(f"FAIL {name}: {e!r}")
                lines.append(traceback.format_exc())
    text = "\n".join(lines) + "\n"
    report.write_text(text, encoding="utf-8")
    if sys.stdout is not None:  # a windowed build has no console
        print(text)
    return 1 if failed else 0
