# Этап 2 «Библиотека и навигация»: план реализации

**Goal:** Программа открывается на библиотеке с плитками серий, левой навигацией (Все, Избранное, Форматы, полки, Настройки) и лентой «Продолжить чтение». В читалке появляется кнопка «⌂ Главная» и раскрывающийся список томов, глав и страниц.

**Architecture:** Логика библиотеки без Qt: `library/catalog.py` (данные и выборки) и `library/library_scan.py` (сканирование папок библиотеки). Обе работают поверх той же базы `Store` и готовых `scan_series` / `classify_series`. Интерфейс на Qt-виджетах: `ui/library/` (экран библиотеки), `ui/settings_page.py`, `ui/reader/nav_panel.py`. Главное окно переключает страницы через `QStackedWidget`. Все размеры и цвета новых экранов берутся из `ui/style.py`.

**Tech Stack:** как на этапе 1: Python 3.13, PySide6-Essentials 6.12 (включая QtSvg), SQLite, pytest + pytest-qt, PyInstaller 6.22. Иконки полок взяты из Lucide 1.49.0 (пакет `lucide-static`, лицензия ISC).

**Spec:** `docs/specs/2026-10-30-library-and-navigation-design.md` вместе с основной `docs/specs/2026-10-30-manga-reader-design.md`. Читать спецификации и план вместе.

## Global Constraints

- Действуют все ограничения этапа 1 (`docs/plans/2026-10-30-stage1-reader-and-snipping.md`). Главное из них: модули `library/*` не импортируют Qt, `QSettings` не используется, интерфейс только на русском, строки в `ui/` обёрнуты в `self.tr(...)`, а `Store` можно вызывать из любого потока.
- Визуальный стиль не меняется: палитра из `ui/theme.py`. Новые размеры, отступы и цвета объявляются только в `ui/style.py`.
- Диалоги и системные действия код вызывает через атрибут модуля, чтобы тесты могли их подменить: `shelf_dialog.ask_shelf(...)`, `errors.confirm(...)`, `settings_page.choose_folder(...)`, `page.open_in_explorer(...)`.
- Схема базы меняется только новой записью в конце `store.MIGRATIONS`, `MIGRATIONS[0]` не трогать.
- Тексты пользователю точно как в спецификации: «Такая полка уже есть», «Серия недоступна: папка или файл не найдены», «Добавьте папки с мангой в Настройках — библиотека заполнится сама», «Удалить полку «…»? Серии останутся в библиотеке», «не найдена», «Не удалось открыть (N)».
- Коммиты от имени `yornn`: одна строка на английском (`feat: …`, `test: …`) без дополнительных подписей.
- Работа идёт в `main`, после каждой задачи `git push origin main`. Выпуск (тег) не делать.

## Review Focus

1. **Вложенные папки библиотеки.** Папка внутри уже добавленной или над ней дала бы двойные серии. `add_root` отказывает с понятным текстом. Тест в задаче 2.
2. **Регистр и юникод в путях Windows.** `D:\Manga\Берсерк` и `d:\manga\берсерк` — одна серия. Кириллица и японские имена работают при «Открыть» и сканировании. Тесты в задачах 2 и 4 (проверка регистра только на Windows, в CI она запускается).
3. **Регистр кириллицы в названиях полок.** «Романтика», «романтика», «РОМАНТИКА» — одна полка. `NOCASE` в SQLite понимает только ASCII, поэтому сравнение идёт через `casefold` в Python. Тест в задаче 2.
4. **Исчезнувшие папки и файлы.** Вынутая флешка с папкой библиотеки не стирает её серии и прогресс. Файл обложки удалён, архив под паролем, архив повреждён: плитка без обложки, без падений, а файл попадает в «Не удалось открыть». Тесты в задачах 4 и 6.
5. **Клавиши читалки на экране библиотеки.** Стрелки, цифры и буквы в сетке плиток и в поиске не должны листать страницы или переключать режимы. Тест в задаче 13.

## Структура файлов

```
src/mangareader/
  library/   catalog.py (новый)  library_scan.py (новый)  classify.py  store.py  model.py
  render/    covers.py (новый)
  ui/        style.py (новый)  settings_page.py (новый)  main_window.py
    icons/   __init__.py  lucide/*.svg (48 шт.) + LICENSE
    library/ __init__.py tiles.py nav.py shelf_dialog.py continue_row.py page.py scan_runner.py
    reader/  nav_panel.py (новый, вместо sidebar.py)  controller.py
    dialogs/ errors.py (+ confirm)  settings_dialog.py (удаляется)
tests/  test_store.py test_catalog.py test_catalog_views.py test_library_scan.py test_icons.py test_covers.py
        test_tiles.py test_library_nav.py test_library_page.py test_settings_page.py test_nav_panel.py
        test_library_flow.py (test_sidebar.py удаляется)
```

---

### Task 1: База данных версии 2

**Files:**
- Modify: `src/mangareader/library/store.py`, `src/mangareader/library/model.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Produces:
  - `store.path_key(path: Path) -> str` (бывший `_key`, теперь публичный)
  - `model.Progress(position: int, finished: bool, updated_at: float, fraction: float = 0.0)`
  - `Store.set_progress(source_id, position, finished, fraction: float = 0.0)`: сохраняет `1.0`, если `finished`, иначе `fraction`, зажатую в 0…1
  - `Store.source_by_id(source_id: int) -> SourceRecord | None`
  - `Store.now() -> float` (бывший `_now`: строго растущее время)
  - `Store.query(sql: str, params=()) -> list[tuple]`, `Store.execute(sql: str, params=()) -> int` (`lastrowid`)
  - `Store.transaction()`: контекстный менеджер, отдаёт `sqlite3.Connection` под блокировкой, `BEGIN IMMEDIATE`, при исключении `ROLLBACK`

- [ ] **Step 1: Падающие тесты**

```python
def test_migration_v1_keeps_progress_marks_and_fills_fraction(tmp_path):
    db = tmp_path / "library.db"
    conn = sqlite3.connect(db); conn.executescript(store.MIGRATIONS[0]); conn.execute("PRAGMA user_version = 1")
    for sid, fp in ((1, "a"), (2, "b")):
        conn.execute("INSERT INTO sources(id, path, path_key, size, mtime, fingerprint, page_count, last_seen)"
                     " VALUES (?, ?, ?, 1, 1, ?, 10, 0)", (sid, fp, fp, fp))
    conn.execute("INSERT INTO progress VALUES (1, 4, 0, 1.0)"); conn.execute("INSERT INTO progress VALUES (2, 9, 1, 2.0)")
    conn.execute("INSERT INTO chapter_marks VALUES (1, 3, '1', '')"); conn.commit(); conn.close()
    st = Store(db)
    assert st.progress(1) == Progress(4, False, 1.0, 0.5) and st.progress(2).fraction == 1.0
    assert st.chapter_marks(1) == [ChapterMark(3, "1")] and (tmp_path / "library.db.bak").exists()
    tables = {r[0] for r in st.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"roots", "series", "shelves", "shelf_series"} <= tables

def test_fraction_saved_and_clamped(tmp_path):
    st = Store(tmp_path / "library.db"); f = tmp_path / "v.cbz"; f.write_bytes(b"1")
    rid = st.register(f, 1, 1.0, "fp", 10, ()).id
    st.set_progress(rid, 3, False, 0.4); assert st.progress(rid).fraction == 0.4
    st.set_progress(rid, 9, True, 0.2); assert st.progress(rid).fraction == 1.0
    st.set_progress(rid, 1, False, 1.7); assert st.progress(rid).fraction == 1.0
    assert st.source_by_id(rid).path == f and st.source_by_id(rid + 100) is None

def test_transaction_rolls_back(tmp_path):
    st = Store(tmp_path / "library.db")
    with pytest.raises(RuntimeError):
        with st.transaction() as conn:
            conn.execute("INSERT INTO roots(path, path_key, added_at) VALUES ('r', 'r', 0)")
            raise RuntimeError
    assert st.query("SELECT COUNT(*) FROM roots") == [(0,)]
```

- [ ] **Step 2: Запустить** `pytest tests/test_store.py -q` → FAIL (`Progress` без `fraction`, нет `query`).

- [ ] **Step 3: Реализовать.** `MIGRATIONS[1]`:

```sql
CREATE TABLE roots(id INTEGER PRIMARY KEY, path TEXT NOT NULL, path_key TEXT NOT NULL UNIQUE, added_at REAL NOT NULL);
CREATE TABLE series(id INTEGER PRIMARY KEY, path TEXT NOT NULL, path_key TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
  root_id INTEGER REFERENCES roots(id) ON DELETE CASCADE, added_at REAL NOT NULL, last_opened_at REAL,
  favorite INTEGER NOT NULL DEFAULT 0, formats TEXT NOT NULL DEFAULT '',
  cover_source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
  last_source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL, last_label TEXT NOT NULL DEFAULT '[]');
CREATE TABLE shelves(id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE, icon TEXT NOT NULL,
  created_at REAL NOT NULL);
CREATE TABLE shelf_series(shelf_id INTEGER NOT NULL REFERENCES shelves(id) ON DELETE CASCADE,
  series_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE, PRIMARY KEY(shelf_id, series_id));
ALTER TABLE sources ADD COLUMN series_id INTEGER REFERENCES series(id) ON DELETE SET NULL;
CREATE INDEX sources_series ON sources(series_id);
ALTER TABLE progress ADD COLUMN fraction REAL NOT NULL DEFAULT 0;
UPDATE progress SET fraction = CASE WHEN finished THEN 1.0 ELSE COALESCE((SELECT CASE WHEN progress.position < s.page_count
  THEN (progress.position + 1.0) / s.page_count ELSE 0 END FROM sources s WHERE s.id = progress.source_id), 0) END;
```

  Число страниц серии в таблицу не пишется: его считает запрос каталога по `sources`. Позиция книги (большой номер главы и доли) при миграции даёт долю 0, а при следующем открытии книги доля запишется верная.

- [ ] **Step 4: Прогнать** `pytest -q` → PASS (старые тесты `test_store.py` тоже). **Step 5: Commit** `feat: database v2 with series, roots, shelves and read fraction`.

---

### Task 2: Каталог: папки, серии, полки, избранное, отметки прочитанного

**Files:**
- Create: `src/mangareader/library/catalog.py`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Consumes: `Store.query/execute/transaction/now`, `store.path_key`
- Produces (всё в `catalog.py`):
  - `Status` (StrEnum): `NOT_STARTED = "not_started"`, `READING = "reading"`, `FINISHED = "finished"`
  - `Root(id: int, path: Path, added_at: float)` (frozen), свойство `available` (`path.is_dir()`)
  - `Shelf(id: int, name: str, icon: str, created_at: float)` (frozen)
  - `SeriesCard` (frozen): `id, path: Path, title: str, root_id: int | None, added_at: float, last_opened_at: float | None, favorite: bool, formats: tuple[str, ...], cover_source_id: int | None, last_source_id: int | None, where: tuple[str, ...], shelf_ids: frozenset[int], available: bool, pages_total: int, pages_read: float, sources: int, opened: int, finished: int`. Свойства:
    - `main_format`: `formats[0]` или `""`;
    - `status`: `NOT_STARTED`, если `opened == 0`; `FINISHED`, если `sources and finished == sources`; иначе `READING`;
    - `progress`: `pages_read / pages_total`, а при `pages_total == 0` — `1.0` для `FINISHED`, иначе `0.0`.
  - `CatalogError(ValueError)`: текст исключения сразу показывается пользователю
  - `Catalog(store: Store)`:
    - `roots() -> list[Root]` (по `added_at`, `id`), `add_root(path) -> int`, `remove_root(root_id)`, `relocate_root(root_id, new_path)`
    - `ensure_series(path, root_id: int | None = None) -> int`, `update_series(series_id, *, title: str, formats: Sequence[str], cover_source_id: int | None, source_ids: Sequence[int])`, `remove_series(series_id)`
    - `cards() -> list[SeriesCard]`, `card(series_id) -> SeriesCard | None`
    - `touch(series_id, source_id: int, where: Sequence[str])`, `set_favorite(series_id, on: bool)`, `mark_read(series_id)`, `mark_unread(series_id)`
    - `shelves() -> list[Shelf]` (по `created_at`, `id`), `check_shelf_name(name, except_id: int | None = None) -> str | None` (текст ошибки или `None`), `add_shelf(name, icon) -> int`, `rename_shelf(shelf_id, name)`, `set_shelf_icon(shelf_id, icon)`, `delete_shelf(shelf_id)`, `add_to_shelf(shelf_id, series_ids)`, `remove_from_shelf(shelf_id, series_ids)`

- [ ] **Step 1: Падающие тесты.** Вспомогательная функция в тесте:

```python
def make_series(cat, st, tmp_path, name, pages=(10, 10), root_id=None, base=None):
    folder = (base or tmp_path) / name; folder.mkdir(parents=True)
    ids = []
    for i, n in enumerate(pages):
        f = folder / f"c{i + 1}.cbz"; f.write_bytes(b"1")
        ids.append(st.register(f, 1, 1.0, f"{name}{i}", n, ()).id)
    sid = cat.ensure_series(folder, root_id)
    cat.update_series(sid, title=name, formats=["CBZ"], cover_source_id=ids[0], source_ids=ids)
    return sid, ids

