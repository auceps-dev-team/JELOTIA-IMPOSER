"""C5 — premiers tests de l'interface.

`src/ui/` pèse ~8 300 lignes et aucun test ne l'importait : la couverture
annoncée de 85 % en excluait donc la moitié du code applicatif (réelle : ~34 %).

Ce fichier ne prétend pas couvrir l'interface. Il installe le filet minimal qui
manquait : chaque écran se construit, se remplit et s'enregistre sans exploser.
Trivial en apparence — mais une simple faute de syntaxe dans settings_view.py
passait jusqu'ici toute la suite au vert, puisque rien n'importait ce module.

Les dialogues modaux ne sont jamais exec()'és : on les construit et on inspecte
leur état, sinon la suite se bloquerait sur une fenêtre invisible.
"""

import pytest

pytest.importorskip("pytestqt")


# --------------------------------------------------------------------------- #
#  Chaque module de l'interface doit au moins s'importer                       #
# --------------------------------------------------------------------------- #

UI_MODULES = [
    "src.ui.theme",
    "src.ui.main_window",
    "src.ui.widgets.common",
    "src.ui.widgets.dashboard",
    "src.ui.widgets.job_queue",
    "src.ui.widgets.job_dialog",
    "src.ui.widgets.settings_view",
    "src.ui.widgets.preset_manager",
    "src.ui.widgets.preflight_report",
    "src.ui.widgets.production_report",
    "src.ui.widgets.batch_export_dialog",
    "src.ui.widgets.sheet_preview",
    "src.ui.widgets.sheet_editor",
    "src.ui.widgets.system_info",
    "src.ui.widgets.qr_generator",
    "src.ui.widgets.qr_batch_dialog",
    "src.ui.widgets.qr_template_designer",
    "src.ui.widgets.pdf_editor_view",
]


@pytest.mark.parametrize("module", UI_MODULES)
def test_ui_module_imports(module):
    """Attrape les fautes de syntaxe et les imports cassés — exactement ce que
    la suite laissait passer tant que rien n'importait src.ui."""
    __import__(module)


# --------------------------------------------------------------------------- #
#  Écran de réglages : le pont entre l'opérateur et le pipeline                #
# --------------------------------------------------------------------------- #

@pytest.fixture
def settings(qtbot, tmp_path, monkeypatch):
    """SettingsWidget dont la config est redirigée hors du poste de l'utilisateur."""
    import src.utils.config_manager as cm
    from src.ui.widgets.settings_view import SettingsWidget

    monkeypatch.setattr(cm, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(cm.ConfigManager, "_instance", None, raising=False)
    widget = SettingsWidget()
    qtbot.addWidget(widget)
    yield widget
    cm.ConfigManager._instance = None


def test_settings_screen_builds_and_loads(settings):
    settings.load_settings()
    assert settings.min_dpi.value() > 0
    assert settings.export_dpi.value() > 0


def test_settings_expose_the_wired_fields_only(settings):
    """Les champs retirés (M6) ne doivent pas revenir : ils confirmaient un
    enregistrement qui ne changeait rien."""
    assert hasattr(settings, "workers"), "le nombre de workers est câblé"
    assert hasattr(settings, "allowed_formats"), "les formats autorisés sont câblés"
    assert hasattr(settings, "max_ink"), "la limite d'encrage est câblée"
    assert not hasattr(settings, "memory_limit"), "aucune limite mémoire n'est appliquée"
    assert not hasattr(settings, "user_role"), "aucun contrôle d'accès n'existe"


def test_settings_round_trip_through_the_config(settings, monkeypatch):
    """Ce que l'opérateur saisit doit ressortir tel quel — le contrat de base
    de l'écran, jamais vérifié jusqu'ici."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    settings.min_dpi.setValue(444)
    settings.max_ink.setValue(275)
    settings.allowed_formats.setText("PDF,TIFF")
    settings.save_settings()

    settings.min_dpi.setValue(1)
    settings.max_ink.setValue(1)
    settings.allowed_formats.setText("")
    settings.load_settings()

    assert settings.min_dpi.value() == 444
    assert settings.max_ink.value() == 275
    assert settings.allowed_formats.text() == "PDF,TIFF"


def test_every_settings_category_can_be_shown(settings, qtbot):
    """Chaque page de réglages doit s'afficher : une erreur de mise en page ne
    doit pas rester invisible jusqu'à ce qu'un opérateur clique dessus."""
    from PySide6.QtWidgets import QStackedWidget

    stack = settings.findChild(QStackedWidget)
    assert stack is not None and stack.count() >= 6
    for index in range(stack.count()):
        settings._select_category(index)
        assert stack.currentIndex() == index


# --------------------------------------------------------------------------- #
#  Dialogue de création de job                                                 #
# --------------------------------------------------------------------------- #

def test_job_dialog_builds_and_reports_its_overrides(qtbot, tmp_path):
    from src.ui.widgets.job_dialog import JobDialog

    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    dialog = JobDialog(files=[str(pdf)])
    qtbot.addWidget(dialog)

    dialog.name_input.setText("Commande 42")
    dialog.target_width_input.setValue(60.0)
    data = dialog.get_job_data()

    assert data["name"] == "Commande 42"
    assert data["overrides"]["target_file_width_mm"] == 60.0
    assert data["overrides"]["target_file_height_mm"] is None, "0 = taille d'origine"
    assert str(pdf) in data["files"]


def test_job_dialog_refuses_an_empty_name(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from src.ui.widgets.job_dialog import JobDialog

    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a))
    dialog = JobDialog()
    qtbot.addWidget(dialog)
    dialog.name_input.setText("   ")
    dialog.validate_and_accept()

    assert warned, "un nom vide doit être refusé, pas créer un job anonyme"


# --------------------------------------------------------------------------- #
#  Gammes produit                                                              #
# --------------------------------------------------------------------------- #

def test_preset_manager_round_trips_a_gamme(qtbot, tmp_path, monkeypatch):
    from src.core.presets import PresetStore
    from src.ui.widgets.preset_manager import PresetManagerDialog

    monkeypatch.setattr(PresetStore, "_path", lambda self: tmp_path / "presets.json",
                        raising=False)
    dialog = PresetManagerDialog(store=PresetStore())
    qtbot.addWidget(dialog)

    dialog._new_preset()
    dialog.name_input.setText("Stickers vinyle")
    dialog.sheet_w.setValue(1000)
    dialog.target_w.setValue(45.0)
    dialog._save()

    assert dialog.changed
    saved = [p for p in dialog.store.list() if p.name == "Stickers vinyle"]
    assert saved, "la gamme doit être enregistrée"
    assert saved[0].settings.sheet_width_mm == 1000
    assert saved[0].settings.target_file_width_mm == 45.0
