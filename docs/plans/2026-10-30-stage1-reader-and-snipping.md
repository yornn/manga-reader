# Этап 1 «Читалка и ножницы» — план реализации

**Goal:** Портативная программа для Windows (версия 0.1.0), которая открывает мангу и книги всех форматов из спецификации, показывает их в трёх режимах чтения с навигацией по томам и главам, позволяет вырезать фрагмент «ножницами» и сохранить страницу или фрагмент в любом формате.

**Architecture:** Python-пакет `mangareader` в `src/`. Логические слои (`imaging`, `sources`, `library`, `export`, `settings`, `paths`) не зависят от Qt и тестируются отдельно. Слой `render` (кэш и фоновая загрузка) и слой `ui` построены на PySide6. Все данные лежат в папке `data/` рядом с exe. Сборку делает PyInstaller на Windows-машине GitHub Actions.

**Tech Stack:** Python 3.13, PySide6-Essentials 6.12, PyMuPDF 2.0, Pillow 13.0 (+ pillow-jxl-plugin), 7-Zip `7zz` из py7zz 1.5, SQLite, pytest + pytest-qt, PyInstaller 6.22.

**Spec:** `docs/specs/2026-10-30-manga-reader-design.md` (этап 1 — раздел 14, п. 1). Спецификацию и план читать вместе.

## Global Constraints

- Python 3.13. Зависимости фиксированы точно: `PySide6-Essentials==6.12.0`, `pymupdf==2.0`, `pillow==13.0.0`, `pillow-jxl-plugin==1.3.8`, `py7zz==1.5.0`; для разработки `pytest==9.2.0`, `pytest-qt==4.5.0`, `pyinstaller==6.22.3`. Пакет `PySide6` целиком не ставить: он тянет WebEngine и добавляет сотни мегабайт.
- Модули `mangareader.imaging`, `sources`, `library`, `export`, `settings`, `paths`, `logging_setup` не импортируют Qt.
- Интерфейс только на русском. Строки в `ui/` оборачиваются в `self.tr(...)` (или `QCoreApplication.translate`). Сообщения исключений логики (`SourceError`, `ExportError`, `ImageDecodeError`) — готовые русские фразы для пользователя.
- Портативность: никаких записей в реестр, **`QSettings` не использовать** (в Windows он пишет в реестр). Все настройки хранятся в `data/settings.json`, база — в `data/library.db`.
- Каждый вызов `subprocess` передаёт `stdin=subprocess.DEVNULL`, а в Windows ещё `creationflags=subprocess.CREATE_NO_WINDOW`, иначе в оконной сборке мигает консоль.
- Пути на диске — `pathlib.Path`. Пути внутри архивов — строки с разделителем `/`.
- Методы `PageSource`, `Store` и `ImageCache` можно вызывать из любого потока: блокировка внутри.
- Код интерфейса вызывает диалоги и запись через атрибут модуля (`errors.ask_password(...)`, `errors.show_error(...)`, `chapter_mark_dialog.ask_chapter_mark(...)`, `writer.write_atomic(...)`), а не через `from … import`: тесты подменяют их через `monkeypatch`.
- Тесты запускаются командой `pytest -q` из корня проекта при `QT_QPA_PLATFORM=offscreen` (выставляется в `tests/conftest.py`).
- Версия программы `0.1.0` (`mangareader.__version__`).
- Сообщения коммитов на английском в стиле `feat: …` / `test: …` / `build: …`.
- Работа идёт в ветке `main`, после каждой задачи `git push origin main`.

## Review Focus

1. **Огромные raw-страницы.** PNG 12000×10000 (120 Мп) больше лимита Pillow против «бомб» (89 Мп) и должен открываться без ошибки. Тест в задаче 2.
2. **Не-ASCII и длинные пути.** Папки вида `Манга/日本語 漫画/` должны работать во всех источниках, в аргументах `7zz` и в папках распаковки. Тесты в задачах 3, 4 и 5.
3. **Мусор в папке серии.** `readme.txt`, `.nfo`, ZIP без картинок, скрытые папки и `__MACOSX` не должны становиться главами. Тест в задаче 8.
4. **Повреждённые и исчезнувшие файлы.** Обрезанный архив, битая страница внутри, файл удалён после открытия (вынули флешку): всегда `SourceError` с русским текстом, никаких «сырых» исключений, а в интерфейсе — заглушка вместо страницы. Тесты в задачах 3, 4, 5, 6 и 13.
5. **Параллельные чтения.** Фоновые потоки одновременно читают страницы одного ZIP или PDF: данные верны, падений нет. Тесты в задачах 5 и 6.

## Структура файлов

```
pyproject.toml  .gitignore  README.md
src/mangareader/
  __init__.py  __main__.py  app.py  paths.py  settings.py  logging_setup.py  imaging.py  selftest.py
  sources/   __init__.py base.py natsort.py detect.py folder.py sevenzip.py zip.py document.py
  library/   __init__.py model.py fingerprint.py store.py classify.py scanner.py
  export/    __init__.py model.py geometry.py encoders.py pdf.py naming.py writer.py
  render/    __init__.py cache.py thumbs.py loader.py
  ui/        __init__.py theme.py toast.py main_window.py
    reader/  __init__.py layout.py navigation.py view.py selection.py sidebar.py controller.py
    dialogs/ __init__.py save_dialog.py settings_dialog.py chapter_mark_dialog.py errors.py
tests/  conftest.py helpers.py test_*.py  fixtures/rar/{rar3-subdirs,rar5-subdirs,rar5-solid,rar5-psw,rar5-hpsw}.rar + README.md
packaging/  mangareader.spec  entry.py  build_windows.ps1
.github/workflows/  ci.yml  release.yml
```

---

### Task 1: Скелет проекта, пути, настройки, журнал, CI тестов

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/mangareader/__init__.py`, `src/mangareader/paths.py`, `src/mangareader/settings.py`, `src/mangareader/logging_setup.py`, `tests/conftest.py`, `tests/helpers.py`, `tests/test_paths.py`, `tests/test_settings.py`, `.github/workflows/ci.yml`

**Interfaces:**
- Produces:
  - `paths.DataLocation(root: Path, is_fallback: bool)` со свойствами `db`, `settings_file`, `cache`, `thumbs` (`cache/thumbs`), `extract` (`cache/extract`), `logs`
  - `paths.resolve_data_location() -> DataLocation`, `paths.app_dir() -> Path`, `paths.find_7zz() -> Path | None`
  - `settings.ExportPrefs`, `settings.Settings`, `settings.load_settings(path) -> Settings`, `settings.save_settings(settings, path) -> None`
  - `logging_setup.setup_logging(logs_dir: Path) -> Path` (путь к файлу журнала)
  - `tests/helpers.py`: `page_image(i, size=(600, 900), mode="RGB") -> Image`, `encode(img, fmt, **kw) -> bytes`, `make_zip(path, files: dict[str, bytes], raw_encoding: str | None = None, compress: int = zipfile.ZIP_STORED) -> Path`, `make_7z(path, files: dict[str, bytes], password: str | None = None, fmt: str = "7z") -> Path`, `make_pdf(path, images: list[bytes]) -> Path`, `make_epub(path, paragraphs: int) -> Path`, `make_fb2(path, text: str) -> Path`, `RAR_DIR: Path`

- [ ] **Step 1: Создать `pyproject.toml` и `.gitignore`**

  Сборщик setuptools, `package-dir = {"" = "src"}`, зависимости из Global Constraints, `[project.optional-dependencies] dev = [pytest, pytest-qt, pyinstaller]`, `[project.gui-scripts] mangareader = "mangareader.app:main"`, `[tool.pytest.ini_options] testpaths = ["tests"]`, `qt_api = "pyside6"`. В `.gitignore`: `data/`, `.venv/`, `build/`, `dist/`, `__pycache__/`, `*.egg-info/`. Окружение: `python3.13 -m venv .venv && .venv/bin/pip install -e .[dev]`. На Linux для Qt нужны `libegl1 libxkbcommon0 libgl1 libfontconfig1 libdbus-1-3`.

- [ ] **Step 2: Написать падающие тесты `tests/test_paths.py` и `tests/test_settings.py`**

```python
def test_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGAREADER_DATA", str(tmp_path / "d"))
    loc = resolve_data_location()
    assert loc.root == tmp_path / "d" and not loc.is_fallback and loc.root.is_dir()

def test_data_next_to_app(tmp_path, monkeypatch):
    monkeypatch.delenv("MANGAREADER_DATA", raising=False)
    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
    assert resolve_data_location().root == tmp_path / "data"

def test_fallback_when_not_writable(tmp_path, monkeypatch):
    monkeypatch.delenv("MANGAREADER_DATA", raising=False)
    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "_is_writable", lambda p: False)
    monkeypatch.setattr(paths, "_user_data_dir", lambda: tmp_path / "fb")
    loc = resolve_data_location()
    assert loc.is_fallback and loc.root == tmp_path / "fb"

def test_find_7zz_in_dev_env():
    exe = find_7zz()
    assert exe is not None and exe.exists()

def test_settings_roundtrip(tmp_path):
    s = Settings(); s.theme = "light"; s.export.quality = 80; s.add_recent("C:/a.cbz")
    save_settings(s, tmp_path / "settings.json")
    assert load_settings(tmp_path / "settings.json") == s

def test_settings_corrupt_file_gives_defaults(tmp_path):
    (tmp_path / "settings.json").write_text("{oops", encoding="utf-8")
    assert load_settings(tmp_path / "settings.json") == Settings()
    assert (tmp_path / "settings.json.bad").exists()

def test_settings_unknown_keys_ignored_missing_defaulted(tmp_path):
    (tmp_path / "settings.json").write_text('{"theme": "light", "zzz": 1}', encoding="utf-8")
    s = load_settings(tmp_path / "settings.json")
    assert s.theme == "light" and s.cache_mb == 1024

def test_recent_dedupe_and_limit():
    s = Settings()
    for i in range(12): s.add_recent(f"/f{i}")
    s.add_recent("/f5")
    assert s.recent[0] == "/f5" and len(s.recent) == 10 and s.recent.count("/f5") == 1

def test_logging_writes(tmp_path):
    log = setup_logging(tmp_path)
    logging.getLogger("mangareader").warning("проверка")
    assert "проверка" in log.read_text(encoding="utf-8")
```

- [ ] **Step 3: Запустить и убедиться, что падают** — `pytest -q tests/test_paths.py tests/test_settings.py` → ошибки импорта.

- [ ] **Step 4: Реализовать `paths.py`, `settings.py`, `logging_setup.py`, `__init__.py` (`__version__ = "0.1.0"`)**

  - `resolve_data_location()`: переменная `MANGAREADER_DATA` → иначе `app_dir() / "data"`, если `_is_writable` (создать папку, записать и удалить пробный файл) → иначе `_user_data_dir()` (`%LOCALAPPDATA%\MangaReader` в Windows, `~/.local/share/MangaReader` в других ОС) с `is_fallback=True`. Создаёт `root`.
  - `app_dir()`: `Path(sys.executable).parent` при `sys.frozen`, иначе корень репозитория (`Path(__file__).resolve().parents[2]`).
  - `find_7zz()`: переменная `MANGAREADER_7ZZ` → при `sys.frozen` `app_dir()/"tools"/("7zz.exe" | "7zz")` → иначе `importlib.resources.files("py7zz")/"bin"/имя`. Несуществующий файл → `None`.
  - `Settings` (dataclass): `theme="dark"`, `cache_mb=1024`, `recent: list[str]`, `export: ExportPrefs`, `book_font_size=12.0`, `sidebar_visible=True`, `window_geometry=""`; метод `add_recent(path)` (в начало, без дублей, максимум 10).
  - `ExportPrefs`: `fmt="original"`, `quality=92`, `preset="high"`, `resize_mode="original"`, `resize_value=100`, `spread_layout="separate"`, `folder=""`, `template="{серия} – Том {том} – Гл {глава} – стр {страница}"`.
  - `save_settings`: JSON с `ensure_ascii=False`, `indent=2`, атомарно (временный файл + `os.replace`). `load_settings`: нет файла → значения по умолчанию; битый JSON → переименовать в `settings.json.bad` и вернуть значения по умолчанию.
  - `setup_logging`: `RotatingFileHandler(logs_dir/"manga-reader.log", maxBytes=1_000_000, backupCount=4, encoding="utf-8")` на логгер `mangareader`, уровень INFO.

- [ ] **Step 5: `tests/conftest.py` и `tests/helpers.py`**

  `conftest.py`: в самом начале `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`; autouse-фикстура ставит `MANGAREADER_DATA=tmp_path/"data"`; фикстура `ctx` (появится в задаче 3) — `SourceContext(extract_root=tmp_path/"extract", seven_zip=find_7zz())`.
  `helpers.py`:
  - `page_image(i)` — однотонная заливка цветом `((i*53) % 256, (i*97) % 256, (i*31) % 256)` с белым квадратом 50×50 в точке `(10+i, 10+i)`, чтобы страницы различались попиксельно.
  - `make_zip(raw_encoding=…)` пишет имена байтами в заданной кодировке без флага UTF-8. Для этого используется подкласс `zipfile.ZipInfo`, у которого `_encodeFilenameFlags` возвращает `(raw_bytes, flag_bits & ~0x800)`.
  - `make_7z` раскладывает файлы во временную папку и запускает `7zz a` (`-t7z` или `-tzip`); при `password` добавляет `-p{password}` и `-mhe=on` (для 7z).
  - `make_pdf` — одна картинка на страницу, размер листа = пиксели × 72 / 300.
  - `make_epub` собирает EPUB 2 вручную: `mimetype`, `container.xml`, `content.opf`, одна XHTML-глава с `paragraphs` абзацами кириллицы.
  - `make_fb2` — минимальный FictionBook 2.0 в UTF-8.

- [ ] **Step 6: RAR-образцы**

  Скачать исходники `rarfile==4.5` (`pip download rarfile==4.5 --no-binary :all: --no-deps`). Скопировать из `test/files/` файлы `rar3-subdirs.rar`, `rar5-subdirs.rar`, `rar5-solid.rar`, `rar5-psw.rar`, `rar5-hpsw.rar` в `tests/fixtures/rar/`. Пароль `password`. В `tests/fixtures/rar/README.md` указать происхождение и приложить текст лицензии rarfile (ISC, © Marko Kreen).

- [ ] **Step 7: CI тестов `.github/workflows/ci.yml`**

  `on: [push, pull_request, workflow_dispatch]`, job `test` с матрицей `ubuntu-latest` и `windows-latest`: `actions/checkout@v4`, `actions/setup-python@v5` (3.13), на Ubuntu `sudo apt-get install -y libegl1 libxkbcommon0 libgl1 libfontconfig1 libdbus-1-3`, затем `pip install -e .[dev]`, `pytest -q` с `QT_QPA_PLATFORM: offscreen`.

- [ ] **Step 8: Прогнать тесты** — `pytest -q` → все PASS.

- [ ] **Step 9: Commit и push** — `git add -A && git commit -m "build: project skeleton, data paths, settings, logging, CI"`.

---

### Task 2: Расшифровка картинок и естественная сортировка

**Files:**
- Create: `src/mangareader/imaging.py`, `src/mangareader/sources/__init__.py` (пока пустой), `src/mangareader/sources/natsort.py`, `tests/test_imaging.py`, `tests/test_natsort.py`

**Interfaces:**
- Produces:
  - `imaging.IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".jpe", ".png", ".webp", ".avif", ".jxl", ".bmp", ".gif", ".tif", ".tiff"})`
  - `imaging.JpegTables(qtables: dict, subsampling: int)` (frozen dataclass)
  - `imaging.Decoded(image: Image.Image, format: str | None, icc: bytes | None, jpeg: JpegTables | None)`; `format` — имя формата Pillow (`"JPEG"`, `"PNG"`, `"WEBP"`, `"AVIF"`, `"JXL"`, `"BMP"`, `"GIF"`, `"TIFF"`, `"JPEG2000"`), `None` для отрендеренных страниц документа
  - `imaging.ImageDecodeError(Exception)`
  - `imaging.decode(data: bytes, draft: tuple[int, int] | None = None) -> Decoded`
  - `imaging.read_size(data: bytes) -> tuple[int, int] | None` (только по заголовку, данные могут быть неполными)
  - `imaging.resize_lanczos(img, w: int, h: int) -> Image.Image`
  - `natsort.natural_key(s: str) -> tuple`, `natsort.natural_path_key(path: str) -> tuple`

- [ ] **Step 1: Падающие тесты**

```python
@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP", "AVIF", "JXL", "BMP", "GIF", "TIFF"])
def test_decode_all_formats(fmt):
    d = decode(encode(page_image(1, (300, 400)), fmt))
    assert d.format == fmt and d.image.size == (300, 400) and d.image.mode in {"L", "LA", "RGB", "RGBA"}

def test_jpeg_tables_kept():
    d = decode(encode(page_image(1), "JPEG", quality=88))
    assert d.jpeg.qtables and d.jpeg.subsampling in (0, 1, 2)