def test_status_and_progress(cat, st, tmp_path):
    sid, ids = make_series(cat, st, tmp_path, "Berserk")
    c = cat.card(sid); assert (c.status, c.progress, c.pages_total) == (Status.NOT_STARTED, 0.0, 20)
    st.set_progress(ids[0], 4, False, 0.5)
    c = cat.card(sid); assert c.status is Status.READING and c.progress == 0.25
    for i in ids: st.set_progress(i, 9, True)
    assert cat.card(sid).status is Status.FINISHED and cat.card(sid).progress == 1.0

def test_mark_read_and_unread(cat, st, tmp_path):
    sid, ids = make_series(cat, st, tmp_path, "S"); st.set_progress(ids[0], 4, False, 0.5)
    cat.touch(sid, ids[0], ["Глава 1", "стр. 5"])
    cat.mark_read(sid)
    assert cat.card(sid).status is Status.FINISHED and st.progress(ids[0]).position == 4
    cat.mark_unread(sid)
    c = cat.card(sid); assert c.status is Status.NOT_STARTED and c.where == () and st.progress(ids[0]) is None

def test_touch_and_favorite(cat, st, tmp_path):
    sid, ids = make_series(cat, st, tmp_path, "S")
    cat.touch(sid, ids[1], ["Глава 2", "стр. 3"]); cat.set_favorite(sid, True)
    c = cat.card(sid)
    assert c.where == ("Глава 2", "стр. 3") and c.last_source_id == ids[1] and c.last_opened_at and c.favorite

def test_shelves_unique_multi_and_delete(cat, st, tmp_path):
    sid, _ = make_series(cat, st, tmp_path, "S")
    a = cat.add_shelf("Романтика", "heart"); b = cat.add_shelf("Сэйнэн", "sword")
    for dup in ("романтика", "РОМАНТИКА", "  Романтика "):
        with pytest.raises(CatalogError, match="Такая полка уже есть"): cat.add_shelf(dup, "book")
    with pytest.raises(CatalogError, match="Введите название"): cat.add_shelf("  ", "book")
    with pytest.raises(CatalogError, match="Такая полка уже есть"): cat.rename_shelf(b, "романтика")
    cat.rename_shelf(a, "РОМАНТИКА")                                     # own name in another case is fine
    cat.add_to_shelf(a, [sid]); cat.add_to_shelf(b, [sid]); assert cat.card(sid).shelf_ids == {a, b}
    cat.delete_shelf(a)
    assert [s.name for s in cat.shelves()] == ["Сэйнэн"] and cat.card(sid).shelf_ids == {b}

def test_roots_reject_nested_and_remove_keeps_progress(cat, st, tmp_path):
    lib = tmp_path / "Манга"; lib.mkdir(); rid = cat.add_root(lib)
    for p, text in ((lib, "уже в библиотеке"), (lib / "sub", "уже внутри папки библиотеки"),
                    (tmp_path, "Внутри этой папки уже есть папка библиотеки")):
        p.mkdir(exist_ok=True)
        with pytest.raises(CatalogError, match=text): cat.add_root(p)
    sid, ids = make_series(cat, st, tmp_path, "S", root_id=rid, base=lib)
    st.set_progress(ids[0], 4, False, 0.5); shelf = cat.add_shelf("Полка", "book"); cat.add_to_shelf(shelf, [sid])
    cat.remove_root(rid)
    assert cat.cards() == [] and st.progress(ids[0]).position == 4
    rid = cat.add_root(lib); sid = cat.ensure_series(lib / "S", rid)
    cat.update_series(sid, title="S", formats=["CBZ"], cover_source_id=ids[0], source_ids=ids)
    assert cat.card(sid).status is Status.READING and cat.card(sid).shelf_ids == frozenset()

def test_remove_series_only_manual(cat, st, tmp_path):
    lib = tmp_path / "lib"; lib.mkdir(); rid = cat.add_root(lib)
    manual, _ = make_series(cat, st, tmp_path, "M"); scanned, _ = make_series(cat, st, tmp_path, "R", root_id=rid, base=lib)
    cat.remove_series(manual); cat.remove_series(scanned)
    assert [c.title for c in cat.cards()] == ["R"]

def test_ensure_series_adopts_root_and_marks_unavailable(cat, st, tmp_path):
    sid, _ = make_series(cat, st, tmp_path, "S")
    rid = cat.add_root(tmp_path)
    assert cat.ensure_series(tmp_path / "S", rid) == sid and cat.card(sid).root_id == rid
    shutil.rmtree(tmp_path / "S"); assert not cat.card(sid).available

def test_relocate_root(cat, st, tmp_path):
    old = tmp_path / "old"; old.mkdir(); rid = cat.add_root(old)
    sid, ids = make_series(cat, st, tmp_path, "S", root_id=rid, base=old)
    st.set_progress(ids[0], 4, False, 0.5); st.set_series_prefs(old / "S", SeriesPrefs("ltr", "spread"))
    new = tmp_path / "new"; (old).rename(new)
    assert not cat.roots()[0].available
    cat.relocate_root(rid, new)
    c = cat.card(sid)
    assert cat.roots()[0].path == new and c.path == new / "S" and c.available
    assert st.find_by_path(new / "S" / "c1.cbz").id == ids[0] and st.progress(ids[0]).position == 4
    assert st.series_prefs(new / "S") == SeriesPrefs("ltr", "spread")

@pytest.mark.skipif(sys.platform != "win32", reason="регистр путей различается только в Windows")
def test_same_series_in_other_case(cat, st, tmp_path):
    folder = tmp_path / "Берсерк"; folder.mkdir()
    assert cat.ensure_series(folder) == cat.ensure_series(Path(str(folder).upper()))
```

  Фикстуры `st` (`Store(tmp_path / "library.db")`) и `cat` (`Catalog(st)`) объявить в этом файле.

- [ ] **Step 2: Запустить** `pytest tests/test_catalog.py -q` → FAIL (нет модуля).

- [ ] **Step 3: Реализовать.**
  - `add_root`: тексты ошибок: «Эта папка уже в библиотеке», «Эта папка уже внутри папки библиотеки «{имя}»», «Внутри этой папки уже есть папка библиотеки «{имя}»». Вложенность проверять через `classify.is_inside` (задача 4 переносит туда `_inside` из `controller.py`; в этой задаче функцию сразу создать в `classify.py`, а в `controller.py` заменить `_inside` импортом `is_inside`, тест `test_inside_drive_root` перевести на новое имя).
  - `remove_root`: удаление строки `roots`. Серии уходят каскадом, полки серий тоже, у источников `series_id` становится `NULL`, прогресс и разметка остаются.
  - `relocate_root`: если новый путь уже занят другой папкой библиотеки, `CatalogError("Эта папка уже в библиотеке")`. Иначе в одной транзакции заменить начало пути у строк `roots`, `series`, `sources` (и `path`, и `path_key`) и у ключей `series_prefs`. Совпадение по началу ключа: `key == old_key or key.startswith(old_key + os.sep)`. Новый путь: `str(new) + os.path.abspath(path)[len(os.path.abspath(old)):]`. Писать через `UPDATE OR REPLACE`: если на новом месте уже есть строка, она уступает старой (у старой прогресс и разметка).
  - `ensure_series`: строка с тем же `path_key` → вернуть её `id`, а если у неё `root_id IS NULL` и передан `root_id`, записать его. Иначе вставить: `title = path.name` для папки, `path.stem` для файла, `added_at = store.now()`.
  - `update_series`: одной транзакцией обновить название, `formats` (через запятую), обложку; снять `series_id` с источников серии, которых нет в `source_ids`; поставить `series_id` перечисленным.
  - `remove_series`: удаляет только строку с `root_id IS NULL`, иначе ничего не делает.
  - `cards`: один запрос `series LEFT JOIN sources LEFT JOIN progress GROUP BY series.id`. `pages_read = Σ(page_count, если finished, иначе fraction × page_count)`. `opened` — число источников с прогрессом, `finished` — с отметкой. `shelf_ids` отдельным запросом к `shelf_series`, `available = path.exists()`, `where = tuple(json.loads(last_label))`.
  - `touch`: `last_opened_at = store.now()`, `last_source_id`, `last_label = json.dumps(list(where), ensure_ascii=False)`.
  - `mark_read`: `INSERT INTO progress(source_id, position, finished, fraction, updated_at) SELECT id, 0, 1, 1.0, 0 FROM sources WHERE series_id=? ON CONFLICT(source_id) DO UPDATE SET finished=1, fraction=1.0`. Позиция и `updated_at` сохраняются, иначе сбился бы выбор последнего открытого тома.
  - `mark_unread`: удалить прогресс источников серии, `last_source_id = NULL`, `last_label = '[]'`.
  - Полки: `name.strip()`, ключ `name.strip().casefold()`. Пустое имя → «Введите название», занятый ключ (кроме `except_id`) → «Такая полка уже есть». `add_shelf`/`rename_shelf` бросают `CatalogError` с этим текстом. `add_to_shelf` — `INSERT OR IGNORE`.

- [ ] **Step 4: Прогнать** `pytest -q` → PASS. **Step 5: Commit** `feat: library catalog with roots, series, shelves and read marks`.

---

### Task 3: Выборки каталога: разделы, поиск, сортировки, подписи

**Files:**
- Modify: `src/mangareader/library/catalog.py`
- Test: `tests/test_catalog_views.py`

**Interfaces:**
- Consumes: `SeriesCard`, `Status`, `sources.natsort.natural_key`
- Produces (в `catalog.py`, без обращения к базе):
  - `SectionKind` (StrEnum): `ALL = "all"`, `FAVORITES = "favorites"`, `FORMAT = "format"`, `SHELF = "shelf"`; `Section(kind: SectionKind = SectionKind.ALL, value: str | int | None = None)` (frozen)
  - `Sort` (StrEnum): `RECENT = "recent"`, `TITLE = "title"`, `ADDED = "added"`
  - `FORMAT_ORDER = ("CBZ", "CBR", "CB7", "ZIP", "RAR", "7Z", "PDF", "EPUB", "FB2", "MOBI", "XPS", "TXT", "Папка")`
  - `format_label(path: Path) -> str` (папка → «Папка», `.oxps` → «XPS», иначе расширение заглавными); `series_formats(paths: Iterable[Path]) -> list[str]` (по частоте, при равенстве по `FORMAT_ORDER`)
  - `normalize(text: str) -> str` (`casefold()`, «ё» → «е»)
  - `filter_cards(cards, section=Section(), query="", status: Status | None = None, sort=Sort.RECENT) -> list[SeriesCard]`
  - `continue_reading(cards, limit=5) -> list[SeriesCard]`, `format_counts(cards) -> list[tuple[str, int]]`
  - `percent(card) -> int`, `tile_caption(card) -> str`, `continue_caption(card) -> str`, `when_text(ts: float, now: float) -> str`

- [ ] **Step 1: Падающие тесты.** Вспомогательная `card(**kw)` в `tests/helpers.py` собирает `SeriesCard` с нейтральными значениями по умолчанию (`available=True`, `formats=("CBZ",)`, `sources=1`, остальное нули и пустые значения). Её же используют тесты задач 7–9.

```python
def test_search_casefold_and_yo():
    cards = [card(id=1, title="Ёлки"), card(id=2, title="BERSERK"), card(id=3, title="Vagabond")]
    assert [c.id for c in filter_cards(cards, query="елки")] == [1]
    assert [c.id for c in filter_cards(cards, query="ЕЛК")] == [1]
    assert [c.id for c in filter_cards(cards, query="serk")] == [2]

