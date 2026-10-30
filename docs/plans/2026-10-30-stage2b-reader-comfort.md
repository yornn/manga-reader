# Этап 2.1 «Удобное чтение»: план реализации

**Goal:** Чтение манги без лишнего. Колесо мыши только плавно прокручивает. Появляются горизонтальная лента, яркость, шестерёнка с настройками чтения и памяткой клавиш, кнопки глав, переход к странице по номеру и режим «только страница». Меню «Файл / Вид / Правка» убирается, цвета колонок меняются местами. Заодно доделываются пять мелочей этапа 2.

**Architecture:** Логика раскладки (`ui/reader/layout.py`) и контроллер читалки получают четвёртый режим. `PageView` получает плавную прокрутку и затемнение. Шестерёнка — отдельный виджет `ui/reader/reader_settings.py` во всплывающем меню. Памятка клавиш (`ui/dialogs/hotkeys_dialog.py`) — единый список, по которому тест сверяет настоящие горячие клавиши окна.

**Tech Stack:** как на этапе 2.

**Spec:** `docs/specs/2026-10-30-library-and-navigation-design.md` (этап 2) и решения ниже, согласованные в разговоре 30.10.2026.

## Решения

1. **Колесо мыши** только плавно прокручивает и никогда не листает. Если страница целиком в окне, колесо ничего не делает. Ctrl+колесо — масштаб. Пробел работает как раньше: прокрутка, а в конце страницы переход дальше. Листают стрелки, PgUp/PgDn и клик по левой или правой трети страницы.
2. **Горизонтальная лента:** все страницы файла в один ряд. Колесо и стрелки плавно ведут её вбок, при чтении справа налево первая страница стоит справа. Клавиша 4.
3. **Яркость:** одна на всю программу, ползунок 20–100 %. Затемняется только картинка на экране, сохранённые страницы и фрагменты остаются оригинальными.
4. **Шестерёнка в читалке** открывает панель:
   - режим (одна страница, разворот, вертикальная лента, горизонтальная лента);
   - сдвиг разворота;
   - направление (справа налево, слева направо);
   - масштаб (по ширине, по высоте, целиком, 100 %);
   - яркость;
   - размер шрифта (только для книг);
   - кнопка «Горячие клавиши…» с памяткой.

   Кнопки «Режим», «Масштаб», направление и нижний ползунок шрифта с панели убираются.
5. **Кнопка «◧»** рядом с «⌂ Главная» включает режим «только страница». Прячутся левая панель, верхняя полоса и нижний ползунок. Полоса всплывает поверх страницы, если подвести мышь к верхнему краю. Выключается той же кнопкой или Esc.
6. **Цвета.** Левая колонка светлее (палитра `Window`), всё остальное — одним тёмным фоном (`Base`), без отдельной рамки вокруг плиток. В читалке так же: панель томов светлее, страница на тёмном. В светлой теме по тому же правилу.
7. **Переход к странице:** клик по счётчику страниц или Ctrl+G открывает окно ввода. Номер сквозной по всей серии: при 10 томах по 100 страниц можно ввести от 1 до 1000. Число больше последнего ведёт на последнюю страницу, меньше 1 — на первую.
8. **Меню «Файл / Вид / Правка» убирается**, горячие клавиши остаются, а памятка в шестерёнке объясняет каждую. Кнопки «‹ Глава» и «Глава ›» появляются на верхней полосе читалки. Список «Недавние» убирается: его заменяет «Продолжить чтение».
9. **Мелочи этапа 2:**
   - перенос папки библиотеки в другую папку библиотеки или над ней запрещён;
   - Enter открывает выбранную плитку;
   - иконки полок перекрашиваются при смене темы;
   - серии из старого списка «Недавние» один раз добавляются в библиотеку;
   - пока открыты настройки, в навигации подсвечена кнопка «⚙ Настройки», а не «Все».
10. **Ширина окна:** главный экран тоже должен сужаться (на Windows его минимум был 904 px). Верхняя панель библиотеки при нехватке места прокручивается вбок.

## Global Constraints

- Действуют ограничения этапов 1 и 2: интерфейс по-русски, `self.tr(...)`, без `QSettings`, `library/*` без Qt, диалоги через атрибут модуля (`page_dialog.ask_page`, `hotkeys_dialog.show_hotkeys`).
- Коммиты от имени `yornn`: одна строка на английском (`feat: …`, `fix: …`) без дополнительных подписей. Работа в `main`, пуш после каждой задачи. Выпуск не делать.
- Размеры и цвета новых элементов — в `ui/style.py`.