def test_icc_kept():
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    assert decode(encode(page_image(1), "PNG", icc_profile=icc)).icc == icc

@pytest.mark.parametrize("mode,expected", [("P", "RGB"), ("1", "L"), ("I;16", "L"), ("CMYK", "RGB")])
def test_modes_normalized(mode, expected):
    fmt = "JPEG" if mode == "CMYK" else ("TIFF" if mode == "I;16" else "PNG")
    assert decode(encode(page_image(1).convert(mode), fmt)).image.mode == expected

def test_palette_with_transparency_becomes_rgba():
    img = page_image(1).convert("P"); img.info["transparency"] = 0
    assert decode(encode(img, "PNG", transparency=0)).image.mode == "RGBA"

def test_huge_image_is_not_a_bomb():  # Review Focus 1
    d = decode(encode(Image.new("L", (12000, 10000), 200), "PNG"))
    assert d.image.size == (12000, 10000)

def test_garbage_raises():
    with pytest.raises(ImageDecodeError): decode(b"not an image")

def test_read_size_from_head():
    data = encode(page_image(1, (1234, 2345)), "JPEG")
    assert read_size(data[:65536]) == (1234, 2345) and read_size(b"xx") is None

def test_draft_reduces_jpeg():
    d = decode(encode(page_image(1, (2000, 3000)), "JPEG"), draft=(240, 360))
    assert 240 <= d.image.width < 2000

def test_natural_order():
    names = ["10.jpg", "2.jpg", "1.jpg", "B.jpg", "a.jpg"]
    assert sorted(names, key=natural_key) == ["1.jpg", "2.jpg", "10.jpg", "a.jpg", "B.jpg"]

def test_natural_path_order():
    paths = ["ch10/1.jpg", "ch2/10.jpg", "ch2/9.jpg"]
    assert sorted(paths, key=natural_path_key) == ["ch2/9.jpg", "ch2/10.jpg", "ch10/1.jpg"]
```

- [ ] **Step 2: Запустить** — `pytest -q tests/test_imaging.py tests/test_natsort.py` → FAIL (нет модулей).

- [ ] **Step 3: Реализовать `imaging.py` и `natsort.py`**

  - При импорте `imaging`: `import pillow_jxl` (регистрирует JPEG XL) и `Image.MAX_IMAGE_PIXELS = 500_000_000`.
  - `decode`: `Image.open(BytesIO)`; для JPEG при `draft` вызвать `im.draft("RGB" или "L", draft)`; GIF — первый кадр. Перед преобразованием сохранить `format`, `info.get("icc_profile")` и для JPEG `JpegTables(im.quantization, JpegImagePlugin.get_sampling(im))`. Затем `load()` и приведение режима: `1`, `I;16`, `I`, `F` → `L`; `P` и `PA` → `RGBA`, если есть прозрачность, иначе `RGB`; `CMYK`, `YCbCr`, `LAB`, `HSV` → `RGB` (ICC в этом случае отбрасывается); `L`, `LA`, `RGB`, `RGBA` без изменений. Любое исключение Pillow (`UnidentifiedImageError`, `OSError`, `SyntaxError`, `ValueError`, `Image.DecompressionBombError`) превращается в `ImageDecodeError("Не удалось прочитать картинку")`.
  - `read_size`: `Image.open(...).size` без `load()`; при любой ошибке `None`.
  - `resize_lanczos`: `img.resize((w, h), Image.LANCZOS, reducing_gap=3.0)`.
  - `natural_key`: `casefold`, разбиение на числа и текст; элемент ключа — `(0, int)` для числа и `(1, str)` для текста, чтобы не сравнивать int и str. В конце ключа исходная строка для стабильности. `natural_path_key`: кортеж `natural_key` по компонентам пути (разделители `/` и `\`).

- [ ] **Step 4: Прогнать** — те же тесты → PASS.

- [ ] **Step 5: Commit** — `feat: image decoding with format/ICC/JPEG tables and natural sort`.

---

### Task 3: Базовый источник, определение формата, папки

**Files:**
- Create: `src/mangareader/sources/base.py`, `src/mangareader/sources/detect.py`, `src/mangareader/sources/folder.py`, `tests/test_detect.py`, `tests/test_folder_source.py`
- Modify: `src/mangareader/sources/__init__.py`

**Interfaces:**
- Consumes: `imaging.decode`, `imaging.read_size`, `imaging.IMAGE_EXTS`, `imaging.Decoded`, `natsort.natural_path_key`
- Produces:
  - `base.PageRef(index: int, inner_path: str, folder: str, ext: str, size: int)` (frozen). У документов `inner_path="#<n>"` (с единицы), `folder=""`, `ext=""`, `size=0`.
  - `base.Original(data: bytes, ext: str)` (frozen)
  - `base.SourceError(Exception)`; `base.PasswordRequired(SourceError)` с конструктором `(wrong: bool)` и атрибутом `wrong`. Текст: «Архив защищён паролем» / «Неверный пароль».
  - `base.PageSource` (ABC), атрибуты `path: Path`, `kind: str` (`"images"` | `"document"`), `is_reflowable: bool = False`, `pages: list[PageRef]`, `file_size: int`. Методы:
    - `read_original(i) -> Original | None` (абстрактный)
    - `load_image(i, draft=None) -> Decoded` (по умолчанию `decode(read_original(i).data, draft)`; `ImageDecodeError` превращается в `SourceError`)
    - `page_size(i) -> tuple[int, int] | None` (по умолчанию `read_size(self._read_head(i))`, затем полная попытка)
    - `_read_head(i, n=65536) -> bytes | None`
    - `wait_ready(i, timeout=None) -> bool` (по умолчанию `True`)
    - `relayout(width_px, height_px, font_size) -> None` (по умолчанию ничего)
    - `position_token(i) -> int` (по умолчанию `i`), `page_for_token(token) -> int` (по умолчанию ограничение диапазоном)
    - `close()`, `__enter__`, `__exit__`
  - `base.is_junk(inner_path: str) -> bool`, `base.is_image_name(name: str) -> bool`
  - `detect.Format` (StrEnum): `FOLDER, ZIP, RAR, SEVENZIP, PDF, EPUB, FB2, MOBI, XPS, TXT, UNKNOWN`; `detect.detect_format(path) -> Format`; `detect.SOURCE_EXTS = {".cbz", ".zip", ".cbr", ".rar", ".cb7", ".7z", ".pdf", ".epub", ".fb2", ".mobi", ".xps", ".oxps"}` (`.txt` сюда не входит — спецификация 5.1 п. 8); `detect.OPENABLE_EXTS = SOURCE_EXTS | {".txt"}`
  - `folder.FolderSource(path)`, `folder.has_direct_images(path) -> bool`
  - `sources.SourceContext(extract_root: Path, seven_zip: Path | None)` (frozen); `sources.open_source(path, ctx, password=None) -> PageSource`. В этой задаче он обрабатывает `FOLDER`; для `UNKNOWN` бросает `SourceError("Формат файла не поддерживается")`, для отсутствующего пути `SourceError("Файл не найден")`. Остальные ветки добавляют задачи 4–6.

- [ ] **Step 1: Падающие тесты**

```python
def test_detect(tmp_path):
    z = make_zip(tmp_path / "a.cbz", {"1.jpg": b"x"})
    e = make_epub(tmp_path / "b.epub", 3)
    shutil.copy(RAR_DIR / "rar5-solid.rar", tmp_path / "fake.cbz")
    s = make_7z(tmp_path / "c.cb7", {"1.jpg": b"x"})
    (tmp_path / "d.pdf").write_bytes(b"%PDF-1.7\n")
    for name in ("e.fb2", "f.mobi", "g.txt", "h.xps", "i.bin"): (tmp_path / name).write_bytes(b"zz")
    expect = {z: Format.ZIP, e: Format.EPUB, tmp_path / "fake.cbz": Format.RAR, s: Format.SEVENZIP,
              tmp_path / "d.pdf": Format.PDF, tmp_path / "e.fb2": Format.FB2, tmp_path / "f.mobi": Format.MOBI,
              tmp_path / "g.txt": Format.TXT, tmp_path / "h.xps": Format.XPS, tmp_path / "i.bin": Format.UNKNOWN,
              tmp_path: Format.FOLDER}
    assert {p: detect_format(p) for p in expect} == expect

@pytest.mark.parametrize("p,junk", [("__MACOSX/a.jpg", True), ("x/._a.jpg", True), ("Thumbs.db", True),
                                    ("desktop.ini", True), ("x/.DS_Store", True), ("ch1/001.jpg", False)])
def test_is_junk(p, junk): assert is_junk(p) is junk

def test_folder_pages(tmp_path, ctx):
    root = tmp_path / "Манга" / "日本語 漫画"          # Review Focus 2
    for rel in ["ch10/1.jpg", "ch2/1.png", "ch2/10.webp", "ch2/9.jpg", "Thumbs.db", "notes.txt", ".hidden/1.jpg"]:
        f = root / rel; f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(encode(page_image(1), "PNG") if rel.endswith((".jpg", ".png", ".webp")) else b"x")
    src = open_source(root, ctx)
    assert [p.inner_path for p in src.pages] == ["ch2/1.png", "ch2/9.jpg", "ch2/10.webp", "ch10/1.jpg"]
    assert src.pages[0].folder == "ch2" and src.pages[0].ext == ".png"
    assert src.read_original(0) == Original((root / "ch2/1.png").read_bytes(), ".png")
    assert src.page_size(0) == (600, 900) and src.load_image(0).image.size == (600, 900)

def test_folder_file_vanished(tmp_path, ctx):   # Review Focus 4
    (tmp_path / "s").mkdir(); (tmp_path / "s/1.png").write_bytes(encode(page_image(1), "PNG"))
    src = open_source(tmp_path / "s", ctx); (tmp_path / "s/1.png").unlink()
    with pytest.raises(SourceError): src.load_image(0)

def test_missing_and_unknown(tmp_path, ctx):
    with pytest.raises(SourceError, match="не найден"): open_source(tmp_path / "nope.cbz", ctx)
    (tmp_path / "x.bin").write_bytes(b"zz")
    with pytest.raises(SourceError, match="не поддерживается"): open_source(tmp_path / "x.bin", ctx)
```

- [ ] **Step 2: Запустить** → FAIL.

- [ ] **Step 3: Реализовать**

  - `detect_format`: папка → `FOLDER`. Читаются первые 8 байт: `PK\x03\x04` → `EPUB`, если в ZIP есть член `mimetype` с содержимым (без пробелов по краям) `application/epub+zip`, иначе `ZIP` (битый ZIP тоже `ZIP`, ошибка будет при открытии); `Rar!\x1a\x07` → `RAR`; `7z\xbc\xaf\x27\x1c` → `SEVENZIP`; `%PDF` → `PDF`; дальше по расширению: `.fb2` → `FB2`, `.mobi` → `MOBI`, `.xps`/`.oxps` → `XPS`, `.txt` → `TXT`; иначе `UNKNOWN`.
  - `is_junk`: компонент пути `__MACOSX`, имя начинается с `._`, имя (без учёта регистра) равно `thumbs.db`, `desktop.ini` или `.ds_store`.
  - `FolderSource`: рекурсивный обход без скрытых папок (имя начинается с `.`) и без мусора; только `is_image_name`; сортировка `natural_path_key`; `file_size` = сумма размеров. `read_original` превращает `OSError` в `SourceError("Не удалось прочитать страницу: файл недоступен")`. Блокировка `threading.Lock`.
  - `has_direct_images(path)`: в папке есть хотя бы одна картинка (не рекурсивно).

- [ ] **Step 4: Прогнать** → PASS. **Step 5: Commit** — `feat: page source base, format detection, folder source`.

---

### Task 4: RAR и 7z через 7-Zip

**Files:**
- Create: `src/mangareader/sources/sevenzip.py`, `tests/test_sevenzip.py`
- Modify: `src/mangareader/sources/__init__.py` (ветки `RAR`, `SEVENZIP`)

**Interfaces:**
- Consumes: `PageSource`, `PageRef`, `Original`, `SourceError`, `PasswordRequired`, `SourceContext`, `is_junk`, `is_image_name`, `natural_path_key`
- Produces:
  - `sevenzip.ArchiveEntry(path: str, size: int, encrypted: bool)` (frozen)
  - `sevenzip.SevenZip(exe: Path)`: `.list(archive, password) -> list[ArchiveEntry]` (только файлы), `.start_extract(archive, dest, password) -> Extraction`
  - `sevenzip.Extraction`: `.wait_file(inner_path, timeout) -> bool`, `.done: bool`, `.returncode: int | None`, `.error: str | None` (`"wrong_password"` или текст), `.cancel()`
  - `sevenzip.SevenZipSource(path, ctx, password=None)`
  - `sevenzip.prune_extract_root(root, limit_bytes=4 * 1024**3, in_use=frozenset()) -> None`, `sevenzip.clear_extract_root(root) -> None`
  - `open_source`: `RAR`/`SEVENZIP` → `SevenZipSource`; при `ctx.seven_zip is None` → `SourceError("Не найден 7-Zip (7zz) рядом с программой — RAR и 7z не открываются")`.

- [ ] **Step 1: Падающие тесты**

```python
SUBDIRS = {"sub/dir2/file2.txt", "sub/with space/long fn.txt", "sub/üȵĩöḋè/file.txt", "sub/dir1/file1.txt"}

@pytest.mark.parametrize("name", ["rar3-subdirs.rar", "rar5-subdirs.rar"])
def test_list_rar(name):
    entries = SevenZip(find_7zz()).list(RAR_DIR / name, None)
    assert {e.path for e in entries} == SUBDIRS

def test_rar_passwords():
    z = SevenZip(find_7zz())
    with pytest.raises(PasswordRequired) as e1: z.list(RAR_DIR / "rar5-psw.rar", None)
    with pytest.raises(PasswordRequired) as e2: z.list(RAR_DIR / "rar5-hpsw.rar", None)
    with pytest.raises(PasswordRequired) as e3: z.list(RAR_DIR / "rar5-hpsw.rar", "wrong")
    assert (e1.value.wrong, e2.value.wrong, e3.value.wrong) == (False, False, True)
    assert len(z.list(RAR_DIR / "rar5-hpsw.rar", "password")) == 2

def test_extract_solid_rar(tmp_path):
    ex = SevenZip(find_7zz()).start_extract(RAR_DIR / "rar5-solid.rar", tmp_path / "x", None)
    assert ex.wait_file("stest2.txt", 30) and (tmp_path / "x/stest2.txt").stat().st_size == 2048

def test_extract_wrong_password(tmp_path):
    ex = SevenZip(find_7zz()).start_extract(RAR_DIR / "rar5-psw.rar", tmp_path / "x", "nope")
    assert not ex.wait_file("stest1.txt", 30) and ex.error == "wrong_password"

def test_7z_source_pages_lazy_and_cleanup(tmp_path, ctx):
    files = {"ch1/001.jpg": encode(page_image(1), "JPEG"), "ch10/001.jpg": encode(page_image(2), "JPEG"),
             "ch2/001.png": encode(page_image(3), "PNG"), "info.txt": b"x"}
    src = open_source(make_7z(tmp_path / "Манга" / "日本語.cb7", files), ctx)       # Review Focus 2
    assert [p.inner_path for p in src.pages] == ["ch1/001.jpg", "ch2/001.png", "ch10/001.jpg"]
    assert not any(ctx.extract_root.glob("*"))                     # распаковка ещё не началась
    assert src.read_original(2).data == files["ch10/001.jpg"]
    dest = next(ctx.extract_root.iterdir()); src.close()
    assert not dest.exists()

def test_7z_header_password(tmp_path, ctx):
    arc = make_7z(tmp_path / "p.7z", {"1.jpg": encode(page_image(1), "JPEG")}, password="pw")
    with pytest.raises(PasswordRequired): open_source(arc, ctx)
    assert len(open_source(arc, ctx, password="pw").pages) == 1