def test_sections_and_status():
    cards = [card(id=1, favorite=True, formats=("CBZ", "EPUB")), card(id=2, formats=("PDF",), shelf_ids=frozenset({7})),
             card(id=3, opened=1, pages_total=10, pages_read=3)]
    ids = lambda **kw: [c.id for c in filter_cards(cards, sort=Sort.ADDED, **kw)]
    assert ids(section=Section(SectionKind.FAVORITES)) == [1]
    assert ids(section=Section(SectionKind.FORMAT, "EPUB")) == [1]
    assert ids(section=Section(SectionKind.SHELF, 7)) == [2]
    assert ids(status=Status.READING) == [3] and set(ids(status=Status.NOT_STARTED)) == {1, 2}

def test_sorts():
    cards = [card(id=1, title="Том 10", added_at=1), card(id=2, title="Том 2", added_at=3, last_opened_at=5),
             card(id=3, title="том 3", added_at=2, last_opened_at=9), card(id=4, title="А", added_at=4)]
    assert [c.id for c in filter_cards(cards, sort=Sort.RECENT)] == [3, 2, 4, 1]
    assert [c.id for c in filter_cards(cards, sort=Sort.TITLE)] == [4, 2, 3, 1]
    assert [c.id for c in filter_cards(cards, sort=Sort.ADDED)] == [4, 2, 3, 1]

def test_continue_reading():
    reading = [card(id=i, opened=1, pages_total=10, pages_read=1, last_opened_at=i) for i in range(1, 8)]
    other = [card(id=20, opened=1, finished=1, last_opened_at=100), card(id=21, opened=1, pages_total=10)]
    assert [c.id for c in continue_reading(reading + other)] == [7, 6, 5, 4, 3]   # 21 never opened in the reader

def test_formats():
    assert series_formats([Path("a.cbz"), Path("b.CBZ"), Path("c.pdf"), Path("d.oxps")]) == ["CBZ", "PDF", "XPS"]
    cards = [card(formats=("PDF",)), card(formats=("CBZ", "PDF"))]
    assert format_counts(cards) == [("CBZ", 1), ("PDF", 2)]

def test_captions():
    r = card(opened=1, pages_total=100, pages_read=18, where=("Том 3", "Глава 21", "стр. 45"))
    assert tile_caption(r) == "Том 3 · 18%" and continue_caption(r) == "Том 3 · Глава 21 · стр. 45"
    book = card(opened=1, pages_total=100, pages_read=62)
    assert tile_caption(book) == continue_caption(book) == "62%"
    assert tile_caption(card(opened=1, pages_total=1000, pages_read=999.5)) == "99%"
    assert tile_caption(card(opened=1, finished=1)) == "прочитано" and tile_caption(card()) == "не начато"
    assert tile_caption(card(available=False, opened=1, finished=1)) == "недоступно"

def test_when_text():
    now = datetime(2026, 10, 30, 12).timestamp(); day = 86400
    assert [when_text(now - d * day, now) for d in (0, 1, 3, 5)] == ["сегодня", "вчера", "3 дня назад", "5 дней назад"]
    assert when_text(now - 10 * day, now) == "20.10.2026"
```

- [ ] **Step 2: Запустить** → FAIL. **Step 3: Реализовать.**
  - `filter_cards`: сначала раздел, потом статус, потом поиск (`normalize(query.strip()) in normalize(title)`), потом сортировка.
    - `RECENT`: открытые по убыванию `last_opened_at`, затем неоткрытые по убыванию `added_at`;
    - `TITLE`: `natural_key(normalize(title))`;
    - `ADDED`: по убыванию `added_at`.
  - `continue_reading`: статус `READING` и `last_opened_at is not None`.
  - `format_counts`: только форматы, которые есть, в порядке `FORMAT_ORDER`.
  - `percent`: `floor(progress * 100)`; для не прочитанной до конца серии не больше 99.
  - `when_text`: сравнение по календарным дням местного времени. 0 → «сегодня», 1 → «вчера», 2–6 → «N дня/дней назад» (2–4 «дня», 5–6 «дней»), иначе дата `%d.%m.%Y`.
  - `tile_caption`: `where[0] · N%` или `N%`. `continue_caption`: `" · ".join(where)` или `N%`.

- [ ] **Step 4: Прогнать** → PASS. **Step 5: Commit** `feat: catalog filters, search, sorting and captions`.

---

### Task 4: Сканирование папок библиотеки и выбор серии при «Открыть»

**Files:**
- Modify: `src/mangareader/library/classify.py`
- Create: `src/mangareader/library/library_scan.py`
- Test: `tests/test_library_scan.py`, `tests/test_classify.py`

**Interfaces:**
- Consumes: `Catalog`, `Root`, `scan_series`, `classify.list_children/is_volume_folder/find_series_root`, `format_label`, `series_formats`
- Produces:
  - `classify.is_inside(path, folder) -> bool` (уже создана в задаче 2)
  - `classify_series(root, probe)`: если `root` — файл или папка с картинками прямо внутри, дерево из одного источника, `title` — имя без расширения
  - `library_scan.DOCUMENT_EXTS = frozenset({".pdf", ".epub", ".fb2", ".mobi", ".xps", ".oxps", ".txt"})`
  - `library_scan.ScanReport(series_ids: list[int], failed: list[tuple[Path, str]])` (оба поля по умолчанию пустые)
  - `series_candidates(root: Path) -> list[Path]`: видимые папки верхнего уровня и файлы с расширением из `SOURCE_EXTS` прямо в корне, в естественном порядке
  - `record_tree(catalog, series_id, tree: SeriesTree) -> None`
  - `scan_root(catalog, store, ctx, root: Root, on_series: Callable[[int], None] = lambda _: None, cancelled: Callable[[], bool] = lambda: False) -> ScanReport`
  - `scan_library(catalog, store, ctx, on_series=..., cancelled=...) -> ScanReport` (все доступные папки по очереди)
  - `series_path_for(path: Path, roots: Sequence[Root]) -> tuple[Path, int | None]`

- [ ] **Step 1: Падающие тесты.** Функция `library(tmp_path)` лежит в `tests/helpers.py`: её используют и задачи 9, 12, 13.

```python
def library(tmp_path):
    lib = tmp_path / "Манга"
    for v in (1, 2): make_zip(lib / "Berserk" / f"Vol {v:02}.cbz", {f"{i}.png": encode(page_image(i), "PNG") for i in range(3)})
    make_epub(lib / "Ведьмак.epub", 30)
    for i in range(2): (lib / "Artbook").mkdir(parents=True, exist_ok=True); (lib / "Artbook" / f"{i}.png").write_bytes(encode(page_image(i), "PNG"))
    (lib / "empty").mkdir(); make_zip(lib / ".hidden" / "x.cbz", {"1.png": encode(page_image(1), "PNG")})
    (lib / "notes.txt").write_text("x", encoding="utf-8")
    return lib

def test_series_from_root(tmp_path, ctx):
    st = Store(tmp_path / "db"); cat = Catalog(st); lib = library(tmp_path); rid = cat.add_root(lib)
    report = scan_library(cat, st, ctx)
    cards = {c.title: c for c in cat.cards()}
    assert sorted(cards) == ["Artbook", "Berserk", "Ведьмак"] and len(report.series_ids) == 3
    assert cards["Berserk"].formats == ("CBZ",) and cards["Berserk"].pages_total == 6 and cards["Berserk"].sources == 2
    assert cards["Artbook"].formats == ("Папка",) and cards["Ведьмак"].formats == ("EPUB",)
    assert all(c.root_id == rid and c.cover_source_id for c in cards.values())

def test_rescan_keeps_vanished_series_and_missing_root(tmp_path, ctx):
    st = Store(tmp_path / "db"); cat = Catalog(st); lib = library(tmp_path); cat.add_root(lib); scan_library(cat, st, ctx)
    shutil.rmtree(lib / "Berserk"); scan_library(cat, st, ctx)
    assert not next(c for c in cat.cards() if c.title == "Berserk").available
    shutil.rmtree(lib); scan_library(cat, st, ctx)                      # the whole library folder is gone
    assert len(cat.cards()) == 3 and not cat.roots()[0].available

def test_broken_file_reported_others_scanned(tmp_path, ctx):
    st = Store(tmp_path / "db"); cat = Catalog(st); lib = library(tmp_path)
    (lib / "Berserk" / "Vol 03.cbz").write_bytes(b"not a zip"); cat.add_root(lib)
    report = scan_library(cat, st, ctx)
    assert [p.name for p, _ in report.failed] == ["Vol 03.cbz"] and len(cat.cards()) == 3

def test_cancelled_scan_stops(tmp_path, ctx):
    st = Store(tmp_path / "db"); cat = Catalog(st); cat.add_root(library(tmp_path))
    assert scan_library(cat, st, ctx, cancelled=lambda: True).series_ids == [] and cat.cards() == []

def test_record_tree_unlinks_removed_sources(tmp_path, ctx):
    st = Store(tmp_path / "db"); cat = Catalog(st); lib = library(tmp_path); cat.add_root(lib); scan_library(cat, st, ctx)
    (lib / "Berserk" / "Vol 02.cbz").unlink(); scan_library(cat, st, ctx)
    assert next(c for c in cat.cards() if c.title == "Berserk").sources == 1

def test_series_path_for(tmp_path):
    lib = tmp_path / "lib"; (lib / "S" / "Vol 1").mkdir(parents=True); root = Root(5, lib, 0.0)
    assert series_path_for(lib / "S" / "Vol 1" / "c1.cbz", [root]) == (lib / "S", 5)
    assert series_path_for(lib / "Книга.epub", [root]) == (lib / "Книга.epub", 5)
    dl = tmp_path / "Загрузки"; dl.mkdir()
    assert series_path_for(dl / "Книга.epub", [root]) == (dl / "Книга.epub", None)
    assert series_path_for(dl / "c1.cbz", [root]) == (dl, None)
    vol = tmp_path / "Series" / "Том 1"; vol.mkdir(parents=True); make_zip(vol / "Глава 1.cbz", {"1.png": b"x"})
    assert series_path_for(vol, [root]) == (tmp_path / "Series", None)
