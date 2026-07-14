from src.core.models.domain import JobSettings, ProductPreset
from src.core.presets import PresetStore


def _preset(name="Carte de visite 85×55", **settings):
    defaults = {
        "sheet_width_mm": 450.0, "sheet_height_mm": 320.0, "gap_mm": 2.0,
        "margin_mm": 10.0, "plotter_marks": "graphtec2", "cut_contour_spot": True,
        "export_format": "PDF/X-1a", "export_dpi": 600,
    }
    defaults.update(settings)
    return ProductPreset(
        name=name, support="Couché 350g", settings=JobSettings(**defaults)
    )


def test_preset_roundtrip_keeps_full_recipe(tmp_path):
    store = PresetStore(tmp_path / "Presets")
    saved = store.save(_preset())

    loaded = store.load(saved.id)
    assert loaded.name == "Carte de visite 85×55"
    assert loaded.support == "Couché 350g"
    settings = loaded.settings
    assert settings.sheet_width_mm == 450.0
    assert settings.plotter_marks == "graphtec2"
    assert settings.cut_contour_spot is True
    assert settings.export_format == "PDF/X-1a"
    assert settings.export_dpi == 600
    # La recette embarque bien la réserve ARMS calculée.
    assert settings.plotter_reserve_mm() > 0


def test_preset_list_sorted_and_archived_hidden(tmp_path):
    store = PresetStore(tmp_path / "Presets")
    store.save(_preset("Vignette 50×50"))
    badge = store.save(_preset("Badge A7"))
    store.save(_preset("Affiche A3"))

    names = [p.name for p in store.list()]
    assert names == ["Affiche A3", "Badge A7", "Vignette 50×50"]

    store.set_archived(badge.id, True)
    assert [p.name for p in store.list()] == ["Affiche A3", "Vignette 50×50"]
    assert len(store.list(include_archived=True)) == 3

    store.delete(badge.id)
    assert len(store.list(include_archived=True)) == 2