def test_truncated_7z(tmp_path, ctx):                          # Review Focus 4
    arc = make_7z(tmp_path / "t.7z", {f"{i}.png": encode(page_image(i), "PNG") for i in range(5)})
    arc.write_bytes(arc.read_bytes()[: arc.stat().st_size // 2])
    with pytest.raises(SourceError) as e: open_source(arc, ctx)
    assert not isinstance(e.value, PasswordRequired)

def test_prune(tmp_path):
    for i, age in enumerate([300, 200, 100]):
        d = tmp_path / f"d{i}"; d.mkdir(); (d / "f").write_bytes(b"0" * 3_000_000)
        os.utime(d, (time.time() - age, time.time() - age))
    prune_extract_root(tmp_path, limit_bytes=5_000_000, in_use={tmp_path / "d0"})
    assert sorted(p.name for p in tmp_path.iterdir()) == ["d0"]

def test_no_7zz(tmp_path):
    shutil.copy(RAR_DIR / "rar5-solid.rar", tmp_path / "a.cbr")
    with pytest.raises(SourceError, match="7-Zip"):
        open_source(tmp_path / "a.cbr", SourceContext(tmp_path / "e", None))
```

  В `test_prune` удаляется самая старая папка (`d0` старше всех), но она в `in_use` и остаётся. Удаляются `d1`, затем `d2`, пока сумма больше лимита. Ожидание `["d0"]` проверяет оба правила сразу.

- [ ] **Step 2: Запустить** → FAIL.

- [ ] **Step 3: Реализовать `sevenzip.py`**

  - Список: `[exe, "l", "-slt", "-ba", "-sccUTF-8", f"-p{password or ''}", str(archive)]`, вывод в UTF-8 (`errors="replace"`). Блоки разделены пустыми строками; блоки с `Folder = +` пропускаются; путь нормализуется (`\` → `/`). Если в выводе есть `Wrong password` или `Cannot open encrypted archive`, бросается `PasswordRequired(wrong=password is not None)`. Если есть записи с `Encrypted = +`, а пароля нет, — `PasswordRequired(False)`. Любой другой ненулевой код возврата — `SourceError("Архив повреждён или не поддерживается")`.
  - Распаковка: `[exe, "x", "-y", "-aoa", f"-o{dest}", f"-p{password or ''}", "-bb1", "-bso1", "-bse1", "-bsp0", "-sccUTF-8", str(archive)]`. Фоновый поток читает stdout построчно. Строка `- <путь>` означает начало файла, а значит предыдущий начатый файл записан целиком. При завершении с кодом 0 готовы все файлы. При ненулевом коде готовы только файлы, которые существуют и чей размер совпадает с оглавлением; если в выводе есть `Wrong password`, то `error = "wrong_password"`. Ожидание — через `threading.Condition`.
  - `SevenZipSource`: в конструкторе только оглавление (картинки, без мусора, `natural_path_key`). Распаковка стартует лениво при первом `read_original`, `wait_ready` или `page_size` в папку `ctx.extract_root / f"{sha1(путь+размер+mtime)[:16]}-{uuid4().hex[:6]}"`; перед стартом вызывается `prune_extract_root(ctx.extract_root, in_use=открытые папки)`. `read_original` ждёт файл; если распаковка завершилась ошибкой `wrong_password` → `PasswordRequired(True)`, иначе `SourceError("Не удалось распаковать страницу")`. Путь на диске `(dest / inner).resolve()` обязан лежать внутри `dest.resolve()`, иначе `SourceError`. `page_size` не ждёт распаковку (`None`, пока файла нет). `close()` вызывает `cancel()` и `shutil.rmtree(dest, ignore_errors=True)`.
  - `clear_extract_root`: удалить всё содержимое папки (ошибки игнорировать). `prune_extract_root`: удалять самые старые по `mtime` папки не из `in_use`, пока сумма размеров больше лимита.

- [ ] **Step 4: Прогнать** → PASS. **Step 5: Commit** — `feat: RAR/7z sources via bundled 7-Zip with lazy extraction`.

---

### Task 5: ZIP и CBZ

**Files:**
- Create: `src/mangareader/sources/zip.py`, `tests/test_zip_source.py`
- Modify: `src/mangareader/sources/__init__.py` (ветка `ZIP`)

**Interfaces:**
- Consumes: всё из задачи 3, `SevenZipSource` из задачи 4
- Produces: `zip.choose_zip_encoding(raw_names: list[bytes]) -> str` (`"utf-8"` | `"cp932"` | `"cp866"`), `zip.zip_needs_7z(path) -> bool`, `zip.ZipSource(path)`. В `open_source`: `ZIP` → `SevenZipSource`, если `zip_needs_7z`, иначе `ZipSource`.

- [ ] **Step 1: Падающие тесты**

```python
def test_choose_encoding():
    assert choose_zip_encoding([]) == "utf-8"
    assert choose_zip_encoding(["001.jpg".encode()]) == "utf-8"
    assert choose_zip_encoding(["第1話/001.jpg".encode("utf-8")]) == "utf-8"
    assert choose_zip_encoding(["第1話/001.jpg".encode("cp932")]) == "cp932"
    assert choose_zip_encoding(["Глава 1/001.jpg".encode("cp866")]) == "cp866"

@pytest.mark.parametrize("enc,name", [("cp932", "第1話/001.jpg"), ("cp866", "Глава 1/001.jpg")])
def test_legacy_names(tmp_path, ctx, enc, name):
    src = open_source(make_zip(tmp_path / "a.cbz", {name: encode(page_image(1), "JPEG")}, raw_encoding=enc), ctx)
    assert [p.inner_path for p in src.pages] == [name]

def test_pages_order_and_junk(tmp_path, ctx):
    files = {"wrap/10.jpg": b"a", "wrap/2.jpg": b"b", "wrap/._2.jpg": b"c", "__MACOSX/wrap/2.jpg": b"d",
             "wrap/credits.txt": b"e", "wrap/Thumbs.db": b"f"}
    src = open_source(make_zip(tmp_path / "Манга" / "a.zip", files), ctx)
    assert [p.inner_path for p in src.pages] == ["wrap/2.jpg", "wrap/10.jpg"]
    assert src.read_original(1) == Original(b"a", ".jpg") and src.pages[0].folder == "wrap"

def test_concurrent_reads(tmp_path, ctx):                      # Review Focus 5
    files = {f"{i:03}.png": encode(page_image(i), "PNG") for i in range(20)}
    src = open_source(make_zip(tmp_path / "a.cbz", files), ctx)
    with ThreadPoolExecutor(8) as ex:
        got = list(ex.map(lambda i: src.read_original(i).data, list(range(20)) * 4))
    assert got == [files[f"{i:03}.png"] for i in range(20)] * 4

def test_truncated_zip(tmp_path, ctx):                          # Review Focus 4
    p = make_zip(tmp_path / "a.cbz", {f"{i}.png": encode(page_image(i), "PNG") for i in range(3)})
    p.write_bytes(p.read_bytes()[:200])
    with pytest.raises(SourceError): open_source(p, ctx)

def test_corrupt_member_only_that_page(tmp_path, ctx):
    files = {"1.png": encode(page_image(1), "PNG"), "2.png": encode(page_image(2), "PNG")}
    p = make_zip(tmp_path / "a.cbz", files, compress=zipfile.ZIP_DEFLATED)
    data = bytearray(p.read_bytes()); i = data.find(b"2.png") + 40; data[i:i + 20] = b"\0" * 20
    p.write_bytes(bytes(data)); src = open_source(p, ctx)
    assert src.load_image(0).image.size == (600, 900)
    with pytest.raises(SourceError): src.load_image(1)

def test_encrypted_zip_goes_to_7zip(tmp_path, ctx):
    p = make_7z(tmp_path / "e.cbz", {"1.jpg": encode(page_image(1), "JPEG")}, password="pw", fmt="zip")
    with pytest.raises(PasswordRequired): open_source(p, ctx)
    assert isinstance(open_source(p, ctx, password="pw"), SevenZipSource)
```

- [ ] **Step 2: Запустить** → FAIL.

- [ ] **Step 3: Реализовать `zip.py`**

  - `choose_zip_encoding`: `utf-8`, если все имена декодируются; иначе `cp932`, если все декодируются и хотя бы одно содержит символ из `[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]`; иначе `cp866`.
  - `ZipSource`: первое открытие `zipfile.ZipFile(path)`. Для членов без флага `0x800` сырые имена получаются через `info.orig_filename.encode("cp437")`. Если такие есть, архив открывается повторно с `metadata_encoding=choose_zip_encoding(...)`. Члены-папки пропускаются. `BadZipFile` и `OSError` при открытии → `SourceError("Архив повреждён или не поддерживается")`. Ошибки чтения члена (`BadZipFile`, `zlib.error`, `EOFError`, `OSError`) → `SourceError("Не удалось прочитать страницу: файл повреждён")`. `_read_head` читает `zf.open(name).read(65536)`. Все обращения к `ZipFile` под `threading.Lock`.
  - `zip_needs_7z`: есть член с `flag_bits & 0x1` (шифрование) или с `compress_type` не из `{0, 8, 12, 14}`.

- [ ] **Step 4: Прогнать** → PASS. **Step 5: Commit** — `feat: ZIP/CBZ source with legacy filename encodings`.

---

### Task 6: Документы через MuPDF

**Files:**
- Create: `src/mangareader/sources/document.py`, `tests/test_document_source.py`
- Modify: `src/mangareader/sources/__init__.py` (ветки `PDF`, `EPUB`, `FB2`, `MOBI`, `XPS`, `TXT`)

**Interfaces:**
- Consumes: базовые классы задачи 3, `imaging.decode`, `imaging.read_size`, `imaging.Decoded`
- Produces: `document.DocumentSource(path, password=None)`; константы `FIXED_DPI = 300`, `REFLOW_DPI = 192`, `DEFAULT_REFLOW = (800, 1131, 12.0)`

- [ ] **Step 1: Падающие тесты**

```python
def test_pdf_single_image_original(tmp_path, ctx):
    jpgs = [encode(page_image(i), "JPEG") for i in range(3)]
    src = open_source(make_pdf(tmp_path / "m.pdf", jpgs), ctx)
    assert src.kind == "document" and not src.is_reflowable and len(src.pages) == 3
    assert src.read_original(1) == Original(jpgs[1], ".jpg")
    assert src.load_image(1).image.size == (600, 900) and src.page_size(1) == (600, 900)

def test_pdf_text_page_rendered_at_300dpi(tmp_path, ctx):
    doc = pymupdf.open(); doc.new_page(width=144, height=216).insert_text((20, 50), "Текст")
    doc.save(tmp_path / "t.pdf"); src = open_source(tmp_path / "t.pdf", ctx)
    assert src.read_original(0) is None and src.load_image(0).image.size == (600, 900)

def test_pdf_password(tmp_path, ctx):
    doc = pymupdf.open(); doc.new_page()
    doc.save(tmp_path / "p.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    with pytest.raises(PasswordRequired): open_source(tmp_path / "p.pdf", ctx)
    with pytest.raises(PasswordRequired) as e: open_source(tmp_path / "p.pdf", ctx, password="bad")
    assert e.value.wrong and len(open_source(tmp_path / "p.pdf", ctx, password="pw").pages) == 1

def test_epub_relayout_keeps_position(tmp_path, ctx):
    src = open_source(make_epub(tmp_path / "b.epub", 400), ctx)
    assert src.is_reflowable
    src.relayout(800, 1131, 12); n1 = len(src.pages); mid = n1 // 2; tok = src.position_token(mid)
    src.relayout(800, 1131, 20); n2 = len(src.pages)
    assert n2 > n1 and abs(src.page_for_token(tok) / n2 - mid / n1) < 0.1

def test_fb2_renders_cyrillic(tmp_path, ctx):
    src = open_source(make_fb2(tmp_path / "k.fb2", "Привет, мир " * 50), ctx)
    img = src.load_image(0).image.convert("L")
    assert len(src.pages) >= 1 and img.getextrema()[0] < 128      # есть тёмные пиксели текста

def test_corrupt_pdf(tmp_path, ctx):                           # Review Focus 4
    (tmp_path / "c.pdf").write_bytes(b"%PDF-1.7\n" + os.urandom(2000))
    with pytest.raises(SourceError): open_source(tmp_path / "c.pdf", ctx).load_image(0)

def test_concurrent_render(tmp_path, ctx):                     # Review Focus 5
    src = open_source(make_pdf(tmp_path / "m.pdf", [encode(page_image(i), "PNG") for i in range(6)]), ctx)
    with ThreadPoolExecutor(4) as ex:
        sizes = list(ex.map(lambda i: src.load_image(i % 6).image.size, range(24)))
    assert set(sizes) == {(600, 900)}
```

- [ ] **Step 2: Запустить** → FAIL.

- [ ] **Step 3: Реализовать `document.py`**

  - Открытие `pymupdf.open(path)`; при `needs_pass` вызывается `authenticate(password or "")`, и если результат 0 — `PasswordRequired(wrong=password is not None)`. Исключения MuPDF (`pymupdf.FileDataError`, `RuntimeError`, `ValueError`) → `SourceError("Документ повреждён или не поддерживается")` — и при открытии, и при рендере страницы.
  - Для текучих документов в конструкторе вызывается `relayout(*DEFAULT_REFLOW)`. `relayout(w, h, fs)` → `doc.layout(width=w * 0.75, height=h * 0.75, fontsize=fs)`, затем страницы перестраиваются и кэш «одной картинки» сбрасывается.
  - «Одна картинка на страницу» (кэш по номеру страницы): в `page.get_images(full=True)` ровно одна запись, у неё `smask == 0`, `page.get_text("text").strip() == ""`, площадь `page.get_image_rects(xref)[0]` не меньше 0.95 площади страницы. Тогда `doc.extract_image(xref)` и соответствие расширений `{"jpeg": ".jpg", "jpg": ".jpg", "png": ".png", "jpx": ".jp2", "bmp": ".bmp", "tiff": ".tif", "webp": ".webp"}`; другие форматы → `None`.
  - `load_image`: есть оригинал → `decode`. Иначе `get_pixmap(dpi=..., alpha=False)` → `Image.frombytes("RGB", ...)` → `Decoded(img, None, None, None)`. DPI равен `REFLOW_DPI` или `FIXED_DPI`, а при `draft` — `72 * draft[1] / page.rect.height`.
  - `page_size`: для оригинала — `read_size`; иначе размер листа × DPI / 72.
  - `position_token` и `page_for_token` у текучих документов: `make_bookmark(location_from_page_number(i))` и `page_number_from_location(find_bookmark(t))` с ограничением диапазоном. У остальных — как в базовом классе.
  - Все обращения к документу под одной `threading.Lock` (MuPDF не потокобезопасен).

- [ ] **Step 4: Прогнать** → PASS. **Step 5: Commit** — `feat: PDF/EPUB/FB2/MOBI/XPS/TXT source via MuPDF`.

---

### Task 7: Отпечатки и база данных

**Files:**
- Create: `src/mangareader/library/__init__.py`, `library/model.py`, `library/fingerprint.py`, `library/store.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: `PageSource`
- Produces:
  - `model.Kind` (StrEnum `VOLUME="volume"`, `CHAPTER="chapter"`)
  - `model.ChapterSpan(title: str, start_page: int, number: str | None = None, is_mark: bool = False)` (frozen)
  - `model.ChapterMark(page_index: int, number: str, title: str = "")` (frozen)
  - `model.SourceRecord(id, path: Path, size: int, mtime: float, fingerprint: str, page_count: int, chapters: tuple[ChapterSpan, ...], kind_override: Kind | None, spread_offset: int)` (frozen)
  - `model.Progress(position: int, finished: bool, updated_at: float)`, `model.SeriesPrefs(direction: str, mode: str)`
  - `fingerprint.fingerprint(source: PageSource) -> str`
  - `store.Store(db_path)` с методами:
    - `find_by_path(path) -> SourceRecord | None`
    - `register(path, size, mtime, fingerprint, page_count, chapters) -> SourceRecord`
    - `set_kind_override(id, kind | None)`, `set_spread_offset(id, offset)`
    - `progress(id) -> Progress | None`, `set_progress(id, position, finished)`
    - `latest_progress(ids) -> int | None` (id с самым свежим `updated_at`)
    - `chapter_marks(id) -> list[ChapterMark]` (по `page_index`), `set_chapter_mark(id, mark)`, `delete_chapter_mark(id, page_index)`
    - `series_prefs(series: Path) -> SeriesPrefs | None`, `set_series_prefs(series, prefs)`
    - `close()`
  - Модуль `store` содержит `MIGRATIONS: list[str]`.

- [ ] **Step 1: Падающие тесты**

```python
def test_fingerprint_ignores_path_but_not_content(tmp_path, ctx):
    a = make_zip(tmp_path / "a.cbz", {"1.png": b"x" * 10}); b = tmp_path / "b.cbz"; shutil.copy(a, b)
    c = make_zip(tmp_path / "c.cbz", {"1.png": b"x" * 11})
    fa, fb, fc = (fingerprint(open_source(p, ctx)) for p in (a, b, c))
    assert fa == fb != fc and len(fa) == 20

def test_register_progress_marks_prefs(tmp_path):
    st = Store(tmp_path / "library.db"); f = tmp_path / "v.cbz"; f.write_bytes(b"1")
    r = st.register(f, 1, 1.0, "fp", 10, (ChapterSpan("Глава 1", 0, "1"),))
    assert st.register(f, 1, 2.0, "fp", 10, ()).id == r.id
    st.set_progress(r.id, 5, False); st.set_chapter_mark(r.id, ChapterMark(30, "2"))
    st.set_chapter_mark(r.id, ChapterMark(7, "1", "Пролог")); st.set_kind_override(r.id, Kind.CHAPTER)
    st.set_spread_offset(r.id, 1); st.set_series_prefs(tmp_path, SeriesPrefs("rtl", "spread"))
    rec = st.find_by_path(f)
    assert st.progress(r.id).position == 5 and [m.page_index for m in st.chapter_marks(r.id)] == [7, 30]
    assert (rec.kind_override, rec.spread_offset, rec.chapters) == (Kind.CHAPTER, 1, ())
    assert st.series_prefs(tmp_path) == SeriesPrefs("rtl", "spread")

def test_relink_after_rename(tmp_path):
    st = Store(tmp_path / "library.db"); a = tmp_path / "a.cbz"; a.write_bytes(b"1")
    r = st.register(a, 1, 1.0, "fp", 10, ()); st.set_chapter_mark(r.id, ChapterMark(3, "1"))
    b = tmp_path / "Новое имя.cbz"; a.rename(b)
    assert st.register(b, 1, 1.0, "fp", 10, ()).id == r.id and st.chapter_marks(r.id)
    assert st.find_by_path(a) is None

def test_no_relink_for_copies(tmp_path):
    st = Store(tmp_path / "library.db"); a = tmp_path / "a.cbz"; a.write_bytes(b"1")
    b = tmp_path / "b.cbz"; b.write_bytes(b"1")
    assert st.register(a, 1, 1.0, "fp", 10, ()).id != st.register(b, 1, 1.0, "fp", 10, ()).id

def test_migration_makes_backup(tmp_path, monkeypatch):
    Store(tmp_path / "library.db").close()
    monkeypatch.setattr(store, "MIGRATIONS", store.MIGRATIONS + ["CREATE TABLE extra(x);"])
    Store(tmp_path / "library.db").close()
    assert (tmp_path / "library.db.bak").exists()

def test_corrupt_db_replaced(tmp_path):
    (tmp_path / "library.db").write_bytes(b"garbage" * 100)
    st = Store(tmp_path / "library.db"); f = tmp_path / "x"; f.write_bytes(b"1")
    assert st.register(f, 1, 1.0, "fp", 1, ()).id and list(tmp_path.glob("library.db.corrupt-*"))
```

- [ ] **Step 2: Запустить** → FAIL.

- [ ] **Step 3: Реализовать**

  - `fingerprint`: `sha1(f"{source.file_size}\n" + "\n".join(f"{p.inner_path}\t{p.size}" for p in source.pages)).hexdigest()[:20]`.
  - Схема `MIGRATIONS[0]`:
    ```sql
    CREATE TABLE sources(id INTEGER PRIMARY KEY, path TEXT NOT NULL, path_key TEXT NOT NULL UNIQUE,
      size INTEGER NOT NULL, mtime REAL NOT NULL, fingerprint TEXT NOT NULL, page_count INTEGER NOT NULL,
      chapters_json TEXT NOT NULL DEFAULT '[]', kind_override TEXT CHECK(kind_override IN ('volume','chapter')),
      spread_offset INTEGER NOT NULL DEFAULT 0, last_seen REAL NOT NULL);
    CREATE INDEX sources_fp ON sources(fingerprint);
    CREATE TABLE progress(source_id INTEGER PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
      position INTEGER NOT NULL, finished INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL);
    CREATE TABLE chapter_marks(source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
      page_index INTEGER NOT NULL, number TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
      PRIMARY KEY(source_id, page_index));
    CREATE TABLE series_prefs(series_key TEXT PRIMARY KEY, direction TEXT NOT NULL, mode TEXT NOT NULL);
    ```
  - `path_key = os.path.normcase(os.path.abspath(path))`. `register`: если есть строка с таким `path_key` — обновить её (id сохраняется). Иначе взять первую строку с тем же отпечатком, чей `path` больше не существует на диске, и перенести её на новый путь. Иначе вставить новую строку.
  - При открытии: `sqlite3.connect(check_same_thread=False)`, `PRAGMA foreign_keys=ON`; все методы под `threading.RLock`. `sqlite3.DatabaseError` при открытии или проверке схемы → переименовать файл в `library.db.corrupt-<время>` и создать базу заново. Если `0 < user_version < len(MIGRATIONS)`, сначала скопировать файл в `library.db.bak`, затем применить недостающие миграции; в конце `user_version = len(MIGRATIONS)`.
  - `chapters_json` — список `[title, start_page, number, is_mark]`.

- [ ] **Step 4: Прогнать** → PASS. **Step 5: Commit** — `feat: fingerprints and SQLite store with relink and migrations`.

---

### Task 8: Классификация серии и сканер

**Files:**
- Create: `src/mangareader/library/classify.py`, `src/mangareader/library/scanner.py`, `tests/test_classify.py`, `tests/test_scanner.py`

**Interfaces:**
- Consumes: `Kind`, `ChapterSpan`, `ChapterMark`, `Store`, `fingerprint`, `open_source`, `SourceContext`, `SourceError`, `PasswordRequired`, `detect.SOURCE_EXTS`, `has_direct_images`, `is_junk`, `PageRef`, `natural_key`
- Produces (`classify`):
  - `name_kind(name: str) -> Kind | None`
  - `extract_number(name: str, kind: Kind | None = None) -> str | None`
  - `internal_chapters(pages: Sequence[PageRef]) -> list[ChapterSpan]`
  - `chapter_spans(internal: Sequence[ChapterSpan], marks: Sequence[ChapterMark]) -> list[ChapterSpan]`
  - `suggest_chapter_number(spans: Sequence[ChapterSpan], page: int) -> str`
  - `SourceInfo(page_count: int, internal: Sequence[ChapterSpan], kind_override: Kind | None, marks: Sequence[ChapterMark], record_id: int | None, locked: bool = False)` (frozen)
  - `SourceEntry(path: Path, kind: Kind, number: str | None, title: str, page_count: int, chapters: list[ChapterSpan], record_id: int | None, locked: bool = False, in_volume_folder: bool = False)`
  - `TreeNode(kind: Kind, title: str, number: str | None, entries: list[SourceEntry], folder: Path | None = None)`
  - `SeriesTree(root: Path, title: str, nodes: list[TreeNode], failed: list[tuple[Path, str]])` с методами `reading_order() -> list[SourceEntry]` и `index_of(path) -> int | None`
  - `classify_series(root: Path, probe: Callable[[Path], SourceInfo]) -> SeriesTree`
  - `find_series_root(opened: Path) -> Path`, `is_volume_folder(folder: Path) -> bool`, `list_children(folder: Path) -> tuple[list[Path], list[Path]]` (источники; том-папки)
- Produces (`scanner`): `SourceProber(store, ctx)` — вызываемый объект `(path) -> SourceInfo`; `scan_series(root, store, ctx) -> SeriesTree`

- [ ] **Step 1: Падающие тесты**

  Вспомогательные функции в `test_classify.py`: `touch(root, rels)` создаёт файлы и папки (для имён картинок пишет крошечный PNG, для остальных `b"x"`); `fake_probe(pages: dict[str, int], default: int, override: dict[str, Kind] = {}, fail: set[str] = set(), locked: set[str] = set())` возвращает `SourceInfo` по имени файла или папки: число страниц из `pages` или `default`, исправление из `override`; для имён из `fail` бросает `SourceError("битый")`, для имён из `locked` возвращает `SourceInfo(0, (), None, (), None, locked=True)`.

```python
@pytest.mark.parametrize("name,kind", [
    ("Berserk v03", Kind.VOLUME), ("Vol.3", Kind.VOLUME), ("Том 2", Kind.VOLUME), ("第3巻", Kind.VOLUME),
    ("Tome 1", Kind.VOLUME), ("т. 3", Kind.VOLUME), ("Ch.021.5", Kind.CHAPTER), ("c015", Kind.CHAPTER),
    ("Глава 7", Kind.CHAPTER), ("第12話", Kind.CHAPTER), ("Episode 5", Kind.CHAPTER),
    ("Vol.03 Ch.021", Kind.CHAPTER), ("Berserk", None), ("cover", None), ("Chainsaw Man", None), ("Vivid", None)])
def test_name_kind(name, kind): assert name_kind(name) == kind

@pytest.mark.parametrize("name,kind,num", [
    ("Berserk v03 (2003) [Group]", Kind.VOLUME, "3"), ("Ch.021.5", Kind.CHAPTER, "21.5"),
    ("Vol.03 Ch.021", Kind.CHAPTER, "21"), ("Vol.03 Ch.021", Kind.VOLUME, "3"), ("第12話", None, "12"),
    ("Глава 007", None, "7"), ("Extra", None, None), ("0", None, "0")])
def test_extract_number(name, kind, num): assert extract_number(name, kind) == num

def refs(folders): return [PageRef(i, f"{f}/{i}.jpg" if f else f"{i}.jpg", f, ".jpg", 1) for i, f in enumerate(folders)]

def test_internal_chapters():
    assert internal_chapters(refs(["w/ch1"] * 3 + ["w/ch2"] * 2)) == [
        ChapterSpan("Глава 1", 0, "1"), ChapterSpan("Глава 2", 3, "2")]
    assert internal_chapters(refs(["wrap"] * 5)) == []
    spans = internal_chapters(refs([""] + ["Prologue"] * 2 + ["Side"] * 2))
    assert [(s.title, s.start_page) for s in spans] == [("Начало", 0), ("Prologue", 1), ("Side", 3)]

def test_marks_become_chapters():
    spans = chapter_spans([], [ChapterMark(5, "1"), ChapterMark(30, "2", "Битва")])
    assert [(s.title, s.start_page, s.is_mark) for s in spans] == [
        ("Начало", 0, False), ("Глава 1", 5, True), ("Глава 2 — Битва", 30, True)]
    assert suggest_chapter_number(spans, 40) == "3" and suggest_chapter_number([], 0) == "1"

def test_layout_mixed(tmp_path):                                # раскладки A–D и мусор (Review Focus 3)
    touch(tmp_path, ["Vol 01.cbz", "Vol 02/c010.cbz", "c020.cbz", "c011.cbz", "readme.txt", "notes.nfo",
                     "empty.zip", ".hidden/x.cbz", "__MACOSX/y.cbz", "ch05/001.jpg", "big.cbz", "small.cbz"])
    tree = classify_series(tmp_path, fake_probe({"empty.zip": 0, "big.cbz": 150, "small.cbz": 20}, default=40))
    assert [n.title for n in tree.nodes] == ["Том 1", "Том 2", "big", "Глава 5", "Глава 11", "Глава 20", "small"]
    assert tree.nodes[1].folder == tmp_path / "Vol 02" and tree.nodes[1].entries[0].in_volume_folder
    assert all("readme" not in e.path.name and "empty" not in e.path.name for e in tree.reading_order())

def test_override_failed_locked(tmp_path):
    touch(tmp_path, ["Vol 01.cbz", "bad.cbz", "locked.cbr"])
    probe = fake_probe({}, default=200, override={"Vol 01.cbz": Kind.CHAPTER}, fail={"bad.cbz"}, locked={"locked.cbr"})
    tree = classify_series(tmp_path, probe)
    assert tree.failed[0][0].name == "bad.cbz"
    assert [(e.path.name, e.kind, e.locked) for e in tree.reading_order()] == [
        ("Vol 01.cbz", Kind.CHAPTER, False), ("locked.cbr", Kind.CHAPTER, True)]

def test_find_series_root(tmp_path):
    touch(tmp_path, ["Berserk/Vol 01/ch01.cbz", "Berserk/Berserk v02.cbz", "S/01/ch01.cbz", "S/01/ch02.cbz", "T/01/x.cbz"])
    assert find_series_root(tmp_path / "Berserk/Vol 01/ch01.cbz") == tmp_path / "Berserk"
    assert find_series_root(tmp_path / "Berserk/Berserk v02.cbz") == tmp_path / "Berserk"
    assert find_series_root(tmp_path / "S/01/ch01.cbz") == tmp_path / "S"
    assert find_series_root(tmp_path / "T/01/x.cbz") == tmp_path / "T/01"
```

  В `test_layout_mixed` верхний уровень такой: сначала тома (`Vol 01`, том-папка `Vol 02`, `big` по числу страниц), затем главы по номеру (`ch05` — папка с картинками, `c011`, `c020`), в конце главы без номера (`small`). Тома без номера идут после томов с номером, главы без номера — после глав с номером.

  `test_scanner.py`:

```python
def test_prober_uses_cache(tmp_path, ctx, monkeypatch):
    st = Store(tmp_path / "db"); p = make_zip(tmp_path / "s/c001.cbz", {"1.png": encode(page_image(1), "PNG")})
    calls = []; real = scanner.open_source
    monkeypatch.setattr(scanner, "open_source", lambda *a, **k: calls.append(1) or real(*a, **k))
    prober = SourceProber(st, ctx); prober(p); prober(p)
    assert len(calls) == 1
    os.utime(p, (time.time() + 10, time.time() + 10)); prober(p)
    assert len(calls) == 2

def test_scan_series_end_to_end(tmp_path, ctx):
    for n in ("c002", "c001"): make_zip(tmp_path / "S" / f"{n}.cbz", {"1.png": encode(page_image(1), "PNG")})
    tree = scan_series(tmp_path / "S", Store(tmp_path / "db"), ctx)
    assert [e.title for e in tree.reading_order()] == ["Глава 1", "Глава 2"] and tree.title == "S"
```

- [ ] **Step 2: Запустить** → FAIL.

- [ ] **Step 3: Реализовать `classify.py`**

  - Регулярные выражения (без учёта регистра, применяются к имени без расширения):
    - глава: `\b(?:ch|chap|chapter|ep|episode)\.?\s*\d`, `(?<![a-zа-я])c\d`, `глава`, `\bгл\.?\s*\d`, `第\s*\d+\s*話`, `話`;
    - том: `\b(?:vol|volume|tome)\.?\s*\d`, `(?<![a-zа-я])v\d`, `\bтом\b`, `\bт\.\s*\d`, `第\s*\d+\s*巻`, `巻`.
    Если совпали оба, результат `CHAPTER`.
  - `extract_number`: убрать `[...]`, `(...)`, `{...}`; затем искать число после ключевого слова указанного вида, затем `第(\d+)[話巻]`, затем первое `\d+(?:\.\d+)?`. Ведущие нули убираются, но `"0"` остаётся.
  - `internal_chapters`: общий префикс папок страниц срезается (это папка-обёртка), страницы группируются по первому оставшемуся компоненту. Если групп с папкой меньше двух → `[]`. Страницы в корне до первой папки дают «Начало». Заголовок главы: `Глава N`, если `extract_number` нашёл номер, иначе имя папки.
  - `chapter_spans`: внутренние главы и отметки объединяются по `start_page`; при совпадении побеждает отметка. Если первая глава начинается не с 0, в начало добавляется `ChapterSpan("Начало", 0)`. Заголовок отметки: `Глава {number}`, с названием — `Глава {number} — {title}`.
  - `suggest_chapter_number`: номер ближайшей главы до `page` + 1 (целая часть числа); если номера нет — `"1"`.
  - `list_children`: пропускаются скрытые имена и мусор. Файл с расширением из `SOURCE_EXTS` → источник. Папка с картинками напрямую → источник. Папка, где есть источники или папки с картинками, → том-папка. Остальное игнорируется.
  - `classify_series`: у каждого источника вызывается `probe` (`SourceError` попадает в `failed`). Источники с `page_count == 0` и `locked=False` отбрасываются. Вид источника: исправление → внутренних глав не меньше двух (`VOLUME`) → `name_kind` → страниц не меньше 100 (`VOLUME`), иначе `CHAPTER`. Источники том-папки всегда `CHAPTER` (`in_volume_folder=True`) и сортируются по номеру. Пустая том-папка отбрасывается. Сортировка верхнего уровня: сначала тома, затем главы; внутри группы ключ `(номер как float или inf, natural_key(название))`. Заголовок записи: `Том N` / `Глава N` или имя без расширения. `chapters = chapter_spans(info.internal, info.marks)` только для томов, у глав `[]`. `tree.title = root.name`.
  - `is_volume_folder(f)`: `name_kind(f.name) == VOLUME`, либо имя состоит только из числа и все источники внутри по имени — главы. `find_series_root(p)`: `p.parent`, а если это том-папка, то её родитель.

- [ ] **Step 4: Реализовать `scanner.py`**

  `SourceProber.__call__(path)`: для папки-источника всегда заново открывать и перечислять. Для файла: если `store.find_by_path(path)` совпадает по `size` и `mtime`, собрать `SourceInfo` из записи и `chapter_marks`. Иначе `open_source(path, ctx)` → `fingerprint` и `internal_chapters(pages)` → `store.register(...)` → `close()`. `PasswordRequired` даёт `SourceInfo(0, (), None, (), None, locked=True)`. Остальные `SourceError` пробрасываются. `scan_series = classify_series(root, SourceProber(store, ctx))`.

- [ ] **Step 5: Прогнать** → PASS. **Step 6: Commit** — `feat: series classification (volumes/chapters/marks) and cached scanner`.

---

### Task 9: Вырезание и склейка

**Files:**
- Create: `src/mangareader/export/__init__.py`, `export/model.py`, `export/geometry.py`, `tests/test_geometry.py`

**Interfaces:**
- Consumes: `PageSource`, `Original`, `Decoded`
- Produces:
  - `model.PageImage(decoded: Decoded, original: Original | None)`; `model.load_page_image(source, i) -> PageImage`
  - `geometry.Placed(page: int, x: float, y: float, w: float, h: float, orig_w: int, orig_h: int)` (frozen; прямоугольник сцены и исходный размер в пикселях)
  - `geometry.PageCrop(page: int, box: tuple[int, int, int, int], scene: tuple[float, float, float, float])` (frozen; `box` = left, top, right, bottom в пикселях оригинала; `scene` = x, y, w, h пересечения)
  - `geometry.crops_for_selection(placed, sel: tuple[float, float, float, float]) -> list[PageCrop]`
  - `geometry.output_size(placed, crops) -> tuple[int, int]`
  - `geometry.stitch(placed, crops, images: Mapping[int, Image.Image]) -> Image.Image`

- [ ] **Step 1: Падающие тесты**

```python
def test_single_page_crop_is_pixel_exact():
    img = page_image(3, (1000, 1500)); placed = [Placed(0, 0, 0, 500, 750, 1000, 1500)]   # масштаб 0.5
    crops = crops_for_selection(placed, (100, 100, 200, 300))
    assert crops[0].box == (200, 200, 600, 800)
    assert stitch(placed, crops, {0: img}).tobytes() == img.crop((200, 200, 600, 800)).tobytes()

def test_spread_upscales_smaller_page_to_larger():
    a, b = page_image(1, (1000, 1500)), page_image(2, (500, 750))
    placed = [Placed(0, 0, 0, 1000, 1500, 1000, 1500), Placed(1, 1000, 0, 1000, 1500, 500, 750)]
    crops = crops_for_selection(placed, (900, 0, 200, 1500))
    out = stitch(placed, crops, {0: a, 1: b})
    assert out.size == output_size(placed, crops) == (200, 1500)
    assert out.crop((0, 0, 100, 1500)).tobytes() == a.crop((900, 0, 1000, 1500)).tobytes()

def test_ribbon_vertical_stitch_and_modes():
    a, b = page_image(1, (800, 1000)).convert("L"), page_image(2, (800, 1000)).convert("RGBA")
    placed = [Placed(0, 0, 0, 800, 1000, 800, 1000), Placed(1, 0, 1000, 800, 1000, 800, 1000)]
    out = stitch(placed, crops_for_selection(placed, (0, 900, 800, 200)), {0: a, 1: b})
    assert out.size == (800, 200) and out.mode == "RGBA"

def test_selection_outside_pages_is_clamped():
    placed = [Placed(0, 0, 0, 100, 100, 100, 100)]
    assert crops_for_selection(placed, (-50, -50, 80, 80))[0].box == (0, 0, 30, 30)
    assert crops_for_selection(placed, (200, 200, 10, 10)) == []
```

- [ ] **Step 2: Запустить** → FAIL.

- [ ] **Step 3: Реализовать `geometry.py` и `model.py`**

  - `crops_for_selection`: пересечение `sel` с каждым `Placed`, пустые пропускаются. `box`: left/top = `floor((ix - x) * orig_w / w)`, right/bottom = `ceil(...)`, с ограничением размерами оригинала и минимумом 1 пиксель.
  - `stitch`: один фрагмент → `images[p].crop(box)` без изменений. Для нескольких:
    ```
    R = max(p.orig_w / p.w for затронутых страниц)
    U = объединение crop.scene
    размер холста = (round(U.w * R), round(U.h * R)), фон белый
    для каждого фрагмента: прямоугольник на холсте = round((сцена - U.origin) * R) по каждому краю
      (края считаются от абсолютных координат, поэтому соседние куски не дают щелей)
      кусок = images[page].crop(box), Lanczos до размера прямоугольника, если размер отличается
    режим: есть RGBA/LA → RGBA; есть RGB → RGB; иначе L
    ```
  - `output_size` возвращает размер холста по той же формуле (для подписи размера рамки); для одного фрагмента — размер `box`.
  - `load_page_image(source, i)` = `PageImage(source.load_image(i), source.read_original(i))`.

- [ ] **Step 4: Прогнать** → PASS. **Step 5: Commit** — `feat: selection-to-original crop mapping and spread/ribbon stitching`.

---

### Task 10: Кодирование, PDF, имена файлов, запись

**Files:**
- Create: `export/encoders.py`, `export/pdf.py`, `export/naming.py`, `export/writer.py`, `tests/test_encoders.py`, `tests/test_naming_writer.py`

**Interfaces:**
- Consumes: `PageImage`, `Decoded`, `Original`, `imaging.resize_lanczos`
- Produces:
  - `encoders.OutFormat` (StrEnum `ORIGINAL="original"`, `PNG`, `JPEG`, `WEBP`, `AVIF`, `TIFF`, `BMP`, `PDF`; значения в нижнем регистре)
  - `encoders.QUALITY_PRESETS: dict[str, dict[OutFormat, int]]` с ключами `"max"`, `"high"`, `"medium"`, `"compact"` (значения из спецификации 8.2); `encoders.PRESET_LABELS = {"max": "Максимум", "high": "Высокое", "medium": "Среднее", "compact": "Компактное"}`; `encoders.LOSSY = {JPEG, WEBP, AVIF}`
  - `encoders.Resize(mode: str = "original", value: int = 100)` (режимы `"original"`, `"percent"`, `"long_side"`), `encoders.EncodeOptions(fmt: OutFormat, quality: int = 92, resize: Resize = Resize())`, `encoders.Encoded(data: bytes, ext: str)`
  - `encoders.apply_resize(img, resize) -> Image`
  - `encoders.encode_page(page: PageImage, opts) -> Encoded`
  - `encoders.encode_fragment(img, sources: Sequence[PageImage], opts) -> Encoded`
  - `pdf.images_to_pdf(items: Sequence[tuple[Encoded, tuple[int, int]]], dpi: int = 300) -> bytes`
  - `naming.NameFields(series: str, volume: str | None = None, chapter: str | None = None, page: int | None = None, page_count: int = 0, file: str | None = None)`, `naming.DEFAULT_TEMPLATE`, `naming.render_name(template, fields) -> str`, `naming.sanitize_filename(name) -> str`
  - `writer.ExportError(Exception)`, `writer.unique_path(folder, stem, ext) -> Path`, `writer.write_atomic(path, data) -> None`

- [ ] **Step 1: Падающие тесты**

```python
def pi(fmt, mode="RGB", **kw):
    data = encode(page_image(1, (400, 600)).convert(mode), fmt, **kw)
    return PageImage(decode(data), Original(data, {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif"}[fmt]))

def test_original_whole_page_is_byte_copy():
    p = pi("JPEG"); assert encode_page(p, EncodeOptions(OutFormat.ORIGINAL)) == Encoded(p.original.data, ".jpg")

@pytest.mark.parametrize("fmt,ext,check", [
    ("PNG", ".png", "lossless"), ("WEBP", ".webp", "lossless"), ("GIF", ".png", "lossless"), ("JPEG", ".jpg", "jpeg")])
def test_original_fragment_rules(fmt, ext, check):
    p = pi(fmt); frag = p.decoded.image.crop((10, 10, 200, 300))
    enc = encode_fragment(frag, [p], EncodeOptions(OutFormat.ORIGINAL))
    back = Image.open(BytesIO(enc.data)); assert enc.ext == ext
    if check == "lossless": assert back.convert("RGB").tobytes() == frag.convert("RGB").tobytes()
    else: assert back.quantization == p.decoded.jpeg.qtables

def test_mixed_sources_fragment_is_png():
    enc = encode_fragment(page_image(1), [pi("JPEG"), pi("PNG")], EncodeOptions(OutFormat.ORIGINAL))
    assert enc.ext == ".png"

def test_jpeg_quality_subsampling_and_flatten():
    rgba = PageImage(decode(encode(page_image(1).convert("RGBA"), "PNG")), None)
    hi = Image.open(BytesIO(encode_page(rgba, EncodeOptions(OutFormat.JPEG, 92)).data))
    lo = Image.open(BytesIO(encode_page(rgba, EncodeOptions(OutFormat.JPEG, 75)).data))
    assert hi.mode == "RGB" and JpegImagePlugin.get_sampling(hi) == 0 and JpegImagePlugin.get_sampling(lo) == 2

def test_grayscale_and_icc_kept():
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    g = PageImage(decode(encode(page_image(1).convert("L"), "PNG", icc_profile=icc)), None)
    out = Image.open(BytesIO(encode_page(g, EncodeOptions(OutFormat.PNG)).data))
    assert out.mode == "L" and out.info.get("icc_profile") == icc

@pytest.mark.parametrize("fmt", [OutFormat.WEBP, OutFormat.AVIF, OutFormat.TIFF, OutFormat.BMP])
def test_formats_reopen(fmt):
    assert Image.open(BytesIO(encode_page(pi("PNG"), EncodeOptions(fmt, 80)).data)).size == (400, 600)

def test_resize_never_upscales():
    img = page_image(1, (400, 600))
    assert apply_resize(img, Resize("percent", 50)).size == (200, 300)
    assert apply_resize(img, Resize("long_side", 300)).size == (200, 300)
    assert apply_resize(img, Resize("long_side", 5000)).size == (400, 600)

def test_pdf_embeds_original_jpeg():
    p = pi("JPEG"); enc = encode_page(p, EncodeOptions(OutFormat.PDF)); doc = pymupdf.open(stream=enc.data)
    assert enc.ext == ".pdf" and doc.extract_image(doc[0].get_images()[0][0])["image"] == p.original.data
    assert round(doc[0].rect.width) == round(400 * 72 / 300)

def test_render_name():
    f = NameFields("Berserk", "3", "21", 45, 212)
    assert render_name(DEFAULT_TEMPLATE, f) == "Berserk – Том 03 – Гл 21 – стр 045"
    assert render_name(DEFAULT_TEMPLATE, NameFields("Berserk", None, "21.5", 7, 1200)) == "Berserk – Гл 21.5 – стр 0007"
    assert render_name("{файл}", NameFields("S", file="001")) == "001"

@pytest.mark.parametrize("raw,clean", [("a/b:c?", "a_b_c_"), ("CON", "_CON"), ("x. ", "x"), ("", "page")])
def test_sanitize(raw, clean): assert sanitize_filename(raw) == clean

def test_unique_and_atomic(tmp_path):
    write_atomic(unique_path(tmp_path, "p", ".png"), b"1"); write_atomic(unique_path(tmp_path, "p", ".png"), b"2")
    assert sorted(f.name for f in tmp_path.iterdir()) == ["p (2).png", "p.png"]

def test_write_error_is_russian(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError(errno.ENOSPC, "full")))
    with pytest.raises(ExportError, match="места"): write_atomic(tmp_path / "x.png", b"1")
    assert not list(tmp_path.iterdir())
```

- [ ] **Step 2: Запустить** → FAIL.

- [ ] **Step 3: Реализовать**

  - Правило «как в оригинале» для изменённых пикселей (по `Decoded.format` источника):
    - `PNG` и `None` → PNG (`compress_level=6`);
    - `BMP` → BMP; `TIFF` → TIFF (`compression="tiff_lzw"`);
    - `WEBP` → WEBP `lossless=True`;
    - `JPEG` → `qtables=jpeg.qtables, subsampling=jpeg.subsampling, optimize=True` (без таблиц — `quality=95, subsampling=0`);
    - `AVIF` → `quality=100`; `JXL` → `lossless=True`;
    - остальное (`GIF`, `JPEG2000`) → PNG.
    Расширения: `.png .bmp .tif .webp .jpg .avif .jxl`.
  - `encode_page`: `ORIGINAL` без изменения размера при наличии `original` → байты как есть, расширение в нижнем регистре. `ORIGINAL` в остальных случаях → правило выше с источником `page.decoded`.
  - `encode_fragment`: `ORIGINAL` → правило выше, если `format` у всех источников одинаковый (таблицы JPEG берутся у первого), иначе PNG.
  - Форматы с качеством: JPEG `quality=q, subsampling=0 if q >= 90 else 2, optimize=True`; у RGBA/LA — заливка на белый фон (`RGB`/`L`). WEBP `quality=q`; AVIF `quality=q`. PNG/TIFF/BMP как выше. `icc_profile` передаётся для PNG, JPEG, WEBP, AVIF, TIFF, если он есть. `L` остаётся `L`.
  - `PDF`: встраивается картинка, закодированная по правилу «как в оригинале», но только JPEG или PNG. Если правило дало JPEG — JPEG; если исходник целой страницы — JPEG или PNG без изменений — его байты; иначе PNG. `pdf.images_to_pdf`: на каждую картинку `new_page(width=w * 72 / dpi, height=h * 72 / dpi)` и `insert_image(page.rect, stream=data)`, результат `doc.tobytes(deflate=True)`.
  - `apply_resize`: `percent` → `round(w * v / 100)`; `long_side` → коэффициент `v / max(w, h)`; если коэффициент не меньше 1 — изображение без изменений; уменьшение через `resize_lanczos`.
  - `render_name`: шаблон делится на сегменты регулярным выражением `(\s+[–—-]\s+)`. Сегмент, где есть подстановка без значения, удаляется вместе с разделителем перед ним (у первого сегмента — после него). Подстановки: `{серия}`, `{том}`, `{глава}` (целая часть дополняется нулями до 2 знаков: `"3"` → `"03"`, `"21.5"` → `"21.5"`), `{страница}` (номер с единицы, дополняется до `max(3, len(str(page_count)))`), `{файл}`. Неизвестные подстановки остаются как есть. В конце вызывается `sanitize_filename`.
  - `sanitize_filename`: символы `<>:"/\|?*` и `\x00-\x1f` → `_`; обрезать пробелы и точки справа; пустая строка → `page`; зарезервированные имена Windows (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`, без учёта регистра) получают префикс `_`; длина не больше 150 символов.
  - `write_atomic`: запись в `<имя>.part` и `os.replace`. При `OSError` файл `.part` удаляется и бросается `ExportError`: `ENOSPC` → «Недостаточно места на диске», `EACCES`/`EPERM` → «Нет прав на запись в папку {folder}», остальное → «Не удалось сохранить файл: {strerror}».

- [ ] **Step 4: Прогнать** → PASS. **Step 5: Commit** — `feat: encoders with quality rules, PDF export, filename templates, atomic writes`.

---

### Task 11: Кэш, миниатюры, фоновая загрузка

**Files:**
- Create: `src/mangareader/render/__init__.py`, `render/cache.py`, `render/thumbs.py`, `render/loader.py`, `tests/test_render.py`

**Interfaces:**
- Consumes: `PageSource`, `Decoded`, `imaging.resize_lanczos`, `imaging.decode`
- Produces:
  - `cache.ImageCache(budget_bytes)` с методами `get(key)`, `put(key, value, nbytes)`, `set_budget(bytes)`, `discard_where(pred)` и свойством `used_bytes`; функция `cache.image_nbytes(img) -> int` (PIL или QImage)
  - `thumbs.THUMB_HEIGHT = 240`; `thumbs.ThumbnailStore(folder)` с методами `path_for(fp, page) -> Path`, `get(fp, page) -> Image | None`, `create(source, page, fp) -> Image`
  - `loader.pil_to_qimage(img) -> QImage`
  - `loader.PageLoader(cache, thumbs, parent=None)` (QObject). Сигналы: `full_ready(str, int)`, `scaled_ready(str, int)`, `thumb_ready(str, int)`, `failed(str, int, str)`, `size_known(str, int, int, int)`. Методы:
    - `register(key, source, fingerprint)`, `unregister(key)`
    - `full(key, page) -> Decoded | None`
    - `scaled(key, page, w, h) -> QImage | None`
    - `thumbnail(key, page) -> QImage | None`
    - `prefetch(key, pages)`, `probe_sizes(key)`
    - `error(key, page) -> str | None` (последняя ошибка страницы)

- [ ] **Step 1: Падающие тесты**

```python
def test_cache_lru_budget():
    c = ImageCache(100); c.put("a", 1, 40); c.put("b", 2, 40); c.get("a"); c.put("c", 3, 40)
    assert (c.get("a"), c.get("b"), c.get("c"), c.used_bytes) == (1, None, 3, 80)
    c.put("huge", 4, 500); assert c.get("huge") == 4          # только что положенное не вытесняется

def test_thumbnail_store(tmp_path, ctx):
    src = open_source(make_zip(tmp_path / "a.cbz", {"1.jpg": encode(page_image(1, (1200, 1800)), "JPEG")}), ctx)
    ts = ThumbnailStore(tmp_path / "th"); img = ts.create(src, 0, "fp1")
    assert img.height == 240 and ts.path_for("fp1", 0).exists() and ts.get("fp1", 0).size == img.size

def test_loader_full_scaled_and_failure(qtbot, tmp_path, ctx):
    files = {"1.png": encode(page_image(1, (1000, 1500)), "PNG"), "2.png": b"broken"}
    src = open_source(make_zip(tmp_path / "a.cbz", files), ctx)
    ld = PageLoader(ImageCache(512 * 2**20), ThumbnailStore(tmp_path / "th")); ld.register("k", src, "fp")
    with qtbot.waitSignal(ld.full_ready, timeout=5000): assert ld.full("k", 0) is None
    assert ld.full("k", 0).image.size == (1000, 1500)
    with qtbot.waitSignal(ld.scaled_ready, timeout=5000): ld.scaled("k", 0, 200, 300)
    q = ld.scaled("k", 0, 200, 300); assert (q.width(), q.height()) == (200, 300)
    with qtbot.waitSignal(ld.failed, timeout=5000) as sig: ld.full("k", 1)
    assert sig.args[0:2] == ["k", 1] and ld.error("k", 1)

def test_probe_sizes(qtbot, tmp_path, ctx):
    src = open_source(make_zip(tmp_path / "a.cbz", {"1.png": encode(page_image(1, (1600, 900)), "PNG")}), ctx)
    ld = PageLoader(ImageCache(2**26), ThumbnailStore(tmp_path / "th")); ld.register("k", src, "fp")
    with qtbot.waitSignal(ld.size_known, timeout=5000) as sig: ld.probe_sizes("k")
    assert sig.args == ["k", 0, 1600, 900]
```

- [ ] **Step 2: Запустить** → FAIL.

- [ ] **Step 3: Реализовать**

  - `ImageCache`: `OrderedDict` под `threading.Lock`; `put` вытесняет давно не использованные записи, пока сумма больше бюджета, но никогда не трогает только что положенную.
  - `ThumbnailStore.create`: `source.load_image(page, draft=(THUMB_HEIGHT * 2, THUMB_HEIGHT * 3))`, уменьшение до высоты 240 с сохранением пропорций, сохранение в WEBP с `quality=80` атомарно. `path_for = folder / fp[:2] / f"{fp}-{page}.webp"`.
  - `PageLoader`: `QThreadPool.globalInstance()` и задачи-`QRunnable`; одинаковые задачи в работе не дублируются (множество ключей). Приоритеты: видимая страница 10, предзагрузка 0, миниатюры −5. Ключи кэша: `("full", key, page)` и `("scaled", key, page, w, h)`; при новом размере старые `scaled` той же страницы удаляются. `scaled` требует `full`: если полного изображения нет, сначала загружается оно, затем строится уменьшенное. `pil_to_qimage` поддерживает режимы `L` → `Grayscale8`, `RGB` → `RGB888`, `RGBA`/`LA` → `RGBA8888`, учитывает `bytesPerLine` и делает `.copy()`. Ошибка `SourceError` запоминается и испускается `failed`. `probe_sizes` проходит все страницы через `source.page_size(i)` и испускает `size_known` для известных. `unregister` вызывает `cache.discard_where(lambda k: k[1] == key)`.

- [ ] **Step 4: Прогнать** → PASS. **Step 5: Commit** — `feat: memory-bounded image cache, thumbnail store, background page loader`.

---

### Task 12: Раскладка страниц и навигация (без Qt)

**Files:**
- Create: `src/mangareader/ui/__init__.py`, `ui/reader/__init__.py`, `ui/reader/layout.py`, `ui/reader/navigation.py`, `tests/test_layout_navigation.py`

**Interfaces:**
- Consumes: `geometry.Placed`, `classify.SourceEntry`
- Produces:
  - `layout.Mode` (StrEnum `SINGLE="single"`, `SPREAD="spread"`, `RIBBON="ribbon"`), `layout.Direction` (StrEnum `RTL="rtl"`, `LTR="ltr"`), `layout.DEFAULT_PAGE_SIZE = (1000, 1500)`
  - `layout.is_wide(size) -> bool`
  - `layout.spread_groups(sizes, offset) -> list[list[int]]`
  - `layout.view_groups(mode, sizes, offset) -> list[list[int]]`
  - `layout.group_index(groups, page) -> int`
  - `layout.place_group(pages, sizes, direction) -> list[Placed]`
  - `layout.place_ribbon(sizes) -> list[Placed]`
  - `navigation.Position(entry: int, page: int)` (frozen, упорядочиваемый)
  - `navigation.step(pos, groups, page_counts: Sequence[int], forward: bool) -> Position | None`
  - `navigation.chapter_starts(entries) -> list[Position]`
  - `navigation.step_chapter(pos, starts, forward) -> Position | None`
  - `navigation.current_chapter(pos, starts) -> Position | None`

- [ ] **Step 1: Падающие тесты**

```python
P, W = (1000, 1500), (2000, 1500)

def test_spread_groups():
    assert spread_groups([P] * 6, 0) == [[0], [1, 2], [3, 4], [5]]
    assert spread_groups([P] * 6, 1) == [[0], [1], [2, 3], [4, 5]]
    assert spread_groups([P, P, W, P, P], 0) == [[0], [1], [2], [3, 4]]
    assert spread_groups([P, None, P], 0) == [[0], [1, 2]]       # неизвестный размер считается обычной страницей

def test_view_groups_modes():
    assert view_groups(Mode.SINGLE, [P] * 3, 0) == [[0], [1], [2]]
    assert view_groups(Mode.RIBBON, [P] * 3, 0) == [[0, 1, 2]]

def test_place_group_rtl_normalizes_height():
    placed = place_group([1, 2], [P, P, (500, 750)], Direction.RTL)
    by_page = {p.page: p for p in placed}
    assert by_page[1].x > by_page[2].x and by_page[2].h == by_page[1].h == 1500 and by_page[2].w == 1000

def test_place_ribbon_normalizes_width():
    placed = place_ribbon([(800, 1000), (400, 500)])
    assert [(p.y, p.w, p.h) for p in placed] == [(0, 800, 1000), (1000, 800, 1000)]

def test_step_across_entries():
    groups = [[0], [1, 2]]
    assert step(Position(0, 1), groups, [3, 5], True) == Position(1, 0)
    assert step(Position(1, 0), [[0]], [3, 5], False) == Position(0, 2)
    assert step(Position(1, 4), [[0], [1, 2], [3, 4]], [3, 5], True) is None
    assert step(Position(0, 2), groups, [3, 0, 5], True) == Position(2, 0)   # закрытый паролем источник пропускается

def test_chapter_navigation():
    e = [entry(chapters=[]), entry(chapters=[span(0), span(10), span(30)])]
    starts = chapter_starts(e)
    assert starts == [Position(0, 0), Position(1, 0), Position(1, 10), Position(1, 30)]
    assert step_chapter(Position(1, 12), starts, True) == Position(1, 30)
    assert step_chapter(Position(1, 12), starts, False) == Position(1, 0)
    assert current_chapter(Position(1, 12), starts) == Position(1, 10)
```

  (`entry` и `span` — небольшие фабрики в тесте, создающие `SourceEntry` и `ChapterSpan`.)

- [ ] **Step 2: Запустить** → FAIL.

- [ ] **Step 3: Реализовать**

  - `spread_groups`:
    ```
    groups=[]; i=0
    if n: groups.append([0]); i=1
    if offset and i<n and not wide(i): groups.append([i]); i+=1
    while i<n:
        if wide(i): groups.append([i]); i+=1
        elif i+1<n and not wide(i+1): groups.append([i,i+1]); i+=2
        else: groups.append([i]); i+=1
    ```
  - `place_group`: `H = max(h)`, ширина страницы `w * H / h`; порядок слева направо — по возрастанию номеров для `LTR` и по убыванию для `RTL`; `y = 0`. Неизвестный размер — `DEFAULT_PAGE_SIZE`. `place_ribbon`: `W = max(w)`, страницы сверху вниз.
  - `step`: следующая или предыдущая группа текущего источника. За краем — переход к соседнему источнику с `page_count > 0`: вперёд на `Position(e', 0)`, назад на `Position(e', page_count - 1)`. Возвращается первая страница новой группы.
  - `chapter_starts`: у записи без глав — её страница 0, у записи с главами — `start_page` каждой главы (страница 0 добавляется, если её нет среди глав). `step_chapter` вперёд — первое начало строго после `pos`; назад — последнее начало строго перед началом текущей главы.

- [ ] **Step 4: Прогнать** → PASS. **Step 5: Commit** — `feat: spread/ribbon layout and chapter-aware navigation`.

---

### Task 13: Виджет страницы `PageView`

**Files:**
- Create: `src/mangareader/ui/reader/view.py`, `tests/test_view.py`

**Interfaces:**
- Consumes: `PageLoader`, `Placed`, `Direction`
- Produces:
  - `view.ZoomMode` (StrEnum `FIT_WIDTH="width"`, `FIT_HEIGHT="height"`, `FIT_WINDOW="window"`, `ACTUAL="actual"`, `CUSTOM="custom"`)
  - `view.PageView(loader, parent=None)` (`QGraphicsView`):
    - сигналы `flip_requested(bool)` (True — вперёд), `visible_page_changed(int)` (лента), `resized()`
    - `show_pages(key, placed, direction, ribbon=False, focus_page=None)`
    - `set_zoom_mode(mode)`, `zoom_by(factor)`, `zoom_mode`, `scale_factor() -> float`
    - `placed() -> list[Placed]`, `visible_pages() -> list[int]`, `scroll_to_page(page)`, `page_item(page) -> PageItem`
    - `selection_mode: bool` (когда `True`, клики не листают и перетаскивание не сдвигает вид)

- [ ] **Step 1: Падающие тесты** (фикстура `view` создаёт `PageView` 600×600 с настоящим `PageLoader` над ZIP из двух страниц 1000×1500)

```python
def test_fit_modes(view):
    view.show_pages("k", place_group([0], [(1000, 1500)], Direction.LTR), Direction.LTR)
    view.set_zoom_mode(ZoomMode.FIT_WIDTH);  assert view.scale_factor() == pytest.approx(view.viewport().width() / 1000, rel=0.02)
    view.set_zoom_mode(ZoomMode.FIT_WINDOW); assert view.scale_factor() == pytest.approx(view.viewport().height() / 1500, rel=0.02)
    view.set_zoom_mode(ZoomMode.ACTUAL);     assert view.scale_factor() == pytest.approx(1 / view.devicePixelRatioF())

@pytest.mark.parametrize("direction,x_frac,forward", [(Direction.RTL, 0.1, True), (Direction.RTL, 0.9, False),
                                                     (Direction.LTR, 0.1, False), (Direction.LTR, 0.9, True)])
def test_click_thirds(view, qtbot, direction, x_frac, forward):
    view.show_pages("k", place_group([0], [(1000, 1500)], direction), direction)
    with qtbot.waitSignal(view.flip_requested) as sig:
        qtbot.mouseClick(view.viewport(), Qt.LeftButton, pos=QPoint(int(view.viewport().width() * x_frac), 300))
    assert sig.args == [forward]

def test_wheel_flips_when_page_fits(view, qtbot):
    view.show_pages("k", place_group([0], [(1000, 1500)], Direction.LTR), Direction.LTR)
    view.set_zoom_mode(ZoomMode.FIT_WINDOW)
    with qtbot.waitSignal(view.flip_requested) as sig: send_wheel(view, -120)
    assert sig.args == [True]

def test_scaled_image_requested_at_device_size(view, qtbot):
    view.show_pages("k", place_group([0], [(1000, 1500)], Direction.LTR), Direction.LTR)
    view.set_zoom_mode(ZoomMode.FIT_WINDOW)
    qtbot.waitUntil(lambda: view.page_item(0).has_scaled_image(), timeout=5000)
    w, h = view.page_item(0).scaled_size()
    assert h == round(1500 * view.scale_factor() * view.devicePixelRatioF())

def test_error_placeholder(view_with_broken_page, qtbot):        # Review Focus 4
    v = view_with_broken_page
    qtbot.waitUntil(lambda: v.page_item(1).error_text() is not None, timeout=5000)
    assert "Не удалось" in v.page_item(1).error_text()
```

  (`send_wheel` — вспомогательная функция теста, отправляющая `QWheelEvent` во viewport.)

- [ ] **Step 2: Запустить** → FAIL.

- [ ] **Step 3: Реализовать `view.py`**

  - Своя `QGraphicsScene`; на каждый `Placed` — элемент `PageItem(QGraphicsItem)` с `boundingRect = (0, 0, w, h)` в позиции `(x, y)`. Методы `PageItem`: `has_scaled_image()`, `scaled_size()`, `error_text()`. Отрисовка в порядке приоритета: уменьшенная `QImage` нужного размера → полная картинка со `SmoothPixmapTransform` → заглушка «Загрузка…» → текст ошибки из `loader.error`.
  - Размер для запроса уменьшенной копии: `round(w * scale * dpr)` × `round(h * scale * dpr)`. Запрос делается через 50 мс после последнего изменения масштаба или размера окна (`QTimer.singleShot`) для видимых страниц, а в ленте — ещё и для страниц на экран выше и ниже. Сигналы `full_ready`, `scaled_ready`, `failed` вызывают `update()` нужного элемента.
  - Масштаб: `FIT_WIDTH` = ширина viewport / ширина сцены; `FIT_HEIGHT` = высота viewport / высота группы (в ленте — по высоте первой видимой страницы); `FIT_WINDOW` = минимум из двух; `ACTUAL` = `1 / devicePixelRatioF()`. Ctrl+колесо → `zoom_by(1.25 ** steps)` и режим `CUSTOM`. Масштаб пересчитывается при `resizeEvent` (кроме `CUSTOM`), после чего испускается `resized`.
  - Колесо без Ctrl: в ленте — прокрутка. Иначе, если вертикальная полоса прокрутки отсутствует, — `flip_requested(delta < 0)`. Если полоса есть, — прокрутка, а у края в направлении прокрутки — листание.
  - Клик (отпускание кнопки без перетаскивания больше 5 пикселей, `selection_mode` выключен): левая треть → `flip_requested(direction == RTL)`, правая треть → `flip_requested(direction == LTR)`.
  - Перетаскивание сдвигает вид (`ScrollHandDrag`), если `selection_mode` выключен.
  - В ленте при прокрутке испускается `visible_page_changed` для страницы, которая занимает центр viewport.

- [ ] **Step 4: Прогнать** → PASS. **Step 5: Commit** — `feat: page view with zoom modes, click/wheel flipping, Lanczos display scaling`.

---

### Task 14: Главное окно, контроллер читалки, запуск программы

**Files:**
- Create: `src/mangareader/app.py`, `src/mangareader/__main__.py`, `ui/theme.py`, `ui/toast.py`, `ui/main_window.py`, `ui/reader/controller.py`, `ui/dialogs/__init__.py`, `ui/dialogs/errors.py`, `ui/dialogs/settings_dialog.py`, `tests/test_main_window.py`
- Modify: `tests/conftest.py` (фикстура `make_window(qtbot) -> MainWindow` — новое окно над `make_services(resolve_data_location())`, показанное через `qtbot.addWidget`; фикстура `window` — одно такое окно)

**Interfaces:**
- Consumes: всё выше (`resolve_data_location`, `load_settings`, `Store`, `SourceContext`, `open_source`, `scan_series`, `find_series_root`, `is_volume_folder`, `has_direct_images`, `PageLoader`, `ImageCache`, `ThumbnailStore`, `clear_extract_root`, `view_groups`, `place_group`, `place_ribbon`, `step`, `step_chapter`, `chapter_starts`, `PageView`)
- Produces:
  - `controller.Services(data, settings, store, ctx, cache, thumbs, loader)` (dataclass); `controller.make_services(data: DataLocation) -> Services`
  - `controller.ReaderController(services, view, parent=None)`:
    - сигналы `state_changed()`, `tree_changed()`, `source_changed(str)` (заголовок нового источника для подсказки), `error(str)`, `password_needed(Path, bool)`
    - `open_path(path, password=None) -> bool`
    - `go_to(pos: Position)`, `next()`, `prev()`, `next_chapter()`, `prev_chapter()`, `first_page()`, `last_page()`
    - `set_mode(Mode)`, `toggle_direction()`, `toggle_spread_offset()`
    - свойства `tree`, `entries`, `position`, `entry`, `source`, `source_key`, `mode`, `direction`, `groups`, `current_group: list[int]`
    - `breadcrumb() -> list[str]`, `page_label() -> str`
    - `close_source()`
  - `main_window.MainWindow(services)` (QMainWindow): атрибуты `services`, `controller`, `view`; `open_paths(paths) -> bool`; методы `page_label_text()` и `breadcrumb_text()` для тестов
  - `errors.show_error(parent, message, log_path)`, `errors.ask_password(parent, file_name, wrong) -> str | None`
  - `toast.Toast.show_message(parent, text, action=None, ms=3000)`; `toast.Toast.last_text()` (для тестов)
  - `theme.apply_theme(app, theme)`
  - `settings_dialog.SettingsDialog(parent, settings)` с методом `apply_to(settings)` (тема и лимит памяти)
  - `app.main(argv=None) -> int`

- [ ] **Step 1: Падающие тесты** (фикстура `window` создаёт `MainWindow(make_services(resolve_data_location()))` и показывает его через `qtbot`; `series(tmp)` создаёт папку `S` с `c001.cbz` (3 страницы) и `c002.cbz` (2 страницы))

```python
def test_open_and_flip_rtl_default(window, qtbot, tmp_path):
    s = series(tmp_path); assert window.open_paths([s / "c001.cbz"])
    assert window.page_label_text() == "1/3" and window.controller.direction == Direction.RTL
    qtbot.keyClick(window.view, Qt.Key_Left); assert window.page_label_text() == "2/3"
    qtbot.keyClick(window.view, Qt.Key_Right); assert window.page_label_text() == "1/3"

def test_continues_into_next_source(window, qtbot, tmp_path):
    s = series(tmp_path); window.open_paths([s / "c001.cbz"])
    qtbot.waitUntil(lambda: len(window.controller.entries) == 2, timeout=5000)
    for _ in range(3): window.controller.next()
    assert window.controller.entry.path.name == "c002.cbz" and Toast.last_text() == "Глава 2"
    assert window.breadcrumb_text() == "S › Глава 2"

def test_progress_and_prefs_persist(qtbot, tmp_path):
    s = series(tmp_path); w1 = make_window(qtbot); w1.open_paths([s / "c001.cbz"])
    w1.controller.next(); qtbot.keyClick(w1.view, Qt.Key_2); w1.close()
    w2 = make_window(qtbot); w2.open_paths([s / "c001.cbz"])
    assert w2.controller.position.page == 1 and w2.controller.mode == Mode.SPREAD
    assert w2.page_label_text() == "2–3/3"

def test_open_folder_of_series_picks_first(window, tmp_path):
    s = series(tmp_path); assert window.open_paths([s]) and window.controller.entry.path.name == "c001.cbz"

def test_missing_file_reports_error(window, qtbot, tmp_path):
    with qtbot.waitSignal(window.controller.error): assert not window.open_paths([tmp_path / "nope.cbz"])

def test_password_prompt(window, monkeypatch, tmp_path):
    arc = make_7z(tmp_path / "p.cb7", {"1.jpg": encode(page_image(1), "JPEG")}, password="pw")
    monkeypatch.setattr(errors, "ask_password", lambda *a: "pw")
    assert window.open_paths([arc]) and window.page_label_text() == "1/1"

def test_recent_and_no_qsettings(window, tmp_path):
    s = series(tmp_path); window.open_paths([s / "c001.cbz"])
    assert window.services.settings.recent[0] == str(s / "c001.cbz")
    src = (Path(mangareader.__file__).parent).rglob("*.py")
    assert not any("QSettings" in p.read_text(encoding="utf-8") for p in src)
```

- [ ] **Step 2: Запустить** → FAIL.

- [ ] **Step 3: Реализовать контроллер**

  - `make_services`: `load_settings`, `Store(data.db)`, `SourceContext(data.extract, find_7zz())`, `clear_extract_root(data.extract)`, `ImageCache(settings.cache_mb * 2**20)`, `ThumbnailStore(data.thumbs)`, `PageLoader`.
  - `open_path(path)`:
    1. Цель. Файл → источник = файл, серия = `find_series_root(файл)`. Папка с картинками напрямую → источник = папка, серия = `find_series_root(папка)`. Иначе серия = папка или её родитель, если папка — том-папка; в этом случае серия сканируется сразу (с курсором ожидания), а источник — запись с самым свежим прогрессом (`store.latest_progress`) среди лежащих внутри открытой папки, иначе первая из них в порядке чтения.
    2. Источник открывается сразу через `open_source`. При `PasswordRequired` испускается `password_needed`, и окно повторяет `open_path` с введённым паролем. При `SourceError` — сигнал `error(str(e))` и результат `False`.
    3. Регистрация в базе (`store.register` с отпечатком), регистрация в `loader` (ключ — `str(path)`), `probe_sizes`.
    4. Позиция восстанавливается из `store.progress` через `page_for_token`. Режим и направление — из `series_prefs`; если их нет, то для `kind == "document"` — `LTR`, иначе `RTL`, режим `SINGLE`.
    5. Страница показывается, затем `scan_series` запускается в `QThreadPool`. Когда дерево готово, испускается `tree_changed`, `entries = tree.reading_order()`, индекс текущей записи берётся из `tree.index_of`. Если открытого файла нет в дереве, используется одна запись — сам файл.
  - Показ: `groups = view_groups(mode, sizes, record.spread_offset)`; группа с текущей страницей раскладывается через `place_group` (или `place_ribbon`) и передаётся в `view.show_pages`; затем `prefetch` двух следующих групп и одной предыдущей. Сигнал `size_known` в режиме разворота пересчитывает группы, сохраняя текущую страницу.
  - Каждая смена позиции записывает `store.set_progress(record_id, source.position_token(page), finished = последняя группа)`. Режим и направление пишутся в `set_series_prefs`, сдвиг — в `set_spread_offset`.
  - Переход в другой источник: `close_source()` (`loader.unregister`, `source.close()`), открыть новый, испустить `source_changed(entry.title)`.
  - `breadcrumb()`: `[название серии, название узла верхнего уровня, название текущей главы]` без повторов и пустых значений. `page_label()`: `"5/212"`, для двух страниц в развороте — `"5–6/212"`.

- [ ] **Step 4: Реализовать окно, тему, подсказки, диалоги, `app.main`**

  - Панель инструментов: хлебные крошки (`" › ".join(breadcrumb)`), счётчик страниц, кнопки «✂» и «💾» (подключаются в задачах 16–17), выпадающие меню «Режим» (1/2/3), «Масштаб» (W/H/F/Z), кнопка направления (D), «⚙» (`SettingsDialog`). Снизу ползунок страниц (`QSlider`; при `RTL` включается `setInvertedAppearance(True)`).
  - Меню «Файл»: «Открыть файл…» (Ctrl+O, фильтр по `OPENABLE_EXTS`), «Открыть папку…» (Ctrl+Shift+O), «Недавние» (`settings.recent`), «Выход».
  - Горячие клавиши (спецификация 6.3, кроме Backspace): стрелки с учётом направления; Пробел и Shift+Пробел сначала прокручивают, если страница больше окна; PgDn/PgUp; Home/End; Ctrl+PgDn/Ctrl+PgUp; 1/2/3; W/H/F/Z; O; D; Tab (левая панель, задача 15); F11; Esc выходит из полного экрана. Клавиши S, Ctrl+C, Ctrl+S, Ctrl+Shift+S, Enter подключаются в задачах 16–17.
  - Перетаскивание файлов в окно → `open_paths`. Путь из командной строки → `open_paths`.
  - `source_changed` → подсказка (`Toast`). `error` → `show_error`. При `data.is_fallback` один раз при показе окна: «Рядом с программой нельзя сохранять данные, поэтому они хранятся в: …».
  - При закрытии окна сохраняются `window_geometry` (base64 от `saveGeometry`) и `sidebar_visible`, вызываются `save_settings`, `close_source`, `store.close`.
  - `theme.apply_theme`: стиль `Fusion` и тёмная или светлая `QPalette`.
  - `app.main`: `argparse` (`path` необязательный, `--self-test` — задача 19), `resolve_data_location`, `setup_logging`, `sys.excepthook` и `threading.excepthook` пишут в журнал и показывают `show_error`, `QApplication`, `apply_theme`, `MainWindow`, `exec()`. `__main__.py`: `raise SystemExit(main())`.

- [ ] **Step 5: Прогнать** — `pytest -q` → PASS. Запустить программу без экрана и снять скриншот окна с открытым тестовым CBZ (`window.grab().save(...)` в папку scratchpad), чтобы показать пользователю.

- [ ] **Step 6: Commit** — `feat: main window, reader controller, persistence, hotkeys, app entry point`.

---

### Task 15: Левая панель — дерево, миниатюры, ручная разметка

**Files:**
- Create: `ui/reader/sidebar.py`, `ui/dialogs/chapter_mark_dialog.py`, `tests/test_sidebar.py`
- Modify: `ui/main_window.py` (панель в `QSplitter`, Tab), `ui/reader/controller.py` (методы разметки и исправлений)

**Interfaces:**
- Consumes: `SeriesTree`, `SourceEntry`, `ChapterMark`, `Position`, `chapter_spans`, `suggest_chapter_number`, `PageLoader.thumbnail`, `Store`
- Produces:
  - `sidebar.Sidebar(loader, parent=None)`:
    - сигналы `position_selected(int, int)`, `mark_requested(int)`, `mark_edit_requested(int)`, `mark_delete_requested(int)`, `kind_override_requested(int, str)` (`"volume"`, `"chapter"` или `""` — сброс)
    - методы `set_tree(tree)`, `set_source(key, page_count, marks: dict[int, ChapterMark])`, `set_current(pos)`, `tree_widget`, `thumb_view`
  - `chapter_mark_dialog.ask_chapter_mark(parent, number: str, title: str = "") -> tuple[str, str] | None`
  - Методы контроллера: `add_chapter_mark(page, number, title)`, `delete_chapter_mark(page)`, `set_kind_override(entry_index, kind: Kind | None)`, `marks() -> dict[int, ChapterMark]`
  - Атрибут окна `MainWindow.sidebar`

- [ ] **Step 1: Падающие тесты**

```python
def test_tree_shows_volumes_and_chapters(window, qtbot, tmp_path):
    s = tmp_path / "S"; make_zip(s / "Vol 01.cbz", {f"{i:03}.png": encode(page_image(i), "PNG") for i in range(6)})
    make_zip(s / "c010.cbz", {"1.png": encode(page_image(1), "PNG")})
    window.open_paths([s / "Vol 01.cbz"]); qtbot.waitUntil(lambda: window.sidebar.tree_widget.topLevelItemCount() == 2)
    assert [window.sidebar.tree_widget.topLevelItem(i).text(0) for i in range(2)] == ["Том 1", "Глава 10"]

def test_manual_mark_creates_chapter_and_survives_restart(qtbot, tmp_path, monkeypatch):
    s = tmp_path / "S"; make_zip(s / "Vol 01.cbz", {f"{i:03}.png": encode(page_image(i), "PNG") for i in range(6)})
    monkeypatch.setattr(chapter_mark_dialog, "ask_chapter_mark", lambda *a, **k: ("1", "Начало пути"))
    w = make_window(qtbot); w.open_paths([s / "Vol 01.cbz"]); w.sidebar.mark_requested.emit(3)
    vol = w.sidebar.tree_widget.topLevelItem(0)
    assert [vol.child(i).text(0) for i in range(vol.childCount())] == ["Начало", "Глава 1 — Начало пути"]
    w.close(); w2 = make_window(qtbot); w2.open_paths([s / "Vol 01.cbz"])
    qtbot.waitUntil(lambda: w2.sidebar.tree_widget.topLevelItemCount() == 1)
    assert w2.sidebar.tree_widget.topLevelItem(0).childCount() == 2

def test_click_chapter_navigates(window, qtbot, tmp_path): ...    # клик по «Глава 1» → controller.position == Position(0, 3)

def test_kind_override_moves_node(window, qtbot, tmp_path):
    s = tmp_path / "S"; make_zip(s / "Vol 01.cbz", {"1.png": encode(page_image(1), "PNG")})
    make_zip(s / "c002.cbz", {"1.png": encode(page_image(1), "PNG")})
    window.open_paths([s / "Vol 01.cbz"]); qtbot.waitUntil(lambda: window.sidebar.tree_widget.topLevelItemCount() == 2)
    titles = lambda: [window.sidebar.tree_widget.topLevelItem(i).text(0) for i in range(2)]
    assert titles() == ["Том 1", "Глава 2"]
    window.sidebar.kind_override_requested.emit(0, "chapter")
    qtbot.waitUntil(lambda: titles() == ["Глава 1", "Глава 2"], timeout=5000)

def test_thumbnails_and_mark_badge(window, qtbot, tmp_path): ...  # модель миниатюр: 6 строк; у строки 3 после отметки подпись «4 · Гл 1»
```

  Тела двух тестов, отмеченных `...`, пишутся по комментарию в той же форме, что и соседние тесты.

- [ ] **Step 2: Запустить** → FAIL.

- [ ] **Step 3: Реализовать**

  - Дерево: `QTreeWidget` без заголовка. Узел верхнего уровня = `TreeNode`. Дети: у том-папки — её записи, у тома-источника — `chapters`. В `Qt.UserRole` элемента хранится `Position(entry_index, start_page)`. Текущая глава выделяется жирным (`set_current`). Контекстное меню на записях верхнего уровня, кроме записей внутри том-папки: «Это том», «Это глава», «Сбросить».
  - Миниатюры: `QListView` в режиме `IconMode`, поток сверху вниз, иконки 120×180, своя `QAbstractListModel` (иконки из `loader.thumbnail`, обновление по `thumb_ready`). Подпись: номер страницы с единицы и `· Гл N` для отметки. Контекстное меню: «Здесь начинается глава…» или, если отметка уже есть, «Изменить отметку…» и «Удалить отметку». Клик → `position_selected(текущий источник, страница)`.
  - Контроллер: `add_chapter_mark` вызывает `store.set_chapter_mark`, пересчитывает `entry.chapters = chapter_spans(internal записи, marks)` и испускает `tree_changed`. Номер по умолчанию для диалога — `suggest_chapter_number(entry.chapters, page)`. `set_kind_override` вызывает `store.set_kind_override` и пересканирует серию, сохраняя позицию.
  - Окно: `QSplitter(sidebar | view)`, Tab переключает видимость, начальное состояние из `settings.sidebar_visible`.

- [ ] **Step 4: Прогнать** → PASS; снять скриншот окна с панелью. **Step 5: Commit** — `feat: sidebar with series tree, thumbnails, manual chapter marks, kind overrides`.

---

### Task 16: Ножницы и буфер обмена

**Files:**
- Create: `ui/reader/selection.py`, `tests/test_selection.py`
- Modify: `ui/main_window.py` (S, Ctrl+C, Enter, Esc, кнопка ✂), `ui/reader/view.py` (передача событий мыши инструменту при `selection_mode`), `tests/conftest.py` (фикстуры `cbz_1000x1500` — одна PNG-страница 1000×1500, `cbz_spread` — три PNG-страницы 1000×1500; задачи 17 и 18 используют их же)

**Interfaces:**
- Consumes: `PageView.placed()`, `crops_for_selection`, `output_size`, `stitch`, `load_page_image`, `pil_to_qimage`
- Produces:
  - `selection.SelectionTool(view)` (QObject):
    - сигналы `save_requested()`, `copy_requested()`, `finished()`
    - методы `activate()`, `deactivate()`, `active`, `rect() -> QRectF | None` (в координатах сцены, ограничен объединением страниц), `set_rect(QRectF)`, `size_label() -> str` (например `"1840 × 2610"`)
  - `selection.render_selection(source, placed, rect) -> tuple[Image.Image, list[PageImage]]`
  - Атрибут окна `MainWindow.selection` (`SelectionTool`) и метод `copy_to_clipboard()`: есть выделение → фрагмент; нет → текущая группа страниц (для разворота — склейка обеих).

- [ ] **Step 1: Падающие тесты**

```python
def test_drag_creates_rect_and_label(window, qtbot, cbz_1000x1500):
    window.open_paths([cbz_1000x1500]); window.view.set_zoom_mode(ZoomMode.ACTUAL)
    qtbot.keyClick(window.view, Qt.Key_S); tool = window.selection
    vp = window.view.viewport()
    qtbot.mousePress(vp, Qt.LeftButton, pos=QPoint(50, 50)); qtbot.mouseMove(vp, QPoint(250, 350))
    qtbot.mouseRelease(vp, Qt.LeftButton, pos=QPoint(250, 350))
    r = tool.rect(); assert r is not None and r.width() > 0
    w, h = map(int, tool.size_label().split(" × ")); assert (w, h) == output_size(window.view.placed(),
        crops_for_selection(window.view.placed(), (r.x(), r.y(), r.width(), r.height())))

def test_copy_spread_selection_to_clipboard(window, qtbot, cbz_spread):
    window.open_paths([cbz_spread]); window.controller.set_mode(Mode.SPREAD); window.controller.next()
    qtbot.keyClick(window.view, Qt.Key_S); placed = window.view.placed()
    union = QRectF(min(p.x for p in placed), 0, sum(p.w for p in placed), placed[0].h)
    window.selection.set_rect(union); qtbot.keyClick(window.view, Qt.Key_C, Qt.ControlModifier)
    img = QGuiApplication.clipboard().image()
    assert (img.width(), img.height()) == output_size(placed, crops_for_selection(placed, rect_tuple(union)))

def test_escape_cancels(window, qtbot, cbz_1000x1500):
    window.open_paths([cbz_1000x1500]); qtbot.keyClick(window.view, Qt.Key_S)
    window.selection.set_rect(QRectF(0, 0, 10, 10)); qtbot.keyClick(window.view, Qt.Key_Escape)
    assert not window.selection.active and window.selection.rect() is None

def test_copy_without_selection_copies_page(window, qtbot, cbz_1000x1500):
    window.open_paths([cbz_1000x1500]); qtbot.keyClick(window.view, Qt.Key_C, Qt.ControlModifier)
    assert QGuiApplication.clipboard().image().width() == 1000
```

- [ ] **Step 2: Запустить** → FAIL.

- [ ] **Step 3: Реализовать**

  - Режим выделения: `view.selection_mode = True`, курсор `Qt.CrossCursor`. Нажатие вне рамки начинает новую рамку; нажатие внутри двигает её; 8 маркеров по 8 пикселей экрана (`ItemIgnoresTransformations`) меняют размер. Снаружи рамки затемнение полупрозрачным путём, у рамки пунктир. Подпись `size_label()` рисуется у правого нижнего угла. Рамка всегда ограничена объединением прямоугольников страниц.
  - Enter → `save_requested`, Ctrl+C → `copy_requested`, Esc → `deactivate()` и `finished`.
  - `render_selection`: страницы, которые задевает `crops_for_selection`, загружаются через `load_page_image` (в потоке пула с курсором ожидания); затем `stitch`.
  - В окне `copy_to_clipboard` переводит картинку через `pil_to_qimage` и вызывает `QGuiApplication.clipboard().setImage(...)`; подсказка «Скопировано в буфер обмена».

- [ ] **Step 4: Прогнать** → PASS; скриншот с активной рамкой на развороте. **Step 5: Commit** — `feat: snipping tool with handles, pixel-size label, clipboard copy`.

---

### Task 17: Окно сохранения и быстрое сохранение

**Files:**
- Create: `ui/dialogs/save_dialog.py`, `tests/test_save.py`
- Modify: `ui/main_window.py` (Ctrl+S, Ctrl+Shift+S, Enter при выделении, кнопка 💾)

**Interfaces:**
- Consumes: `ExportPrefs`, `OutFormat`, `QUALITY_PRESETS`, `PRESET_LABELS`, `LOSSY`, `EncodeOptions`, `Resize`, `encode_page`, `encode_fragment`, `render_name`, `NameFields`, `unique_path`, `write_atomic`, `ExportError`, `render_selection`
- Produces:
  - `save_dialog.SaveChoice(options: EncodeOptions, spread_layout: str, folder: Path, filename: str)` (dataclass)
  - `save_dialog.SaveDialog(parent, prefs: ExportPrefs, *, default_name: str, is_spread: bool, is_fragment: bool, jpeg_source: bool, estimate: Callable[[EncodeOptions], int] | None)` с методами `choice() -> SaveChoice`, `format_combo`, `preset_combo`, `quality_slider`, `hint_label`, `size_label`, `layout_group`
  - В окне: `save_current(quick=False) -> list[Path]` и `default_name_fields() -> NameFields`

- [ ] **Step 1: Падающие тесты**

```python
def test_dialog_quality_controls(qtbot):
    d = SaveDialog(None, ExportPrefs(), default_name="x", is_spread=False, is_fragment=True, jpeg_source=True, estimate=None)
    qtbot.addWidget(d)
    set_format(d, OutFormat.JPEG); set_preset(d, "high"); assert d.quality_slider.isEnabled() and d.quality_slider.value() == 92
    set_format(d, OutFormat.WEBP); assert d.quality_slider.value() == 90
    set_format(d, OutFormat.PNG); assert not d.quality_slider.isEnabled()
    set_format(d, OutFormat.ORIGINAL); assert d.hint_label.isVisible() and "PNG" in d.hint_label.text()
    d.quality_slider.setValue(50); assert d.preset_combo.currentText() == "Своё"

def test_estimate_shown(qtbot):
    d = SaveDialog(None, ExportPrefs(), default_name="x", is_spread=False, is_fragment=False, jpeg_source=False,
                   estimate=lambda o: 2_500_000)
    qtbot.addWidget(d); qtbot.waitUntil(lambda: "2,4 МБ" in d.size_label.text(), timeout=3000)

def test_save_original_page_is_byte_copy(window, tmp_path, monkeypatch, cbz_1000x1500):
    window.open_paths([cbz_1000x1500]); out = tmp_path / "out"; out.mkdir()
    accept_dialog_with(monkeypatch, fmt=OutFormat.ORIGINAL, folder=out)
    [p] = window.save_current()
    assert p.read_bytes() == window.controller.source.read_original(0).data and p.name.endswith(".png")

def test_spread_separate_and_stitched(window, tmp_path, monkeypatch, cbz_spread):
    window.open_paths([cbz_spread]); window.controller.set_mode(Mode.SPREAD); window.controller.next()
    accept_dialog_with(monkeypatch, fmt=OutFormat.PNG, folder=tmp_path, layout="separate")
    assert len(window.save_current()) == 2
    accept_dialog_with(monkeypatch, fmt=OutFormat.PNG, folder=tmp_path, layout="stitched")
    [p] = window.save_current(); assert Image.open(p).width == 2000

def test_quick_save(window, tmp_path, monkeypatch, cbz_1000x1500):
    window.open_paths([cbz_1000x1500]); window.services.settings.export.folder = str(tmp_path)
    window.services.settings.export.fmt = "jpeg"
    monkeypatch.setattr(SaveDialog, "exec", lambda self: pytest.fail("окно не должно открываться"))
    [p] = window.save_current(quick=True)
    assert p.suffix == ".jpg" and Toast.last_text().startswith("Сохранено:")

def test_quick_save_without_folder_opens_dialog(window, monkeypatch, cbz_1000x1500):
    window.open_paths([cbz_1000x1500]); window.services.settings.export.folder = ""
    opened = []; monkeypatch.setattr(SaveDialog, "exec", lambda self: opened.append(1) or 0)
    assert window.save_current(quick=True) == [] and opened

def test_export_error_shown(window, tmp_path, monkeypatch, cbz_1000x1500):
    window.open_paths([cbz_1000x1500]); accept_dialog_with(monkeypatch, fmt=OutFormat.PNG, folder=tmp_path)
    monkeypatch.setattr(writer, "write_atomic", lambda *a: (_ for _ in ()).throw(ExportError("Недостаточно места на диске")))
    shown = []; monkeypatch.setattr(errors, "show_error", lambda p, m, l: shown.append(m))
    assert window.save_current() == [] and shown == ["Недостаточно места на диске"]
```

  (`set_format`, `set_preset`, `accept_dialog_with` — вспомогательные функции теста: выбор пункта по данным элемента и подмена `SaveDialog.exec` так, чтобы диалог принимался с заданными значениями.)

- [ ] **Step 2: Запустить** → FAIL.

- [ ] **Step 3: Реализовать `save_dialog.py`**

  - Форматы в списке по порядку: «Как в оригинале», PNG, JPEG, WEBP, AVIF, TIFF, BMP, PDF (`userData` = `OutFormat`).
  - Пресеты: «Максимум», «Высокое», «Среднее», «Компактное», «Своё». Ползунок и поле ввода 1–100 активны только для `LOSSY`. Пресет выставляет значение для текущего формата; ручное изменение переключает пресет на «Своё»; смена формата берёт значение текущего пресета.
  - Размер: «Оригинал», «Процент», «Длинная сторона» и поле ввода (1–100 % или 16–20000 px).
  - Группа «Разворот»: «Две отдельные страницы» или «Склеить в одну картинку» (видна при `is_spread and not is_fragment`).
  - Папка (поле и «Обзор…» через `QFileDialog.getExistingDirectory`) и имя файла (поле, по умолчанию `default_name`).
  - Подсказка видна при `is_fragment and jpeg_source and формат == ORIGINAL`: «Фрагмент из JPEG сохраняется с минимальными потерями. Для нулевых потерь выберите PNG.»
  - Примерный размер: при `estimate` таймер 500 мс после последнего изменения, вычисление в `QThreadPool`, результат `≈ 2,4 МБ` (десятичная запятая, `МБ`/`КБ`, деление на 1024). Для разворота с раздельными страницами скрыт.
  - Последний выбор записывается в `ExportPrefs` (`fmt`, `preset`, `quality`, `resize_*`, `spread_layout`, `folder`).

- [ ] **Step 4: Реализовать сохранение в окне**

  - `save_current(quick)`. Что сохраняется: при активном выделении — фрагмент (`render_selection`); при одной странице или ленте — страница в фокусе; при развороте — группа (раздельно или склейкой по `spread_layout`).
  - Имя: `render_name(prefs.template, default_name_fields())`. Поля: `series = tree.title`; `volume` — номер узла верхнего уровня, если это том; `chapter` — номер текущей главы (`current_chapter`) или номер записи-главы; `page` и `page_count`; `file` — имя страницы без расширения. Для раздельного разворота имя строится на каждую страницу.
  - `quick=True` и папка задана → без окна, параметры из `settings.export`. Без папки → обычное окно.
  - Кодирование и запись идут в потоке пула с курсором ожидания: `encode_page` или `encode_fragment` → `unique_path(folder, name, enc.ext)` → `write_atomic`. Успех → подсказка «Сохранено: {имя}» с кнопкой «Открыть папку» (`QDesktopServices.openUrl(QUrl.fromLocalFile(folder))`), `save_settings`. `ExportError` → `show_error`.

- [ ] **Step 5: Прогнать** → PASS; скриншот окна сохранения. **Step 6: Commit** — `feat: save dialog with formats, quality presets, size estimate; quick save`.

---

### Task 18: Текстовые книги в читалке

**Files:**
- Modify: `ui/main_window.py` (ползунок шрифта), `ui/reader/controller.py` (`set_font_size`, перераскладка при изменении размера окна)
- Create: `tests/test_books.py`

**Interfaces:**
- Consumes: `PageSource.is_reflowable`, `relayout`, `position_token`, `page_for_token`, `PageView.resized`, `Settings.book_font_size`
- Produces: `ReaderController.set_font_size(size: float)`; в окне `font_slider` (`QSlider` 8–24), видимый только для текучих документов

- [ ] **Step 1: Падающие тесты**

```python
def test_font_slider_only_for_books(window, tmp_path, cbz_1000x1500):
    window.open_paths([cbz_1000x1500]); assert not window.font_slider.isVisible()
    window.open_paths([make_epub(tmp_path / "b.epub", 400)]); assert window.font_slider.isVisible()

def test_font_change_keeps_position(window, qtbot, tmp_path):
    window.open_paths([make_epub(tmp_path / "b.epub", 400)]); c = window.controller
    for _ in range(5): c.next()
    n1, p1 = len(c.source.pages), c.position.page
    c.set_font_size(20); n2, p2 = len(c.source.pages), c.position.page
    assert n2 > n1 and abs(p2 / n2 - p1 / n1) < 0.1 and window.services.settings.book_font_size == 20

def test_resize_relayouts(window, qtbot, tmp_path):
    window.open_paths([make_epub(tmp_path / "b.epub", 400)]); n1 = len(window.controller.source.pages)
    window.resize(window.width() // 2, window.height())
    qtbot.waitUntil(lambda: len(window.controller.source.pages) != n1, timeout=3000)
```

- [ ] **Step 2: Запустить** → FAIL.

- [ ] **Step 3: Реализовать.** При открытии текучего документа и через 300 мс после последнего `view.resized` контроллер запоминает `position_token(текущая страница)`, вызывает `source.relayout(viewport.width(), viewport.height(), settings.book_font_size)`, затем `loader.unregister` и `register` (страницы изменились), переходит на `page_for_token(token)` и перестраивает группы. `set_font_size` записывает значение в `settings.book_font_size` и делает то же самое. Миниатюры такого источника перестраиваются. Отпечаток книги считается один раз при открытии (до первой перераскладки) и потом не меняется.

- [ ] **Step 4: Прогнать** → PASS. **Step 5: Commit** — `feat: reflowable books with font size slider and resize relayout`.

---

### Task 19: Самопроверка, сборка exe, выпуск, README

**Files:**
- Create: `src/mangareader/selftest.py`, `packaging/entry.py`, `packaging/mangareader.spec`, `packaging/build_windows.ps1`, `.github/workflows/release.yml`, `README.md`, `tests/test_selftest.py`
- Modify: `src/mangareader/app.py` (`--self-test`), `.github/workflows/ci.yml` (job `build-windows`)

**Interfaces:**
- Consumes: всё выше
- Produces: `selftest.run(report: Path) -> int` (0 — успех); `MangaReader.exe --self-test` пишет отчёт в `data/logs/selftest.log` и возвращает код

- [ ] **Step 1: Падающий тест**

```python
def test_selftest_passes(tmp_path):
    report = tmp_path / "selftest.log"
    assert selftest.run(report) == 0
    text = report.read_text(encoding="utf-8")
    for step in ("zip", "7z", "pdf", "avif", "jxl", "export", "window"): assert f"OK {step}" in text
```

- [ ] **Step 2: Запустить** → FAIL.

- [ ] **Step 3: Реализовать `selftest.run`**

  Всё делается во временной папке, каждый шаг пишет в отчёт `OK <шаг>` или `FAIL <шаг>: <ошибка>`:
  - `zip`: CBZ из страниц JPEG, PNG и WEBP, открыть и прочитать каждую;
  - `7z`: `find_7zz()` существует, архив создаётся командой `7zz a` и открывается через `SevenZipSource`;
  - `pdf`: PDF через MuPDF, `read_original` возвращает JPEG;
  - `avif`, `jxl`: кодирование и декодирование;
  - `export`: вырезать фрагмент и сохранить во все `OutFormat`;
  - `window`: `QApplication` (платформа `offscreen`, если окна создать нельзя), `MainWindow` открывает CBZ, ожидание показа страницы, `grab()` не пустой.
  Код возврата 0 только если все шаги OK. В `app.main` при `--self-test` вызывается `selftest.run(data.logs / "selftest.log")`, окно не показывается. Печать в stdout защищена проверкой `sys.stdout is not None`: в оконной сборке stdout отсутствует.

- [ ] **Step 4: PyInstaller**

  - `packaging/entry.py`: `from mangareader.app import main; raise SystemExit(main())`.
  - `packaging/mangareader.spec`: режим onedir, `name="MangaReader"`, `console=False`, `pathex=["src"]`, `hiddenimports=["pillow_jxl"]`. Файлы 7-Zip из `importlib.resources.files("py7zz")/"bin"` (`7zz.exe` и `7z.dll` в Windows, `7zz` в Linux) кладутся в `tools/` через `binaries`. Исключаются ненужные модули Qt (`PySide6.QtNetwork`, `QtQml`, `QtQuick`, `Qt3D*`, `QtMultimedia`). `paths.find_7zz` в замороженной сборке ищет именно `app_dir()/"tools"`.
  - Проверка на Linux (собранная программа не выкладывается, только проверяется спецификация сборки): `pyinstaller packaging/mangareader.spec --noconfirm`, затем `MANGAREADER_DATA=$(mktemp -d) QT_QPA_PLATFORM=offscreen dist/MangaReader/MangaReader --self-test; echo $?` → `0`.
  - `packaging/build_windows.ps1`: `pip install -e .[dev]`; `pyinstaller packaging/mangareader.spec --noconfirm`; самопроверка через `Start-Process dist\MangaReader\MangaReader.exe -ArgumentList '--self-test' -Wait -PassThru` с `MANGAREADER_DATA` во временной папке, чтобы в сборку не попала папка `data`. Ненулевой `ExitCode` → вывести отчёт и `exit 1`. В конце `Compress-Archive dist\MangaReader -DestinationPath MangaReader-$version-win64.zip`; версия читается из `mangareader.__version__`.

- [ ] **Step 5: Рабочие процессы GitHub**

  - `ci.yml`: новый job `build-windows` (`needs: test`, `windows-latest`) запускает `packaging/build_windows.ps1` и выкладывает zip через `actions/upload-artifact@v4` (имя `MangaReader-win64`).
  - `release.yml`: `on: push: tags: ["v*"]`, `permissions: contents: write`, `windows-latest`, тесты, `build_windows.ps1`, затем `gh release create $env:GITHUB_REF_NAME MangaReader-*.zip --title "Manga Reader $env:GITHUB_REF_NAME" --notes-file packaging/release-notes.md` с `GH_TOKEN: ${{ github.token }}`. Текст примечаний к выпуску лежит в `packaging/release-notes.md` на русском: что вошло в версию и как пройти предупреждение SmartScreen.

- [ ] **Step 6: README.md на русском**

  Что это за программа; как скачать (Releases → `MangaReader-<версия>-win64.zip` → распаковать → `MangaReader.exe`); SmartScreen («Подробнее» → «Выполнить в любом случае»); где лежат данные (`data/` рядом с exe, её можно переносить вместе с программой); таблица горячих клавиш из спецификации 6.3; поддерживаемые форматы; раздел для разработчика (`pip install -e .[dev]`, `pytest -q`, сборка).

- [ ] **Step 7: Прогнать всё** — `pytest -q` → PASS; сборка на Linux и `--self-test` → `0`.

- [ ] **Step 8: Commit, push, проверка CI на GitHub**

  `git commit -m "build: self-test, PyInstaller packaging, Windows CI build, release workflow, README"`, push. Дождаться в GitHub Actions зелёных `test` (Ubuntu и Windows) и `build-windows`. Если что-то упало — чинить по логам (сначала воспроизвести), пока не станет зелёным.

- [ ] **Step 9: Выпуск 0.1.0**

  Проверить скриншоты и собранный артефакт. Затем выпуск: тег `v0.1.0` (`git tag v0.1.0 && git push origin v0.1.0`) или Actions → Release → Run workflow.
