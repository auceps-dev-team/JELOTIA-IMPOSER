import uuid

import pytest

from src.core.models.domain import JobSettings, ProductPreset, WatchRule
from src.core.watch_rules import (
    active_rules,
    ensure_folders,
    load_rules,
    save_rules,
    settings_for_rule,
)


@pytest.fixture
def config(monkeypatch):
    """The ConfigManager singleton, isolated: its save() is neutralised so the
    tests never write to the real user config.json, and the rules key is
    restored afterwards."""
    from src.utils.config_manager import ConfigManager

    cfg = ConfigManager()
    monkeypatch.setattr(cfg, "save", lambda *a, **k: None)
    automation = cfg.config.setdefault("automation", {})
    original = automation.get("watch_rules")
    automation["watch_rules"] = []
    yield cfg
    if original is None:
        automation.pop("watch_rules", None)
    else:
        automation["watch_rules"] = original


def test_rules_roundtrip(config):
    rules = [
        WatchRule(name="Badges A7", folder="C:/hf/badges", preset_id="p1"),
        WatchRule(name="Vinyle", folder="C:/hf/vinyle", preset_id="p2", enabled=False),
    ]
    save_rules(rules)

    loaded = load_rules()
    assert [r.name for r in loaded] == ["Badges A7", "Vinyle"]
    assert loaded[0].preset_id == "p1"
    assert loaded[1].enabled is False


def test_active_rules_filters_disabled_and_empty(config):
    save_rules([
        WatchRule(name="OK", folder="C:/hf/ok"),
        WatchRule(name="Désactivée", folder="C:/hf/off", enabled=False),
        WatchRule(name="Sans dossier", folder="   "),
    ])
    assert [r.name for r in active_rules()] == ["OK"]


def test_invalid_entries_are_skipped_not_fatal(config):
    config.config["automation"]["watch_rules"] = [
        {"name": "Bonne", "folder": "C:/hf/a", "id": str(uuid.uuid4())},
        {"folder": 12345},  # incohérent
    ]
    rules = load_rules()
    assert [r.name for r in rules] == ["Bonne"], "une règle illisible ne casse pas le reste"


def test_settings_for_rule_uses_the_bound_preset(config, tmp_path, monkeypatch):
    from src.core import presets as presets_module

    store = presets_module.PresetStore(tmp_path / "Presets")
    preset = store.save(
        ProductPreset(
            name="Badge",
            settings=JobSettings(sheet_width_mm=550.0, plotter_marks="graphtec2"),
        )
    )
    monkeypatch.setattr(presets_module, "PresetStore", lambda *a, **k: store)

    rule = WatchRule(name="Badges", folder="C:/hf/b", preset_id=str(preset.id))
    fallback = JobSettings(sheet_width_mm=100.0)

    settings = settings_for_rule(rule, fallback)
    assert settings.sheet_width_mm == 550.0
    assert settings.plotter_marks == "graphtec2"


def test_settings_fall_back_when_no_preset_or_missing(config, tmp_path, monkeypatch):
    from src.core import presets as presets_module

    store = presets_module.PresetStore(tmp_path / "Presets")
    monkeypatch.setattr(presets_module, "PresetStore", lambda *a, **k: store)

    fallback = JobSettings(sheet_width_mm=100.0)
    # Aucune gamme liée.
    assert settings_for_rule(WatchRule(name="X", folder="c:/x"), fallback) is fallback
    assert settings_for_rule(None, fallback) is fallback
    # Gamme supprimée depuis : on retombe sur le global au lieu de planter.
    ghost = WatchRule(name="X", folder="c:/x", preset_id=str(uuid.uuid4()))
    assert settings_for_rule(ghost, fallback) is fallback


def test_ensure_folders_creates_them(tmp_path):
    rules = [
        WatchRule(name="A", folder=str(tmp_path / "hf" / "a")),
        WatchRule(name="B", folder=str(tmp_path / "hf" / "b")),
    ]
    ensure_folders(rules)
    assert (tmp_path / "hf" / "a").is_dir()
    assert (tmp_path / "hf" / "b").is_dir()


# --------------------------------------------------------------------------- #
#  AutoProcessor: rules must never be mixed                                    #
# --------------------------------------------------------------------------- #

def test_files_from_different_rules_are_never_grouped_together():
    """Deux dossiers surveillés portent des gammes différentes (support,
    planche, repères…) : leurs fichiers ne peuvent jamais partager un job,
    même à format identique."""
    from src.core.auto_processor import AutoProcessor

    processor = AutoProcessor()
    processor.add_file("C:/hf/badges/a.pdf", rule_id="rule-badges")
    processor.add_file("C:/hf/vinyle/b.pdf", rule_id="rule-vinyle")
    processor.add_file("C:/hf/badges/c.pdf", rule_id="rule-badges")

    # Même taille physique pour tous : seule la règle doit les séparer.
    for data in processor.pending_files.values():
        data["size"] = (100.0, 100.0)

    groups = {}
    for fp, data in processor.pending_files.items():
        groups.setdefault((data["rule_id"], data["size"]), []).append(fp)

    assert len(groups) == 2, "un groupe par règle, malgré le même format"
    assert len(groups[("rule-badges", (100.0, 100.0))]) == 2
    assert len(groups[("rule-vinyle", (100.0, 100.0))]) == 1


def test_add_file_defaults_to_no_rule():
    from src.core.auto_processor import AutoProcessor

    processor = AutoProcessor()
    processor.add_file("C:/hf/x.pdf")
    assert processor.pending_files["C:/hf/x.pdf"]["rule_id"] == ""