```

  В `tests/test_classify.py`:

```python
def test_single_file_and_image_folder_series(tmp_path):
    f = tmp_path / "Книга.epub"; f.write_bytes(b"x")
    tree = classify_series(f, lambda p: SourceInfo(30, (), None, (), 1))
    assert tree.title == "Книга" and [e.path for e in tree.reading_order()] == [f]
    art = tmp_path / "Artbook"; art.mkdir(); (art / "1.png").write_bytes(b"x")
    assert [e.path for e in classify_series(art, lambda p: SourceInfo(1, (), None, (), 2)).reading_order()] == [art]
```

- [ ] **Step 2: Запустить** → FAIL. **Step 3: Реализовать.**
  - `scan_root`: если папка библиотеки недоступна, пустой отчёт. Иначе для каждого кандидата, пока не `cancelled()`:
    1. `tree = scan_series(кандидат, store, ctx)`;
    2. ошибки дерева добавить в `failed`;
    3. если в дереве нет узлов, пропустить кандидата;
    4. иначе `ensure_series(кандидат, root.id)` → `record_tree` → `on_series(id)`.

    Исключение на одном кандидате записать в журнал, добавить в `failed` с текстом «Файл повреждён или не поддерживается» и перейти к следующему. Серии, которых больше нет среди кандидатов, не трогать.
  - `record_tree`:
    - источники — `record_id` записей дерева, у которых он есть;
    - форматы — `series_formats` путей всех записей;
    - обложка — первый незапертый источник с `record_id`;
    - название — `tree.title`.
  - `series_path_for`: правила по порядку, первое подходящее.

    | Что открыли | Серия |
    |---|---|
    | Путь внутри папки библиотеки | её первый уровень: `root.path / Path(os.path.relpath(path, root.path)).parts[0]`, плюс `root.id` |
    | Файл с расширением из `DOCUMENT_EXTS` | сам файл |
    | Папка без картинок внутри | её родитель, если это папка тома (`is_volume_folder`), иначе сама папка |
    | Всё остальное | `find_series_root(path)` |

- [ ] **Step 4: Прогнать** `pytest -q` → PASS. **Step 5: Commit** `feat: scan library folders into series`.

---

### Task 5: Модуль размеров и иконки полок

**Files:**
- Create: `src/mangareader/ui/style.py`, `src/mangareader/ui/icons/__init__.py`, `src/mangareader/ui/icons/lucide/<48 имён>.svg`, `src/mangareader/ui/icons/lucide/LICENSE`
- Modify: `pyproject.toml`, `packaging/mangareader.spec`
- Test: `tests/test_icons.py`

**Interfaces:**
- Produces:
  - `style`: `NAV_WIDTH = 220`, `TILE_COVER = QSize(150, 213)`, `TILE_GRID = QSize(172, 292)`, `TILE_RADIUS = 6`, `PROGRESS_HEIGHT = 4`, `CONTINUE_COVER = QSize(54, 77)`, `CONTINUE_CARD_WIDTH = 250`, `READER_NAV_WIDTH = 300`, `VOLUME_COVER = QSize(32, 45)`, `NAV_THUMB = QSize(78, 112)`, `SHELF_ICON = 18`, `DIALOG_ICON = 28`, `UNAVAILABLE_OPACITY = 0.4`, `FAVORITE_COLOR = "#f2c94c"`, `BADGE_BG = QColor(0, 0, 0, 170)`, `PLACEHOLDER = QColor(60, 60, 60)`; функции `text_color()`, `muted_color()`, `accent_color()` берут `WindowText`, `PlaceholderText` и `Highlight` из текущей палитры приложения
  - `icons.SHELF_ICONS: tuple[str, ...]`: 48 имён в порядке спецификации (раздел 6)
  - `icons.DEFAULT_SHELF_ICON = "book"`, `icons.ICON_DIR = Path(__file__).parent / "lucide"`
  - `icons.icon_pixmap(name: str, size: int, color: QColor | str) -> QPixmap` (неизвестное имя → `DEFAULT_SHELF_ICON`; кэш по `(name, size, color)`), `icons.icon(name, size, color) -> QIcon`

- [ ] **Step 1: Падающие тесты**

```python
def test_all_shelf_icons_render(qapp):
    assert len(SHELF_ICONS) == 48 == len(set(SHELF_ICONS))
    for name in SHELF_ICONS:
        image = icon_pixmap(name, 24, "#ff0000").toImage()
        assert (ICON_DIR / f"{name}.svg").exists() and not image.isNull()
        assert any(image.pixelColor(x, y).red() > 200 for x in range(24) for y in range(24)), name

def test_unknown_icon_falls_back(qapp):
    assert icon_pixmap("no-such", 24, "#fff").toImage() == icon_pixmap(DEFAULT_SHELF_ICON, 24, "#fff").toImage()

def test_licence_and_packaging():
    assert "ISC" in (ICON_DIR / "LICENSE").read_text(encoding="utf-8")
    root = Path(__file__).parents[1]
    assert "icons" in (root / "packaging" / "mangareader.spec").read_text(encoding="utf-8")
    assert "lucide/*.svg" in (root / "pyproject.toml").read_text(encoding="utf-8")
```

- [ ] **Step 2: Запустить** → FAIL. **Step 3: Реализовать.**
  - Скопировать 48 файлов `icons/<имя>.svg` и `LICENSE` из `lucide-static@1.49.0`.
  - `icon_pixmap`: заменить `currentColor` на `QColor(color).name()`, отрисовать через `QSvgRenderer` в `QImage(size, size, ARGB32_Premultiplied)` с прозрачным фоном.
  - `pyproject.toml`: секция `[tool.setuptools.package-data]` с `"mangareader.ui.icons" = ["lucide/*.svg", "lucide/LICENSE"]`.
  - Спека PyInstaller: `datas=[(str(ROOT / "src" / "mangareader" / "ui" / "icons" / "lucide"), "mangareader/ui/icons/lucide")]`.

- [ ] **Step 4: Прогнать** → PASS. **Step 5: Commit** `feat: layout constants and bundled shelf icons`.

---

### Task 6: Обложки и общие сервисы

**Files:**
- Create: `src/mangareader/render/covers.py`
- Modify: `src/mangareader/ui/reader/controller.py` (`Services`, `make_services`)
- Test: `tests/test_covers.py`

**Interfaces:**
- Consumes: `Store.source_by_id`, `ThumbnailStore.get/create`, `open_source`, `pil_to_qimage`
- Produces:
  - `CoverLoader(store: Store, thumbs: ThumbnailStore, ctx: SourceContext, parent=None)`, сигнал `cover_ready(int)` (id источника)
  - `CoverLoader.cover(source_id: int | None) -> QImage | None`: отдаёт готовую обложку или ставит её в фоновую очередь и возвращает `None`
  - `CoverLoader.pending -> set[int]`
  - `COVER_CACHE = 300` (сколько обложек держать в памяти)
  - `Services` получает поля `catalog: Catalog` и `covers: CoverLoader`, `make_services` создаёт их

- [ ] **Step 1: Падающие тесты**

```python
def prober_id(st, ctx, path):
    return SourceProber(st, ctx)(path).record_id

def test_cover_for_archive(qtbot, tmp_path, ctx):
    st = Store(tmp_path / "db"); thumbs = ThumbnailStore(tmp_path / "thumbs")
    arc = make_zip(tmp_path / "S" / "v.cbz", {"1.png": encode(page_image(1, (600, 900)), "PNG")})
    covers = CoverLoader(st, thumbs, ctx); sid = prober_id(st, ctx, arc)
    with qtbot.waitSignal(covers.cover_ready):
        assert covers.cover(sid) is None
    assert covers.cover(sid).height() == THUMB_HEIGHT and thumbs.get(st.source_by_id(sid).fingerprint, 0)

def test_cover_reuses_thumbnail_on_disk(qtbot, tmp_path, ctx, monkeypatch):
    st = Store(tmp_path / "db"); thumbs = ThumbnailStore(tmp_path / "thumbs")
    arc = make_zip(tmp_path / "S" / "v.cbz", {"1.png": encode(page_image(1), "PNG")}); sid = prober_id(st, ctx, arc)
    with open_source(arc, ctx) as src: thumbs.create(src, 0, st.source_by_id(sid).fingerprint)
    monkeypatch.setattr(covers_module, "open_source", lambda *a, **k: pytest.fail("must not open"))
    covers = CoverLoader(st, thumbs, ctx)
    with qtbot.waitSignal(covers.cover_ready): covers.cover(sid)

def test_missing_or_locked_gives_no_cover(qtbot, tmp_path, ctx):
    st = Store(tmp_path / "db"); covers = CoverLoader(st, ThumbnailStore(tmp_path / "t"), ctx)
    arc = make_zip(tmp_path / "S" / "v.cbz", {"1.png": encode(page_image(1), "PNG")}); sid = prober_id(st, ctx, arc)
    arc.unlink(); covers.cover(sid)
    qtbot.waitUntil(lambda: not covers.pending, timeout=5000)
    assert covers.cover(sid) is None and covers.cover(None) is None and not covers.pending   # no retry loop
```

- [ ] **Step 2: Запустить** → FAIL. **Step 3: Реализовать.**
  - Фоновая задача:
    1. `record = store.source_by_id(id)`;
    2. если на диске уже есть миниатюра `thumbs.get(record.fingerprint, 0)`, взять её;
    3. иначе `open_source(record.path, ctx)` → `thumbs.create(source, 0, fingerprint)` → `close()`.
  - Любое исключение записать в журнал и запомнить id в наборе неудач: повторно этот id до перезапуска не грузить.
  - Задачи идут через `QThreadPool.globalInstance()`. `RuntimeError` при отправке сигнала (окно уже закрыто) глушить, как в `controller._start_scan`.
  - Кэш в памяти — `OrderedDict` на `COVER_CACHE` записей.
  - Архивы RAR и 7z распаковываются до первой страницы, затем `close()` останавливает распаковку.

- [ ] **Step 4: Прогнать** `pytest -q` → PASS. **Step 5: Commit** `feat: background series covers`.

---

### Task 7: Сетка плиток

**Files:**
- Create: `src/mangareader/ui/library/__init__.py`, `src/mangareader/ui/library/tiles.py`
- Test: `tests/test_tiles.py`

**Interfaces:**
- Consumes: `SeriesCard`, `tile_caption`, `CoverLoader`, `style.*`
- Produces:
  - `SERIES_MIME = "application/x-mangareader-series"`, `CARD_ROLE = Qt.UserRole + 1`
  - `TileModel(covers: CoverLoader)` (`QAbstractListModel`):
    - `set_cards(cards)`, `card_at(row) -> SeriesCard | None` (строка 0 — плитка «Открыть», для неё `None`);
    - `DisplayRole`: «Открыть» или название; `ToolTipRole`: путь серии;
    - `mimeData(indexes)`: id серий через запятую в `SERIES_MIME`; плитку «Открыть» перетаскивать нельзя.
  - `series_ids_from_mime(mime: QMimeData) -> list[int]`
  - `TileDelegate(covers)`: рисует плитку, размер — `style.TILE_GRID`
  - `TileGrid(QListView)`: режим значков, `Static`, перенос строк, `DragOnly`, множественный выбор, `gridSize = TILE_GRID`

- [ ] **Step 1: Падающие тесты**

```python
def test_open_tile_first(qtbot, services):
    model = TileModel(services.covers); model.set_cards([card(id=5, title="Berserk")])
    assert model.rowCount() == 2 and model.data(model.index(0)) == "Открыть" and model.card_at(1).id == 5
    assert not model.flags(model.index(0)) & Qt.ItemIsDragEnabled and model.flags(model.index(1)) & Qt.ItemIsDragEnabled