## Review Focus

1. **Прокрутка у края.** Колесо в конце страницы в режиме одной страницы не листает. Тест в задаче 2.
2. **Горизонтальная лента и направление.** При смене «справа налево» на «слева направо» текущая страница остаётся на экране. Тест в задаче 3.
3. **Сквозной номер страницы с непрочитанными томами:** число страниц неоткрытых томов берётся из базы, а 0 у запертого архива номер не сбивает. Тест в задаче 5.
4. **Памятка и клавиши не расходятся:** каждая клавиша из памятки есть у действия окна, и наоборот. Тест в задаче 4.
5. **Режим «только страница» и книги:** всплывающая полоса не меняет размер страницы, поэтому книга не перераскладывается. Тест в задаче 6.

---

### Task 1: Мелочи библиотеки: перенос папки и импорт «Недавних»

**Files:** `library/catalog.py`, `library/library_scan.py`, `settings.py`; тесты `tests/test_catalog.py`, `tests/test_library_scan.py`

**Interfaces:**
- `Catalog.relocate_root` бросает те же `CatalogError`, что и `add_root`, если новое место внутри другой папки библиотеки или над ней. Проверка вынесена в `Catalog._check_nesting(path, except_id)`.
- `library_scan.import_recent(catalog, paths: Sequence[str]) -> int`: для каждого существующего пути `ensure_series(*series_path_for(path, roots))`; папки библиотеки пропускаются. Возвращает число добавленных серий.
- `Settings.recent_imported: bool = False`.

- [ ] Тесты:
  - `test_relocate_rejects_nesting`: `relocate_root(a, b / "sub")` → `CatalogError` «уже внутри папки библиотеки»;
  - `test_import_recent_adds_series_once`: два файла из разных папок плюс несуществующий путь → 2 серии с `root_id is None`; повторный вызов → 0 новых.
- [ ] Запустить → FAIL. Реализовать. Запустить `pytest -q` → PASS. Commit `feat: guard folder relocation; import recent files into the library`.

### Task 2: Плавная прокрутка колесом

**Files:** `ui/reader/view.py`, `tests/test_view.py`

**Interfaces:**
- `PageView` больше не шлёт `flip_requested` от колеса, поле `_wheel_acc` убирается.
- `PageView.smooth_scroll(dx: float, dy: float)`: анимация полос прокрутки (`QVariantAnimation`, 160 мс, `OutCubic`); новые шаги добавляются к цели.
- Шаг колеса: `WHEEL_STEP` (120) → `max(80, viewport.height() * 0.2)` пикселей.
- `pixelDelta` тачпада прокручивает сразу, без анимации.
- В горизонтальной ленте вертикальное колесо ведёт по горизонтали: «вниз» = вперёд по направлению чтения.

- [ ] Тесты (`tests/test_view.py` или `tests/test_main_window.py`):
  - `test_wheel_never_flips`: одна страница выше окна, прокрутка до низа, ещё 3 щелчка колеса → страница та же;
  - `test_wheel_scrolls_smoothly`: после щелчка полоса сдвигается, и через 300 мс значение больше начального;
  - `test_ctrl_wheel_still_zooms`.
- [ ] FAIL → реализовать → PASS. Commit `feat: the mouse wheel only scrolls, smoothly`.

### Task 3: Горизонтальная лента

**Files:** `ui/reader/layout.py`, `ui/reader/view.py`, `ui/reader/controller.py`, `ui/main_window.py`; тесты `tests/test_layout_navigation.py`, `tests/test_main_window.py`

**Interfaces:**
- `Mode.HRIBBON = "hribbon"`, `RIBBON_MODES = frozenset({Mode.RIBBON, Mode.HRIBBON})`.
- `layout.place_hribbon(sizes, direction) -> list[Placed]`: все страницы приведены к высоте самой высокой. LTR — слева направо, RTL — первая страница справа.
- `view_groups(Mode.HRIBBON, …)` — одна группа, как у ленты.
- `PageView.show_pages(…, ribbon=True, horizontal=True, …)`.
  - Видимая страница определяется по центру по горизонтали.
  - `scroll_to_page(page, fraction)` ставит передний край страницы (правый при RTL) к переднему краю окна.
  - `ribbon_anchor()` считает так же.
  - Масштаб «по ширине» и «целиком» в ленте берутся по текущей странице, а не по всей ленте.
