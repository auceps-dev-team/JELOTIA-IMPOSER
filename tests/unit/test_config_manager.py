"""ConfigManager must never write through to DEFAULT_CONFIG.

Regression: `DEFAULT_CONFIG.copy()` is shallow, so every sub-dict was shared
with the module constant. Both `load()` (via `self.config[key].update(...)`)
and `set()` rewrote the factory defaults in place — after the first write, a
deleted or corrupted config.json no longer restored factory settings but the
last values typed by the operator.
"""

import copy

import pytest

import src.utils.config_manager as cm
from src.utils.config_manager import ConfigManager


@pytest.fixture
def manager(tmp_path, monkeypatch):
    """A fresh singleton whose live file is redirected into tmp_path, so the
    user's real ~/Jelotia/config.json is never touched."""
    monkeypatch.setattr(cm, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(ConfigManager, "_instance", None, raising=False)
    instance = ConfigManager()
    instance.config_file = tmp_path / "config.json"
    yield instance
    ConfigManager._instance = None


def test_config_does_not_share_sub_dicts_with_the_constant(manager):
    for section, value in manager.config.items():
        if isinstance(value, dict):
            assert value is not cm.DEFAULT_CONFIG.get(section), (
                f"la section « {section} » partage son dict avec DEFAULT_CONFIG"
            )


def test_set_never_mutates_the_factory_defaults(manager):
    pristine = copy.deepcopy(cm.DEFAULT_CONFIG)

    manager.set("imposition", "sheet_width", 4242)
    manager.set("paths", "input", "X:/nowhere")

    assert cm.DEFAULT_CONFIG == pristine, "DEFAULT_CONFIG a été muté par set()"
    assert manager.get("imposition", "sheet_width") == 4242, "la valeur doit être lue"


def test_load_never_mutates_the_factory_defaults(tmp_path, monkeypatch):
    import json

    pristine = copy.deepcopy(cm.DEFAULT_CONFIG)
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps({"imposition": {"sheet_width": 1234}}), encoding="utf-8"
    )

    monkeypatch.setattr(cm, "CONFIG_FILE", config_file)
    monkeypatch.setattr(ConfigManager, "_instance", None, raising=False)
    try:
        instance = ConfigManager()
        assert instance.get("imposition", "sheet_width") == 1234
        assert cm.DEFAULT_CONFIG == pristine, "DEFAULT_CONFIG a été muté par load()"
    finally:
        ConfigManager._instance = None


def test_a_wiped_config_does_not_come_back_with_the_last_written_value(
    tmp_path, monkeypatch
):
    """The point of the fix. A deleted config.json must restore the shipped
    defaults (load() reseeds from the bundled config.json — factory behaviour),
    never the value the operator last saved. With the shallow copy, 9999 had
    been written into the module constant and came back instead.
    """
    monkeypatch.setattr(cm, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(ConfigManager, "_instance", None, raising=False)
    try:
        first = ConfigManager()
        first.config_file = tmp_path / "config.json"
        reference = first.get("imposition", "sheet_width")
        first.set("imposition", "sheet_width", 9999)

        # config.json wiped (corruption, manual reset), singleton restarted.
        (tmp_path / "config.json").unlink(missing_ok=True)
        ConfigManager._instance = None
        second = ConfigManager()

        restored = second.get("imposition", "sheet_width")
        assert restored != 9999, "la valeur saisie a survécu à la remise à zéro"
        assert restored == reference, "les valeurs d'usine doivent être restaurées"
    finally:
        ConfigManager._instance = None