def test_mime_roundtrip(qtbot, services):
    model = TileModel(services.covers); model.set_cards([card(id=5), card(id=9)])
    assert series_ids_from_mime(model.mimeData([model.index(1), model.index(2)])) == [5, 9]

def test_cover_ready_updates_row(qtbot, services):
    model = TileModel(services.covers); model.set_cards([card(id=5, cover_source_id=42)])
    with qtbot.waitSignal(model.dataChanged) as blocker: services.covers.cover_ready.emit(42)
    assert blocker.args[0].row() == 1

def test_grid_paints_all_kinds(qtbot, services):
    grid = TileGrid(); model = TileModel(services.covers); grid.setModel(model); grid.setItemDelegate(TileDelegate(services.covers))
    model.set_cards([card(id=1, favorite=True), card(id=2, available=False), card(id=3, opened=1, finished=1)])
    qtbot.addWidget(grid); grid.resize(800, 400); grid.show()
    assert not grid.grab().isNull()
```

  Фикстура `services(qapp)` в `tests/conftest.py`: `make_services(resolve_data_location())`, после теста `shutdown()`.

- [ ] **Step 2: Запустить** → FAIL. **Step 3: Реализовать.** Отрисовка плитки сверху вниз:
  1. обложка по центру `TILE_COVER` с сохранением пропорций, а пока её нет — прямоугольник цвета `style.PLACEHOLDER`;
  2. значок `main_format` в левом верхнем углу на фоне `BADGE_BG`;
  3. «★» цветом `FAVORITE_COLOR` справа сверху, если серия в избранном;
  4. название в одну строку с многоточием;
  5. полоска прогресса высотой `PROGRESS_HEIGHT` цветом `accent_color()`;
  6. подпись `tile_caption` цветом `muted_color()`.

  Недоступная серия рисуется с прозрачностью `UNAVAILABLE_OPACITY`. Плитка «Открыть»: пунктирная рамка, «＋», «Открыть» и строкой ниже «файл или папку». Выделенная плитка обводится цветом `accent_color()`.

- [ ] **Step 4: Прогнать** → PASS. **Step 5: Commit** `feat: library tile grid`.

---

### Task 8: Левая навигация библиотеки и окно полки

**Files:**
- Create: `src/mangareader/ui/library/nav.py`, `src/mangareader/ui/library/shelf_dialog.py`
- Modify: `src/mangareader/ui/dialogs/errors.py`
- Test: `tests/test_library_nav.py`

**Interfaces:**
- Consumes: `SeriesCard`, `Shelf`, `Section`, `SectionKind`, `format_counts`, `Catalog.check_shelf_name`, `icons.*`, `SERIES_MIME`, `series_ids_from_mime`
- Produces:
  - `LibraryNav(QWidget)`, сигналы:
    - `section_selected(object)` (`Section`), `add_shelf_requested()`, `settings_requested()`;
    - `shelf_rename_requested(int)`, `shelf_icon_requested(int)`, `shelf_delete_requested(int)`;
    - `series_dropped(int, list)` (id полки, id серий).
  - Поля `tree: QTreeWidget` (2 колонки: название и количество) и `settings_button: QPushButton` («⚙ Настройки», внизу).
  - Методы `set_data(cards, shelves)`, `section() -> Section`, `select(section)`, `item_for(section) -> QTreeWidgetItem | None`, `shelf_menu(shelf_id) -> QMenu`.
  - `ShelfDialog(parent, catalog, *, title: str, name: str = "", icon: str = DEFAULT_SHELF_ICON, shelf_id: int | None = None)`:
    - поля `name_edit`, `icon_buttons: dict[str, QToolButton]` (по 8 в ряд, выбирается одна), `error_label`;
    - метод `value() -> tuple[str, str]`.
  - `ask_shelf(parent, catalog, *, title, name="", icon=DEFAULT_SHELF_ICON, shelf_id=None) -> tuple[str, str] | None`
  - `errors.confirm(parent, text: str) -> bool` (`QMessageBox.question`, кнопки «Да» и «Нет»)

- [ ] **Step 1: Падающие тесты**

```python
def test_items_and_counts(qtbot):
    nav = LibraryNav(); qtbot.addWidget(nav)
    nav.set_data([card(id=1, favorite=True, formats=("CBZ",), shelf_ids=frozenset({3})), card(id=2, formats=("EPUB", "CBZ"))],
                 [Shelf(3, "Сэйнэн", "sword", 0)])
    texts = lambda item: (item.text(0), item.text(1))
    assert texts(nav.item_for(Section())) == ("▦ Все", "2") and texts(nav.item_for(Section(SectionKind.FAVORITES))) == ("★ Избранное", "1")
    assert texts(nav.item_for(Section(SectionKind.FORMAT, "EPUB"))) == ("EPUB", "1")
    assert nav.item_for(Section(SectionKind.FORMAT, "PDF")) is None
    assert texts(nav.item_for(Section(SectionKind.SHELF, 3))) == ("Сэйнэн", "1")

def test_click_emits_sections_and_actions(qtbot):
    nav = LibraryNav(); qtbot.addWidget(nav); nav.set_data([], [Shelf(3, "Сэйнэн", "sword", 0)])
    with qtbot.waitSignal(nav.section_selected) as b: nav.tree.itemClicked.emit(nav.item_for(Section(SectionKind.SHELF, 3)), 0)
    assert b.args == [Section(SectionKind.SHELF, 3)]
    add = next(nav.tree.topLevelItem(i) for i in range(nav.tree.topLevelItemCount()) if "Добавить категорию" in nav.tree.topLevelItem(i).text(0))
    with qtbot.waitSignal(nav.add_shelf_requested): nav.tree.itemClicked.emit(add, 0)
    with qtbot.waitSignal(nav.settings_requested): nav.settings_button.click()
    assert [a.text() for a in nav.shelf_menu(3).actions()] == ["Переименовать…", "Сменить иконку…", "Удалить полку"]

def test_drop_series_on_shelf(qtbot, services):
    nav = LibraryNav(); qtbot.addWidget(nav); nav.set_data([card(id=7)], [Shelf(3, "Сэйнэн", "sword", 0)]); nav.show()
    model = TileModel(services.covers); model.set_cards([card(id=7)])
    pos = nav.tree.visualItemRect(nav.item_for(Section(SectionKind.SHELF, 3))).center()
    event = QDropEvent(QPointF(pos), Qt.CopyAction, model.mimeData([model.index(1)]), Qt.LeftButton, Qt.NoModifier)
    with qtbot.waitSignal(nav.series_dropped) as b: nav.tree.dropEvent(event)
    assert b.args == [3, [7]]

def test_shelf_dialog_duplicate_stays_open(qtbot, tmp_path):
    cat = Catalog(Store(tmp_path / "db")); cat.add_shelf("Романтика", "heart")
    dlg = ShelfDialog(None, cat, title="Новая полка"); qtbot.addWidget(dlg)
    dlg.name_edit.setText("романтика"); dlg.accept()
    assert dlg.result() != QDialog.Accepted and dlg.error_label.text() == "Такая полка уже есть"
    dlg.name_edit.setText("Сэйнэн"); dlg.icon_buttons["sword"].click(); dlg.accept()
    assert dlg.result() == QDialog.Accepted and dlg.value() == ("Сэйнэн", "sword") and len(dlg.icon_buttons) == 48
```

- [ ] **Step 2: Запустить** → FAIL. **Step 3: Реализовать.**
  - Пункты дерева сверху вниз:
    - «▦ Все», «★ Избранное»;
    - «Форматы»: только раскрывается, сам не выбирается, без форматов скрыт;
    - заголовок «МОИ ПОЛКИ»: не выбирается;
    - полки: иконка `icons.icon(shelf.icon, SHELF_ICON, text_color())`;
    - «＋ Добавить категорию».
  - Количество — во второй колонке, выровнено вправо. `set_data` сохраняет выбранный раздел, а если его больше нет, выбирает «Все».
  - Перетаскивание: подкласс `QTreeWidget` принимает `SERIES_MIME` только над строкой полки.
  - Правый клик по полке открывает `shelf_menu`.
  - `ShelfDialog.accept`: `catalog.check_shelf_name(name, shelf_id)`. Если вернулся текст ошибки, показать его в `error_label` и не закрывать окно.

- [ ] **Step 4: Прогнать** → PASS. **Step 5: Commit** `feat: library navigation and shelf dialog`.

---

### Task 9: Экран библиотеки

**Files:**
- Create: `src/mangareader/ui/library/continue_row.py`, `src/mangareader/ui/library/page.py`
- Test: `tests/test_library_page.py`

**Interfaces:**
- Consumes: `Services`, `Catalog`, `filter_cards`, `continue_reading`, `continue_caption`, `when_text`, `Section`, `Sort`, `Status`, `TileModel`, `TileDelegate`, `TileGrid`, `LibraryNav`, `shelf_dialog.ask_shelf`, `errors.confirm`, `Toast`
- Produces:
  - `ContinueCard(QFrame)`: сигнал `clicked(int)`; поля `series_id`, `title_label`, `where_label`, `when_label`
  - `ContinueRow(QWidget)`: сигнал `open_series(int)`, методы `set_cards(cards, covers, now: float | None = None)` и `cards() -> list[ContinueCard]`
  - Функция модуля `page.open_in_explorer(path: Path)`: открывает папку серии, а для серии-файла — папку, где он лежит
  - `LibraryPage(services)`:
    - сигналы `open_series(int)`, `open_file_requested()`, `open_folder_requested()`, `settings_requested()`, `refresh_requested()`;
    - поля `nav`, `search`, `status_buttons: dict[Status | None, QToolButton]`, `sort_combo`, `refresh_button`, `continue_row`, `grid`, `model`, `empty_hint`, `content: QStackedWidget`;
    - методы `reload()`, `visible_cards() -> list[SeriesCard]`, `show_tiles()`, `show_settings()`, `set_settings_page(widget)`, `set_scanning(on: bool)`, `tile_menu(series_id) -> QMenu`, `open_menu() -> QMenu`.

- [ ] **Step 1: Падающие тесты.** Фикстура `page(qtbot, services, tmp_path)`:
  1. построить библиотеку `library(tmp_path)` из `tests/helpers.py`;
  2. `catalog.add_root(lib)`, `scan_library(...)`;
  3. `LibraryPage(services)`, `reload()`.

```python
titles = lambda p: [c.title for c in p.visible_cards()]

def test_search_status_and_sort(page, qtbot):
    page.search.setText("ведь"); assert titles(page) == ["Ведьмак"]
    page.search.clear(); page.status_buttons[Status.READING].click(); assert titles(page) == []
    page.status_buttons[None].click(); page.sort_combo.setCurrentIndex(page.sort_combo.findData(Sort.TITLE))
    assert titles(page) == ["Artbook", "Berserk", "Ведьмак"]
    assert page.sort_combo.itemText(0) == "Недавно открытые"

def test_continue_row_only_in_all(page, services):
    c = next(c for c in services.catalog.cards() if c.title == "Berserk"); src = c.cover_source_id
    services.store.set_progress(src, 1, False, 0.5); services.catalog.touch(c.id, src, ["Том 1", "стр. 2"]); page.reload()
    assert [k.series_id for k in page.continue_row.cards()] == [c.id] and page.continue_row.isVisibleTo(page)
    assert page.continue_row.cards()[0].where_label.text() == "Том 1 · стр. 2"
    page.nav.select(Section(SectionKind.FAVORITES)); assert not page.continue_row.isVisibleTo(page)