- В контроллере везде, где было `mode is Mode.RIBBON`, стоит `mode in RIBBON_MODES`. Раскладку даёт `_ribbon_placed()`.
- Клавиша `4` включает горизонтальную ленту.

- [ ] Тесты:
  - `test_place_hribbon_rtl_and_ltr`: при RTL x первой страницы самый большой, высоты равны;
  - `test_hribbon_next_scrolls_and_saves`: `c.set_mode(Mode.HRIBBON)`, `c.next()` → `c.page == 1` и прогресс сохранён;
  - `test_hribbon_direction_keeps_page`: на странице 2 сменить направление → `c.page == 2`, и страница 2 видна (`2 in view.visible_pages()`).
- [ ] FAIL → реализовать → PASS. Commit `feat: horizontal ribbon mode`.

### Task 4: Яркость, шестерёнка, памятка клавиш, без меню

**Files:**
- Create: `ui/reader/reader_settings.py`, `ui/dialogs/hotkeys_dialog.py`
- Modify: `ui/reader/view.py`, `settings.py`, `ui/main_window.py`, `tests/test_books.py`
- Test: `tests/test_reader_settings.py`

**Interfaces:**
- `Settings.brightness: int = 100`. `PageView.set_brightness(percent: int)`: `PageItem.paint` поверх картинки закрашивает чёрным с прозрачностью `(100 - percent) / 100`. Значение зажимается в 20–100.
- `ReaderSettingsPanel(QWidget)`:
  - сигналы `mode_chosen(str)`, `zoom_chosen(str)`, `direction_chosen(str)`, `spread_offset_toggled()`, `brightness_changed(int)`, `font_size_changed(int)`, `hotkeys_requested()`;
  - поля `mode_buttons: dict[Mode, QRadioButton]`, `zoom_buttons`, `direction_buttons`, `offset_check`, `brightness_slider`, `brightness_label`, `font_slider`, `font_row`, `hotkeys_button`;
  - `sync(mode, zoom, direction, spread_offset: bool, brightness: int, font_size: float, is_book: bool)`.
- В главном окне:
  - `gear_button` (⚙) с меню-панелью (`QWidgetAction`), `sync` при открытии;
  - меню окна нет; все действия по-прежнему висят на окне;
  - «Режим», «Масштаб», кнопка направления и нижний `font_box` удалены, поле `font_slider` теперь на панели.
- `hotkeys_dialog.HOTKEYS: list[tuple[str, str, tuple[str, ...]]]` — (клавиши для показа, что делает, `QKeySequence`-строки действий). `show_hotkeys(parent)` — немодальное окно-таблица.

- [ ] Тесты:
  - `test_brightness_dims_only_the_screen`: при 50 % пиксель в центре страницы примерно вдвое темнее, а `render_selection` отдаёт исходные пиксели;
  - `test_gear_panel_controls_reader`: `mode_buttons[Mode.SPREAD].click()` → `c.mode is Mode.SPREAD`; ползунок яркости 60 → `settings.brightness == 60` и сохранено в файл; `font_row` виден только для книги;
  - `test_hotkeys_match_actions`: множество `QKeySequence` из `HOTKEYS` равно множеству сочетаний всех действий окна;
  - `test_no_menu_bar`: `window.menuBar().actions() == []`.

  `test_books.py`: проверки `font_slider.isVisible()` заменить на `reader_settings.font_row.isVisibleTo(reader_settings)`.
- [ ] FAIL → реализовать → PASS. Commit `feat: reader settings behind a gear, brightness, hotkey sheet; no menu bar`.

### Task 5: Кнопки глав и переход к странице

**Files:**
- Create: `ui/dialogs/page_dialog.py`
- Modify: `ui/reader/controller.py`, `ui/main_window.py`
- Test: `tests/test_main_window.py`

