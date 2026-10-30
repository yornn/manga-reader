import pytest

from mangareader.settings import load_settings
from mangareader.ui import settings_page as settings_page_module
from mangareader.ui.dialogs import errors
from mangareader.ui.settings_page import SettingsPage
from mangareader.ui.toast import Toast


@pytest.fixture
def settings_page(qtbot, services):
    page = SettingsPage(services)
    qtbot.addWidget(page)
    page.refresh()
    return page


def test_add_remove_root(settings_page, services, tmp_path, monkeypatch, qtbot):
    lib = tmp_path / "Манга"
    lib.mkdir()
    monkeypatch.setattr(settings_page_module, "choose_folder", lambda *a: str(lib))
    with qtbot.waitSignal(settings_page.roots_changed):
        settings_page.add_button.click()
    assert [r.path for r in services.catalog.roots()] == [lib] and settings_page.roots_list.item(0).text() == str(lib)
    (lib / "sub").mkdir()
    monkeypatch.setattr(settings_page_module, "choose_folder", lambda *a: str(lib / "sub"))
    settings_page.add_button.click()
    assert Toast.last_text().startswith("Эта папка уже внутри папки библиотеки")
    monkeypatch.setattr(errors, "confirm", lambda *a: True)
    settings_page.roots_list.setCurrentRow(0)
    with qtbot.waitSignal(settings_page.roots_changed):
        settings_page.remove_button.click()
    assert services.catalog.roots() == []


def test_missing_root_marked_and_relocated(settings_page, services, tmp_path, monkeypatch):
    old = tmp_path / "old"
    old.mkdir()
    services.catalog.add_root(old)
    old.rename(tmp_path / "new")
    settings_page.refresh()
    assert settings_page.roots_list.item(0).text().endswith("— не найдена")
    settings_page.roots_list.setCurrentRow(0)
    assert settings_page.relocate_button.isEnabled()
    monkeypatch.setattr(settings_page_module, "choose_folder", lambda *a: str(tmp_path / "new"))
    settings_page.relocate_button.click()
    assert services.catalog.roots()[0].path == tmp_path / "new"
    assert "не найдена" not in settings_page.roots_list.item(0).text()


def test_failed_list(settings_page, tmp_path):
    settings_page.refresh([(tmp_path / "a.cbz", "Архив повреждён или не поддерживается")])
    assert settings_page.failed_toggle.text() == "Не удалось открыть (1)" and settings_page.failed_list.count() == 1
    settings_page.refresh([])
    assert settings_page.failed_toggle.isHidden()


def test_preferences_apply_and_save_immediately(settings_page, services):
    settings_page.theme_combo.setCurrentIndex(settings_page.theme_combo.findData("light"))
    settings_page.cache_spin.setValue(2048)
    settings_page.template_edit.setText("{серия} {страница}")
    settings_page.template_edit.editingFinished.emit()
    saved = load_settings(services.data.settings_file)
    assert (saved.theme, saved.cache_mb, saved.export.template) == ("light", 2048, "{серия} {страница}")
    assert services.cache.budget == 2048 * 2**20