def test_tile_menu_favorite_and_new_shelf(page, services, monkeypatch):
    monkeypatch.setattr(shelf_dialog, "ask_shelf", lambda *a, **k: ("Сэйнэн", "sword"))
    sid = page.visible_cards()[0].id
    action = lambda text: next(a for a in all_actions(page.tile_menu(sid)) if a.text() == text)
    action("В избранное").trigger(); assert services.catalog.card(sid).favorite
    action("Новая полка…").trigger()
    shelf = services.catalog.shelves()[0]; assert services.catalog.card(sid).shelf_ids == {shelf.id}
    page.nav.select(Section(SectionKind.SHELF, shelf.id))
    action(f"Убрать с полки «{shelf.name}»").trigger(); assert titles(page) == []

def test_read_marks_and_remove_from_menu(page, services, tmp_path):
    sid = page.visible_cards()[0].id
    menu = lambda: [a.text() for a in all_actions(page.tile_menu(sid))]
    assert "Отметить прочитанным" in menu() and "Отметить непрочитанным" not in menu()
    assert "Убрать из библиотеки" not in menu()                       # scanned series leave with their folder only
    next(a for a in all_actions(page.tile_menu(sid)) if a.text() == "Отметить прочитанным").trigger()
    assert services.catalog.card(sid).status is Status.FINISHED and "Отметить непрочитанным" in menu()

def test_unavailable_tile_click_shows_message(page, qtbot):
    shutil.rmtree(next(c.path for c in page.visible_cards() if c.title == "Berserk")); page.reload()
    row = next(r for r in range(1, page.model.rowCount()) if not page.model.card_at(r).available)
    page.grid.clicked.emit(page.model.index(row))
    assert Toast.last_text() == "Серия недоступна: папка или файл не найдены"

def test_tile_click_opens_series(page, qtbot):
    with qtbot.waitSignal(page.open_series) as b: page.grid.clicked.emit(page.model.index(1))
    assert b.args == [page.model.card_at(1).id]
    assert [a.text() for a in page.open_menu().actions()] == ["Файл…", "Папку…"]

def test_delete_current_shelf_returns_to_all(page, services, monkeypatch):
    shelf = services.catalog.add_shelf("Полка", "book"); page.reload(); page.nav.select(Section(SectionKind.SHELF, shelf))
    monkeypatch.setattr(errors, "confirm", lambda parent, text: text == "Удалить полку «Полка»? Серии останутся в библиотеке")
    page.nav.shelf_delete_requested.emit(shelf)
    assert services.catalog.shelves() == [] and page.nav.section() == Section()

def test_empty_library_hint(qtbot, services):
    p = LibraryPage(services); qtbot.addWidget(p); p.reload()
    assert p.empty_hint.isVisibleTo(p) and p.model.rowCount() == 1
    with qtbot.waitSignal(p.settings_requested): p.empty_hint.findChild(QPushButton).click()
```

  `all_actions(menu)` — помощник в тесте: обходит действия меню и подменю.

- [ ] **Step 2: Запустить** → FAIL. **Step 3: Реализовать.**
  - Раскладка: слева `nav` шириной `NAV_WIDTH`. Справа `content`: страница плиток (индекс 0) и страница настроек (её добавляет `set_settings_page`).
  - Страница плиток сверху вниз:
    1. верхняя панель: поиск с подсказкой «Поиск…»; кнопки-фишки «Все», «Читаю», «Не начато», «Прочитано» (выбирается одна); список сортировки «Недавно открытые», «По названию», «Недавно добавленные» с `Sort` в `itemData`; кнопка «⟳»;
    2. заголовок «ПРОДОЛЖИТЬ ЧТЕНИЕ» и `continue_row`: видны только в разделе «Все», когда есть что продолжать;
    3. заголовок «БИБЛИОТЕКА» и сетка;
    4. `empty_hint`: текст «Добавьте папки с мангой в Настройках — библиотека заполнится сама» и кнопка «Открыть настройки». Виден, когда нет ни папок библиотеки, ни серий.
  - `reload()`:
    1. `cards = catalog.cards()`;
    2. `nav.set_data(cards, catalog.shelves())`;
    3. сетка — `filter_cards` с текущими настройками;
    4. лента — `continue_reading(cards)`.
  - Клик по строке 0 → `open_menu().exec(QCursor.pos())`, пункты шлют `open_file_requested` / `open_folder_requested`. Клик по недоступной серии → `Toast.show_message(self, «Серия недоступна: папка или файл не найдены»)`, по доступной → `open_series`.
  - Пункты `tile_menu`, после каждого `reload()`:

    | Пункт | Когда виден | Что делает |
    |---|---|---|
    | «В избранное» / «Убрать из избранного» | всегда | `set_favorite` |
    | «На полку…» | всегда | подменю: полки с галочками (`add_to_shelf` / `remove_from_shelf`), разделитель, «Новая полка…» (`ask_shelf` → `add_shelf` → `add_to_shelf`) |
    | «Убрать с полки «имя»» | открыт раздел этой полки | `remove_from_shelf` |
    | «Отметить прочитанным» | статус не «Прочитано» | `mark_read` |
    | «Отметить непрочитанным» | статус не «Не начато» | `mark_unread` |
    | «Показать в проводнике» | всегда | `open_in_explorer` |
    | «Убрать из библиотеки» | `root_id is None` | `remove_series` |

  - Полки из навигации:
    - добавить → `ask_shelf(title="Новая полка")` → `add_shelf`;
    - переименовать или сменить иконку → `ask_shelf` с текущими значениями и `shelf_id` → `rename_shelf` + `set_shelf_icon`;
    - удалить → `errors.confirm(«Удалить полку «имя»? Серии останутся в библиотеке»)` → `delete_shelf`;
    - перетаскивание → `add_to_shelf` и сообщение «Добавлено на полку «имя»».
  - Клик по разделу навигации всегда возвращает к плиткам. `settings_requested` навигации и кнопки подсказки пробрасываются наверх.
  - `set_scanning(True)`: кнопка «⟳» недоступна, подсказка «Идёт обновление…»; `set_scanning(False)` возвращает как было.

- [ ] **Step 4: Прогнать** → PASS. **Step 5: Commit** `feat: library screen with continue-reading row and tile menu`.

---

### Task 10: Страница настроек

**Files:**
- Create: `src/mangareader/ui/settings_page.py`
- Delete: `src/mangareader/ui/dialogs/settings_dialog.py`
- Test: `tests/test_settings_page.py`

**Interfaces:**
- Consumes: `Services`, `Catalog.roots/add_root/remove_root/relocate_root`, `CatalogError`, `apply_theme`, `save_settings`, `errors.confirm`, `Toast`
- Produces:
  - Функция модуля `choose_folder(parent, title: str) -> str` (`QFileDialog.getExistingDirectory`; пустая строка, если выбор отменён)
  - `SettingsPage(services)`:
    - сигналы `roots_changed()` и `rescan_requested()`;
    - поля `roots_list`, `add_button`, `remove_button`, `rescan_button`, `relocate_button`, `failed_toggle`, `failed_list`, `theme_combo`, `folder_edit`, `folder_button`, `template_edit`, `cache_spin`;
    - метод `refresh(failed: Sequence[tuple[Path, str]] = ())`.

- [ ] **Step 1: Падающие тесты**

```python
def test_add_remove_root(settings_page, services, tmp_path, monkeypatch, qtbot):
    lib = tmp_path / "Манга"; lib.mkdir()
    monkeypatch.setattr(settings_page_module, "choose_folder", lambda *a: str(lib))
    with qtbot.waitSignal(settings_page.roots_changed): settings_page.add_button.click()
    assert [r.path for r in services.catalog.roots()] == [lib] and settings_page.roots_list.item(0).text() == str(lib)
    monkeypatch.setattr(settings_page_module, "choose_folder", lambda *a: str(lib / "sub"))
    (lib / "sub").mkdir(); settings_page.add_button.click()
    assert Toast.last_text().startswith("Эта папка уже внутри папки библиотеки")
    monkeypatch.setattr(errors, "confirm", lambda *a: True); settings_page.roots_list.setCurrentRow(0)
    with qtbot.waitSignal(settings_page.roots_changed): settings_page.remove_button.click()
    assert services.catalog.roots() == []

def test_missing_root_marked_and_relocated(settings_page, services, tmp_path, monkeypatch):
    old = tmp_path / "old"; old.mkdir(); services.catalog.add_root(old); old.rename(tmp_path / "new"); settings_page.refresh()
    assert settings_page.roots_list.item(0).text().endswith("— не найдена")
    settings_page.roots_list.setCurrentRow(0); assert settings_page.relocate_button.isEnabled()
    monkeypatch.setattr(settings_page_module, "choose_folder", lambda *a: str(tmp_path / "new"))
    settings_page.relocate_button.click()
    assert services.catalog.roots()[0].path == tmp_path / "new" and "не найдена" not in settings_page.roots_list.item(0).text()

def test_failed_list(settings_page, tmp_path):
    settings_page.refresh([(tmp_path / "a.cbz", "Архив повреждён или не поддерживается")])
    assert settings_page.failed_toggle.text() == "Не удалось открыть (1)" and settings_page.failed_list.count() == 1
    settings_page.refresh([]); assert settings_page.failed_toggle.isHidden()

def test_preferences_apply_and_save_immediately(settings_page, services):
    settings_page.theme_combo.setCurrentIndex(settings_page.theme_combo.findData("light"))
    settings_page.cache_spin.setValue(2048)
    settings_page.template_edit.setText("{серия} {страница}"); settings_page.template_edit.editingFinished.emit()
    saved = load_settings(services.data.settings_file)
    assert (saved.theme, saved.cache_mb, saved.export.template) == ("light", 2048, "{серия} {страница}")
    assert services.cache.budget == 2048 * 2**20
```

  В `ImageCache` (`render/cache.py`) добавить свойство `budget` (чтение `_budget`).

- [ ] **Step 2: Запустить** → FAIL. **Step 3: Реализовать.**
  - Разделы страницы:
    1. «Папки библиотеки»: строка списка — путь, а у недоступной папки приписка « — не найдена». Кнопки «＋ Добавить папку…», «Убрать», «⟳ Обновить сейчас», «Указать новое место…» (активна только для недоступной папки). Ниже раскрываемый «Не удалось открыть (N)» со строками «имя — причина».
    2. «Внешний вид»: тема «Тёмная» / «Светлая».
    3. «Сохранение»: папка по умолчанию (`folder_edit` только для чтения и кнопка «Выбрать…») и шаблон имени. Подсказка: «Подстановки: {серия} {том} {глава} {страница} {файл}».
    4. «Память»: 256–8192, шаг 256, « МБ».
  - Добавление: `CatalogError` → `Toast` с её текстом.
  - Удаление: `errors.confirm(«Убрать папку «имя» из библиотеки? Прогресс чтения сохранится»)`.
  - После добавления, удаления и переноса папки → `roots_changed`. Кнопка «⟳ Обновить сейчас» → `rescan_requested`.
  - Каждое изменение сразу пишется в `Settings` и сохраняется `save_settings`. Тема применяется через `apply_theme`, память — через `services.cache.set_budget`.

- [ ] **Step 4: Прогнать** `pytest -q` → PASS. Окно настроек ещё вызывается из главного окна, поэтому `settings_dialog.py` удалить в задаче 13 вместе с его вызовом. **Step 5: Commit** `feat: settings page`.

---

### Task 11: Раскрывающийся список в читалке

**Files:**
- Create: `src/mangareader/ui/reader/nav_panel.py`
- Delete: `src/mangareader/ui/reader/sidebar.py`, `tests/test_sidebar.py`
- Modify: `src/mangareader/ui/main_window.py` (`Sidebar` → `NavPanel`, поле `nav_panel`), `tests/test_books.py`, `tests/test_main_window.py`
- Test: `tests/test_nav_panel.py`

**Interfaces:**
- Consumes: `SeriesTree`, `TreeNode`, `SourceEntry`, `ChapterMark`, `Position`, `PageLoader.thumbnail/thumb_ready`, `CoverLoader`, `Store.progress`, `style.*`
- Produces:
  - `RowKind` (StrEnum): `VOLUME`, `CHAPTER`, `THUMBS`; роли `KIND_ROLE`, `POSITION_ROLE`, `OVERRIDE_ROLE`, `PAGES_ROLE`, `SOURCE_ROLE`, `PROGRESS_ROLE` (подряд от `Qt.UserRole`); `THUMBS_PER_ROW = 3`
  - `NavPanel(loader: PageLoader, covers: CoverLoader, store: Store, parent=None)`:
    - сигналы как у `Sidebar`: `position_selected(int, int)`, `mark_requested(int)`, `mark_edit_requested(int)`, `mark_delete_requested(int)`, `kind_override_requested(int, str)`;
    - поле `tree: QTreeWidget`, свойство `page_count`;
    - методы `set_tree(tree)`, `set_source(key, entry_index, page_count, marks, markable)`, `set_marks(marks)`, `set_current(pos)`;
    - для тестов: `item(*titles) -> QTreeWidgetItem` (путь по названиям), `thumb_rect(page) -> QRect | None` (в координатах `tree.viewport()`), `thumb_label(page) -> str`, `page_menu(page) -> QMenu | None`, `row_menu(item) -> QMenu | None`.

- [ ] **Step 1: Падающие тесты** (переносят все проверки из `test_sidebar.py` и добавляют новые).

```python
def volume_with_marks(window, tmp_path, monkeypatch, pages=9):
    s = tmp_path / "S"; make_zip(s / "Vol 01.cbz", {f"{i:03}.png": encode(page_image(i), "PNG") for i in range(pages)})
    answers = iter([("1", ""), ("2", "")]); monkeypatch.setattr(chapter_mark_dialog, "ask_chapter_mark", lambda *a, **k: next(answers))
    window.open_paths([s / "Vol 01.cbz"]); window.nav_panel.mark_requested.emit(3); window.nav_panel.mark_requested.emit(6)
    return s