**Interfaces:**
- `ReaderController.series_page_count() -> int`: сумма `_page_counts()`.
- `ReaderController.series_page() -> int`: сквозной номер текущей страницы, считая с 1.
- `ReaderController.go_to_series_page(n: int)`: зажимает n в 1…всего и переводит в `Position`.
- `page_dialog.ask_page(parent, current: int, total: int) -> int | None`: поле только для цифр, подсказка «Страница (1–{total})».
- В окне:
  - `page_label` становится кнопкой; клик и `Ctrl+G` → `ask_page` → `go_to_series_page`;
  - кнопки `prev_chapter_button` «‹ Глава» и `next_chapter_button` «Глава ›».

- [ ] Тесты:
  - `test_go_to_series_page`: серия из двух файлов по 3 и 2 страницы; `go_to_series_page(5)` → файл 2, страница 1 (индекс 1); `go_to_series_page(1002)` → последняя страница; `go_to_series_page(0)` → первая;
  - `test_page_button_opens_dialog`: подменить `page_dialog.ask_page` на `lambda *a: 4` → после клика `c.entry_index == 1 and c.page == 0`;
  - `test_chapter_buttons`.
- [ ] FAIL → реализовать → PASS. Commit `feat: chapter buttons and go-to-page by series-wide number`.

### Task 6: Режим «только страница»

**Files:** `ui/main_window.py`; тест `tests/test_main_window.py`

**Interfaces:**
- `MainWindow.focus_button` («◧»), `set_focus_mode(on: bool)`, `focus_mode -> bool`.
- Во включённом режиме прячутся `nav_panel` (видимость запоминается), нижняя полоса и `toolbar`. Панель вынимается из раскладки и показывается поверх страницы, когда мышь у верхнего края окна (< 12 px), и прячется, когда мышь уходит.
- Esc по порядку: снять выделение → выключить режим → выйти из полного экрана.

- [ ] Тесты:
  - `test_focus_mode_hides_chrome_and_keeps_layout`: включить → `not nav_panel.isVisible()`, `not slider.isVisible()`, `not toolbar.isVisible()`; размер `view` не меняется, когда панель всплывает (`view.size()` до и после события мыши у края равны);
  - `test_esc_leaves_focus_mode`.
- [ ] FAIL → реализовать → PASS. Commit `feat: page-only reading mode`.

### Task 7: Цвета колонок, узкое окно, мелочи интерфейса

**Files:** `ui/style.py`, `ui/library/page.py`, `ui/library/nav.py`, `ui/library/tiles.py`, `ui/settings_page.py`, `ui/main_window.py`; тесты `tests/test_library_page.py`, `tests/test_library_flow.py`

**Interfaces:**
- `style.panel_color()` = палитра `Window`, `style.content_color()` = палитра `Base`.
- `style.set_surface(widget, "panel" | "content")`: запоминает вид поверхности в свойстве виджета и задаёт `Window` и `Base` его палитры. `style.refresh_surfaces(root)` перекрашивает все такие виджеты (вызывается после смены темы).
- `SettingsPage.theme_changed` (сигнал). Окно по нему вызывает `refresh_surfaces` и `library_page.reload()`, и иконки полок перекрашиваются.
- Верхняя панель библиотеки лежит в горизонтальной прокрутке без рамки, сетка без рамки.
- `LibraryNav.set_settings_active(on: bool)`: кнопка настроек отмечена, выделение раздела снято.
- `TileGrid.tile_activated(QModelIndex)` по Enter/Return.

- [ ] Тесты:
  - `test_nav_lighter_than_content`: яркость `nav.palette().color(QPalette.Window)` больше, чем у `content` (тёмная тема);
  - `test_window_can_be_narrow` (уже есть; теперь и с порогом 700 на Windows);
  - `test_enter_opens_tile`;
  - `test_settings_highlights_settings_button`: после `show_settings()` у `nav.settings_button.isChecked()` и нет выделенного раздела, а клик по «Все» снимает отметку.
- [ ] FAIL → реализовать → PASS. Commit `feat: lighter navigation column, narrow library, settings highlight, Enter opens a tile`.

### Task 8: README, скриншоты, CI

- [ ] README: таблица клавиш (клавиша 4, Ctrl+G, колесо, Esc), раздел про шестерёнку и режим «только страница».
- [ ] Скриншоты: библиотека (новые цвета), читалка с открытой шестерёнкой, горизонтальная лента, режим «только страница», окно перехода к странице, памятка клавиш.
- [ ] Commit `docs: reader comfort features in README`, push, дождаться зелёного CI вместе с `build-windows`.
