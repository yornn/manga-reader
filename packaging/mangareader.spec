# PyInstaller build of the portable folder: dist/MangaReader/MangaReader(.exe)
# Run from the repository root:  pyinstaller packaging/mangareader.spec --noconfirm
import importlib.resources
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
BIN = Path(str(importlib.resources.files("py7zz") / "bin"))
TOOLS = ["7zz.exe", "7z.dll"] if sys.platform == "win32" else ["7zz"]

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=[(str(BIN / name), "tools") for name in TOOLS if (BIN / name).exists()],
    datas=[],
    hiddenimports=["pillow_jxl"],
    # PyMuPDF 2.0 installs an optional ML layout analyser (pymupdf.layout + onnxruntime + numpy) and
    # imports it inside try/except ImportError; the reader does not need it, so it is left out.
    excludes=["tkinter", "pytest", "pytestqt", "PyInstaller", "pymupdf.layout", "pymupdf4llm", "pymupdf_layout",
              "onnxruntime", "numpy", "networkx", "psutil", "tabulate", "yaml"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MangaReader",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="MangaReader")