def test_rows_for_volumes_and_chapters(window, qtbot, tmp_path):
    s = tmp_path / "S"; make_zip(s / "Vol 01.cbz", {"1.png": encode(page_image(1), "PNG")}); make_zip(s / "c010.cbz", {"1.png": encode(page_image(1), "PNG")})
    window.open_paths([s / "Vol 01.cbz"])
    qtbot.waitUntil(lambda: window.nav_panel.tree.topLevelItemCount() == 2, timeout=5000)
    tree = window.nav_panel.tree
    assert [(tree.topLevelItem(i).text(0), tree.topLevelItem(i).data(0, KIND_ROLE)) for i in range(2)] == [("Том 1", RowKind.VOLUME), ("Глава 10", RowKind.CHAPTER)]

def test_one_chapter_open_at_a_time(window, qtbot, tmp_path, monkeypatch):
    volume_with_marks(window, tmp_path, monkeypatch); panel = window.nav_panel
    start, ch1, ch2 = (panel.item("Том 1", t) for t in ("Начало", "Глава 1", "Глава 2"))
    window.controller.go_to(Position(0, 7))
    assert ch2.isExpanded() and not start.isExpanded() and panel.item("Том 1").isExpanded()
    ch1.setExpanded(True); assert ch1.isExpanded() and not ch2.isExpanded()
    assert [ch1.child(i).data(0, PAGES_ROLE) for i in range(ch1.childCount())] == [[3, 4, 5]]

def test_click_thumbnail_and_chapter(window, qtbot, tmp_path, monkeypatch):
    volume_with_marks(window, tmp_path, monkeypatch); panel = window.nav_panel
    panel.item("Том 1", "Глава 1").setExpanded(True); qtbot.wait(50)
    qtbot.mouseClick(panel.tree.viewport(), Qt.LeftButton, pos=panel.thumb_rect(4).center())
    assert window.controller.position == Position(0, 4)
    panel.tree.itemClicked.emit(panel.item("Том 1", "Глава 2"), 0); assert window.controller.position == Position(0, 6)

def test_other_volume_has_no_thumbnails(window, qtbot, tmp_path):
    s = tmp_path / "S"
    for v in (1, 2): make_zip(s / f"Vol {v:02}.cbz", {f"c{c}/{i}.png": encode(page_image(i), "PNG") for c in (1, 2) for i in range(2)})
    window.open_paths([s / "Vol 01.cbz"]); qtbot.waitUntil(lambda: window.nav_panel.tree.topLevelItemCount() == 2, timeout=5000)
    other = window.nav_panel.item("Том 2", "Глава 2")
    assert other.childIndicatorPolicy() == QTreeWidgetItem.DontShowIndicator
    window.nav_panel.tree.itemClicked.emit(other, 0)
    assert window.controller.entry.path.name == "Vol 02.cbz" and window.controller.position.page == 2

def test_marks_badge_delete_and_restart(make_window, qtbot, tmp_path, monkeypatch):
    w = make_window(qtbot); s = volume_with_marks(w, tmp_path, monkeypatch)
    assert w.nav_panel.thumb_label(3) == "4 · Гл 1" and w.nav_panel.thumb_label(2) == "3"
    assert w.breadcrumb_text() == "S › Том 1 › Начало"
    w.nav_panel.mark_delete_requested.emit(6); vol = w.nav_panel.item("Том 1")
    assert [vol.child(i).text(0) for i in range(vol.childCount())] == ["Начало", "Глава 1"]
    w.close(); w2 = make_window(qtbot); w2.open_paths([s / "Vol 01.cbz"])
    qtbot.waitUntil(lambda: w2.nav_panel.item("Том 1").childCount() == 2, timeout=5000)
    menu = w2.nav_panel.page_menu(3); assert [a.text() for a in menu.actions()] == ["Изменить отметку…", "Удалить отметку"]

def test_kind_override_and_volume_progress(window, qtbot, tmp_path):
    s = tmp_path / "S"; make_zip(s / "Vol 01.cbz", {f"{i}.png": encode(page_image(i), "PNG") for i in range(4)}); make_zip(s / "c002.cbz", {"1.png": encode(page_image(1), "PNG")})
    window.open_paths([s / "Vol 01.cbz"]); qtbot.waitUntil(lambda: window.nav_panel.tree.topLevelItemCount() == 2, timeout=5000)
    window.controller.next(); window.nav_panel.set_tree(window.controller.display_tree())
    assert window.nav_panel.item("Том 1").data(0, PROGRESS_ROLE) > 0
    assert [a.text() for a in window.nav_panel.row_menu(window.nav_panel.item("Том 1")).actions()] == ["Это том", "Это глава", "Сбросить"]
    window.nav_panel.kind_override_requested.emit(0, "chapter")
    qtbot.waitUntil(lambda: window.nav_panel.tree.topLevelItem(0).text(0) == "Глава 1", timeout=5000)

def test_tab_toggles_panel(window, qtbot, tmp_path):
    s = tmp_path / "S"; make_zip(s / "Vol 01.cbz", {"1.png": encode(page_image(1), "PNG")}); window.open_paths([s / "Vol 01.cbz"])
    visible = window.nav_panel.isVisible(); qtbot.keyClick(window.view, Qt.Key_Tab)
    assert window.nav_panel.isVisible() != visible
```

  `tests/test_books.py`: `window.sidebar.thumb_view.model().rowCount()` заменить на `window.nav_panel.page_count`. `tests/test_main_window.py`: `window.sidebar` заменить на `window.nav_panel`.

- [ ] **Step 2: Запустить** → FAIL. **Step 3: Реализовать.**
  - Строки по узлам дерева, номер записи `index` идёт по порядку чтения:

    | Узел | Строка верхнего уровня | Строки внутри |
    |---|---|---|
    | Папка тома (`node.folder`) | `VOLUME`, обложка и прогресс по записям папки | по строке `CHAPTER` на запись: `Position(index, 0)` |
    | Том-файл | `VOLUME`, `Position(index, 0)` | по строке `CHAPTER` на главу `entry.chapters`: `Position(index, span.start_page)` |
    | Глава-файл или книга | `CHAPTER`, `Position(index, 0)` | — |

  - «Контейнер страниц» — строка, внутри которой миниатюры: глава открытой записи, том открытой записи без глав, глава-файл или книга открытой записи. У строк других записей стрелки нет (`DontShowIndicator`).
  - Миниатюры: строки `THUMBS` по `THUMBS_PER_ROW` страниц (`PAGES_ROLE`). Создаются при первом раскрытии контейнера.
  - Аккордеон: раскрыли контейнер — остальные контейнеры свернулись. При открытии записи и при смене контейнера в `set_current` раскрыть текущий том и текущий контейнер и прокрутить к текущей странице. Пока контейнер не сменился, раскрытие не трогать.
  - Отрисовка:
    - строка тома: обложка `covers.cover(source_id)` размером `VOLUME_COVER`, название, полоска прогресса (`PROGRESS_ROLE`: доля из `store.progress(...)`, взвешенная по страницам записей);
    - строка миниатюр: до трёх `loader.thumbnail(key, page)` размером `NAV_THUMB`, под ними `thumb_label`; текущая страница обведена `accent_color()`.

    Миниатюры запрашиваются только при отрисовке, то есть только видимые. `loader.thumb_ready` и `covers.cover_ready` обновляют `tree.viewport()`.
  - Клик:
    - по строке миниатюр: страница по колонке `(x - left) // ширина ячейки` → `position_selected`;
    - по другой строке: её `POSITION_ROLE`.
  - Правый клик:
    - по миниатюре — `page_menu` (только если `markable`): «Здесь начинается глава…» или «Изменить отметку…» и «Удалить отметку»;
    - по строке верхнего уровня с одной записью без папки — `row_menu`: «Это том», «Это глава», «Сбросить».
  - `thumb_label`: «N · Гл M» при отметке, иначе «N».

- [ ] **Step 4: Прогнать** `pytest -q` → PASS. **Step 5: Commit** `feat: accordion volume and chapter panel in the reader`.

---

### Task 12: Читалка знает серию; фоновое сканирование библиотеки

**Files:**
- Modify: `src/mangareader/ui/reader/controller.py`
- Create: `src/mangareader/ui/library/scan_runner.py`
- Test: `tests/test_library_flow.py` (первая часть)

**Interfaces:**
- Consumes: `scan_library`, `ScanReport`, `Services`
- Produces:
  - `ReaderController.open_path(path, password=None, series: Path | None = None) -> bool`: при `series` деревом серии считается `series`, а не путь из `find_series_root`
  - `ReaderController.tree_scanned = Signal(object)`: в начале `_set_tree`
  - `ReaderController.where_parts() -> list[str]`: `breadcrumb()[1:] + [f"стр. {page + 1}"]`, а если серия — сам открытый файл или папка картинок, то `[]`
  - `_save_progress` передаёт `fraction`: `1.0` в последней группе, иначе `(page + 1) / len(pages)`
  - `ScanRunner(services)` (`QObject`):
    - сигналы `started()`, `series_updated()`, `finished()`;
    - методы `start()` (если скан уже идёт, после него пройти ещё раз) и `stop()`;
    - свойства `running -> bool` и `failed -> list[tuple[Path, str]]` (последнего отчёта).

- [ ] **Step 1: Падающие тесты**

```python
def test_single_file_series_and_where(window, qtbot, tmp_path):
    dl = tmp_path / "Загрузки"; book = make_epub(dl / "b.epub", 40); make_epub(dl / "other.epub", 40)
    c = window.controller; assert c.open_path(book, series=book)
    qtbot.wait(300); assert [e.path for e in c.entries] == [book] and c.where_parts() == []
    s = tmp_path / "S"; make_zip(s / "Vol 01.cbz", {f"{i}.png": encode(page_image(i), "PNG") for i in range(4)})
    assert c.open_path(s / "Vol 01.cbz", series=s); c.next()
    assert c.where_parts() == ["Том 1", "стр. 2"]
    assert window.services.store.progress(c.record.id).fraction == 0.5

def test_tree_scanned_signal(window, qtbot, tmp_path):
    s = tmp_path / "S"; make_zip(s / "c1.cbz", {"1.png": encode(page_image(1), "PNG")}); make_zip(s / "c2.cbz", {"1.png": encode(page_image(1), "PNG")})
    with qtbot.waitSignal(window.controller.tree_scanned, timeout=5000) as b: window.controller.open_path(s / "c1.cbz", series=s)
    assert b.args[0].root == s

def test_scan_runner(qtbot, services, tmp_path):
    services.catalog.add_root(library(tmp_path)); runner = ScanRunner(services)
    with qtbot.waitSignal(runner.finished, timeout=20000): runner.start(); runner.start()   # second start queues a rerun
    qtbot.waitUntil(lambda: not runner.running, timeout=20000)
    assert len(services.catalog.cards()) == 3 and runner.failed == []
```

- [ ] **Step 2: Запустить** → FAIL. **Step 3: Реализовать.**
  - `open_path`:
    - корень серии `root = series or <прежнее правило>`;
    - папка без картинок → прежняя ветка с `scan_series(root)`, записи внутри `path`;
    - всё остальное → `_open_source(path, password, root)` и `_start_scan(root)`.

    `scan_series` с корнем-файлом работает после задачи 4.
  - `ScanRunner`: фоновая задача в `QThreadPool`. Внутри `scan_library(services.catalog, services.store, services.ctx, on_series=…, cancelled=…)`. `on_series` шлёт `series_updated` через сигнал-мост. Исключение пишется в журнал, `finished` приходит всегда.

- [ ] **Step 4: Прогнать** `pytest -q` → PASS. **Step 5: Commit** `feat: reader tracks its series; background library scan`.

---

### Task 13: Главное окно: библиотека, читалка, настройки

**Files:**
- Modify: `src/mangareader/ui/main_window.py`, `src/mangareader/app.py`, `tests/test_main_window.py`, `tests/test_books.py`, `tests/conftest.py`
- Delete: `src/mangareader/ui/dialogs/settings_dialog.py`
- Test: `tests/test_library_flow.py` (вторая часть)

**Interfaces:**
- Consumes: `LibraryPage`, `SettingsPage`, `ScanRunner`, `series_path_for`, `record_tree`, `Catalog.ensure_series/touch/card/roots`, `where_parts`, `tree_scanned`
- Produces (в `MainWindow`):
  - поля `pages: QStackedWidget`, `library_page`, `reader_page`, `settings_page`, `scanner`, `toolbar` (панель читалки внутри `reader_page`), `home_button`
  - методы `is_library_shown() -> bool`, `go_home()`, `show_settings()`, `open_series(series_id) -> bool`, `open_paths(paths) -> bool` (прежняя сигнатура)

- [ ] **Step 1: Падающие тесты**

```python
def scanned_window(window, qtbot, tmp_path):
    window.services.catalog.add_root(library(tmp_path))
    with qtbot.waitSignal(window.scanner.finished, timeout=20000): window.scanner.start()
    return window

def tile_row(window, title):
    m = window.library_page.model
    return next(r for r in range(1, m.rowCount()) if m.card_at(r).title == title)

def test_starts_on_library(window):
    assert window.is_library_shown() and window.library_page.model.data(window.library_page.model.index(0)) == "Открыть"

def test_tile_opens_reader_and_home_returns(window, qtbot, tmp_path):
    w = scanned_window(window, qtbot, tmp_path)
    w.library_page.grid.clicked.emit(w.library_page.model.index(tile_row(w, "Berserk")))
    assert not w.is_library_shown() and w.controller.entry.path.name == "Vol 01.cbz"
    w.controller.next(); qtbot.keyClick(w.view, Qt.Key_Backspace)
    assert w.is_library_shown() and w.controller.source is None
    card = next(c for c in w.services.catalog.cards() if c.title == "Berserk")
    assert card.status is Status.READING and card.where == ("Том 1", "стр. 2")
    assert [k.series_id for k in w.library_page.continue_row.cards()] == [card.id]

def test_continue_card_opens_exact_place(window, qtbot, tmp_path):
    w = scanned_window(window, qtbot, tmp_path)
    w.library_page.grid.clicked.emit(w.library_page.model.index(tile_row(w, "Berserk")))
    w.controller.go_to(Position(1, 2)); w.home_button.click()
    qtbot.mouseClick(w.library_page.continue_row.cards()[0], Qt.LeftButton)
    assert w.controller.entry.path.name == "Vol 02.cbz" and w.controller.position.page == 2

def test_open_adds_series_without_duplicates(window, qtbot, tmp_path):
    w = scanned_window(window, qtbot, tmp_path); lib = w.services.catalog.roots()[0].path
    assert w.open_paths([lib / "Berserk" / "Vol 02.cbz"]); assert len(w.services.catalog.cards()) == 3
    dl = tmp_path / "Загрузки"; book = make_epub(dl / "Книга.epub", 30); make_zip(dl / "x.cbz", {"1.png": encode(page_image(1), "PNG")})
    assert w.open_paths([book])
    new = next(c for c in w.services.catalog.cards() if c.path == book)
    assert new.root_id is None and new.title == "Книга"

def test_open_library_root_itself_is_refused(window, qtbot, tmp_path):
    w = scanned_window(window, qtbot, tmp_path)
    assert not w.open_paths([w.services.catalog.roots()[0].path]) and w.is_library_shown()
    assert Toast.last_text() == "Это папка библиотеки — её серии уже на главной"

def test_reader_keys_do_not_fire_on_library(window, qtbot, tmp_path):
    w = scanned_window(window, qtbot, tmp_path); grid = w.library_page.grid
    grid.setFocus(); grid.setCurrentIndex(w.library_page.model.index(0))
    qtbot.keyClick(grid, Qt.Key_Right); assert grid.currentIndex().row() == 1
    qtbot.keyClick(grid, Qt.Key_2); assert w.controller.mode is Mode.SINGLE and w.is_library_shown()

def test_reader_toolbar_has_home_and_no_settings(window, cbz_1000x1500):
    window.open_paths([cbz_1000x1500])
    texts = [b.text() for b in window.toolbar.findChildren(QToolButton)]
    assert "⌂ Главная" in texts and "⚙" not in texts

def test_settings_from_menu_and_back(window, qtbot, cbz_1000x1500):
    window.open_paths([cbz_1000x1500]); window.show_settings()
    assert window.is_library_shown() and window.library_page.content.currentWidget() is window.settings_page
    window.library_page.nav.tree.itemClicked.emit(window.library_page.nav.item_for(Section()), 0)
    assert window.library_page.content.currentIndex() == 0
```

- [ ] **Step 2: Запустить** → FAIL. **Step 3: Реализовать.**
  - Центр окна — `pages` (`library_page`, `reader_page`). Внутри `reader_page` сверху вниз: панель `toolbar` (`QToolBar` в раскладке страницы), `splitter` (`nav_panel` | `view`), нижняя полоса. Первая кнопка панели — «⌂ Главная» (`home_button`, подсказка «Главная (Backspace)»). Кнопки ⚙ нет. `SettingsPage` вставляется через `library_page.set_settings_page`.
  - Горячие клавиши читалки (листание, режимы, масштаб, ножницы, сохранение, Tab, Backspace, Esc, Enter) добавляются в `reader_page` с `Qt.WidgetWithChildrenShortcut`. Ctrl+O, Ctrl+Shift+O, F11 и «Выход» остаются в окне. «Вид → Настройки…» вызывает `show_settings()`.
  - `open_paths(paths)`:
    1. Путь совпадает с папкой библиотеки → сообщение «Это папка библиотеки — её серии уже на главной» и `False`.
    2. Иначе `series, root_id = series_path_for(path, catalog.roots())` и `controller.open_path(path, series=series)`.
    3. При успехе: `self._series_id = catalog.ensure_series(series, root_id)`, `record_tree` по `controller.tree` (если дерево уже есть), `_touch()`, показать читалку, сохранить настройки.
  - `open_series(id)`: карточка недоступна → сообщение «Серия недоступна: папка или файл не найдены». Иначе `controller.open_path(card.path, series=card.path)`, дальше как в `open_paths` с готовым id. Тот же метод открывает серию по клику на плитку и на карточку ленты.
  - `_touch()` по `controller.state_changed`, если известны серия и `controller.record`: `catalog.touch(id, record.id, controller.where_parts())`. По `tree_scanned`: `record_tree`, если `tree.root` совпадает с путём серии.
  - `go_home()`:
    1. снять выделение ножниц;
    2. `controller.close_source()`;
    3. показать библиотеку и плитки, `library_page.reload()`;
    4. заголовок окна `APP_TITLE`, фокус на сетку.
  - `show_settings()`: если открыта читалка, сначала `go_home()`, потом `library_page.show_settings()` и `settings_page.refresh(scanner.failed)`.
  - Сканер:
    - `started` → `set_scanning(True)`;
    - `series_updated` → `reload()` с задержкой 300 мс;
    - `finished` → `set_scanning(False)`, `reload()`, `settings_page.refresh(scanner.failed)`;
    - `settings_page.roots_changed` → `reload()` и `scanner.start()`, `rescan_requested` и «⟳» → `scanner.start()`.

    При запуске окна, если папки библиотеки есть, `scanner.start()` вызывается через `QTimer.singleShot(0, …)`. `closeEvent` сначала вызывает `scanner.stop()`.
  - Удалить `ui/dialogs/settings_dialog.py` и `_open_settings`.

- [ ] **Step 4: Прогнать** `pytest -q` → PASS (весь набор, включая перенесённые тесты этапа 1). **Step 5: Commit** `feat: start on the library; home button; settings page in the window`.

---

### Task 14: Самопроверка, README, скриншоты, CI

**Files:**
- Modify: `src/mangareader/selftest.py`, `README.md`
- Test: `tests/test_selftest.py`

- [ ] **Step 1: Тест.** В `test_selftest.py` проверить, что отчёт содержит строку `OK window`. Сам шаг `window` дополняется проверками:
  - окно стартует на библиотеке (`is_library_shown()`);
  - `icons.icon_pixmap("book", 24, "#ffffff")` не пустая;
  - открытие `cbz` переводит окно в читалку.

- [ ] **Step 2: Реализовать и прогнать** `pytest -q` → PASS, затем `python -m mangareader --self-test` локально → все шаги `OK`.

- [ ] **Step 3: README.**
  - Новый раздел «Библиотека» (3–5 предложений): папки библиотеки в Настройках, плитка «Открыть», полки и избранное, лента «Продолжить чтение».
  - В таблицу клавиш добавить «Backspace — вернуться в библиотеку», у Tab уточнить «панель томов и глав».
  - Упоминание окна настроек заменить на страницу настроек.

- [ ] **Step 4: Скриншоты.** Сценарий в папке для временных файлов (не в репозитории) собирает пример библиотеки (несколько серий, полки, прогресс) и снимает `window.grab()` в тёмной теме: библиотеку, раздел полки, меню плитки, окно новой полки, читалку с раскрытой главой и страницу настроек. Показать пользователю.

- [ ] **Step 5: Commit** `docs: library in README; self-test checks the library screen`, `git push origin main`. Дождаться зелёного CI: тесты на Ubuntu и Windows и `build-windows` с самопроверкой собранного exe.
