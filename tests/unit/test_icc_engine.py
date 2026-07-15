from pathlib import Path

import pytest
from PIL import Image

from src.core.engines.icc_engine import (
    ICCError,
    convert_image_to_cmyk,
    discover_profiles,
    read_profile,
    total_ink_coverage,
)

_SWOP = Path("C:/Windows/System32/spool/drivers/color/RSWOP.icm")
_needs_swop = pytest.mark.skipif(
    not _SWOP.is_file(), reason="profil CMJN système absent (RSWOP.icm)"
)


@pytest.fixture
def rgb_image():
    img = Image.new("RGB", (4, 1))
    img.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255), (0, 0, 0)])
    return img


@_needs_swop
def test_read_profile_identifies_cmyk():
    info = read_profile(_SWOP)
    assert info is not None
    assert info.is_cmyk, f"RSWOP doit être CMJN, espace lu : {info.color_space!r}"
    assert info.name


def test_read_profile_returns_none_on_garbage(tmp_path):
    bad = tmp_path / "faux.icc"
    bad.write_bytes(b"pas un profil")
    assert read_profile(bad) is None


@_needs_swop
def test_discover_finds_only_cmyk_profiles():
    profiles = discover_profiles(cmyk_only=True)
    assert profiles, "au moins un profil CMJN doit être trouvé sur le poste"
    assert all(p.is_cmyk for p in profiles)
    assert all(p.path.is_file() for p in profiles)


@_needs_swop
def test_icc_black_is_clean_100k_not_300_percent_ink(rgb_image):
    """LE bénéfice mesurable : la conversion naïve de Pillow transforme le noir
    pur en C+M+J+N = 300 % d'encre (indéchable, refusé par les RIP) ; l'ICC
    donne un noir 100K propre à 100 %."""
    naive = rgb_image.convert("CMYK")
    managed = convert_image_to_cmyk(rgb_image, _SWOP)

    naive_black = naive.getpixel((3, 0))
    icc_black = managed.getpixel((3, 0))

    assert sum(naive_black) / 255 * 100 == pytest.approx(300.0, abs=1), (
        "on documente ici le défaut du convert() naïf"
    )
    assert icc_black[3] > 200, "le noir ICC doit être porté par le canal N"
    assert max(icc_black[:3]) < 60, f"CMJ doivent rester faibles, obtenu {icc_black[:3]}"
    assert total_ink_coverage(managed) < 260.0, "encrage total dans les limites RIP"


@_needs_swop
def test_conversion_differs_from_naive_and_is_cmyk(rgb_image):
    managed = convert_image_to_cmyk(rgb_image, _SWOP)
    assert managed.mode == "CMYK"
    assert list(managed.get_flattened_data()) != list(
        rgb_image.convert("CMYK").get_flattened_data()
    )
    assert managed.info.get("icc_profile"), "le profil de destination est embarqué"


@_needs_swop
def test_already_cmyk_is_left_alone():
    img = Image.new("CMYK", (2, 2), (10, 20, 30, 40))
    assert convert_image_to_cmyk(img, _SWOP) is img


@_needs_swop
def test_grayscale_is_converted(rgb_image):
    grey = Image.new("L", (2, 2), 128)
    assert convert_image_to_cmyk(grey, _SWOP).mode == "CMYK"


def test_missing_profile_raises(rgb_image, tmp_path):
    with pytest.raises(ICCError):
        convert_image_to_cmyk(rgb_image, tmp_path / "absent.icc")


def test_invalid_profile_raises(rgb_image, tmp_path):
    bad = tmp_path / "faux.icc"
    bad.write_bytes(b"pas un profil")
    with pytest.raises(ICCError):
        convert_image_to_cmyk(rgb_image, bad)


def test_total_ink_coverage_measures_the_worst_pixel():
    img = Image.new("CMYK", (2, 1))
    img.putdata([(0, 0, 0, 255), (255, 255, 255, 255)])
    assert total_ink_coverage(img) == pytest.approx(400.0)
    assert total_ink_coverage(Image.new("RGB", (1, 1))) == 0.0


# --------------------------------------------------------------------------- #
#  Correction engine integration                                               #
# --------------------------------------------------------------------------- #

@_needs_swop
def test_correction_engine_uses_the_configured_profile(tmp_path):
    import uuid

    from src.core.engines.correction_engine import CorrectionEngine
    from src.core.models.domain import ColorMode, FileFormat, FileItem, JobSettings

    src = tmp_path / "art.png"
    Image.new("RGB", (8, 8), (0, 0, 0)).save(str(src), dpi=(300, 300))

    settings = JobSettings(force_cmyk=True, icc_profile_path=str(_SWOP), min_dpi=72)
    engine = CorrectionEngine(settings, tmp_path / "work")
    item = FileItem(
        job_id=uuid.uuid4(), path=src, format=FileFormat.PNG,
        width_mm=10, height_mm=10, dpi=300, color_mode=ColorMode.RGB,
    )
    out = engine._correct_image(item, cmyk=True, flatten=False, dpi=False)

    with Image.open(out) as result:
        assert result.mode == "CMYK"
        black = result.getpixel((4, 4))
    assert black[3] > 200 and max(black[:3]) < 60, (
        f"le noir doit sortir en 100K via l'ICC, obtenu {black}"
    )


def test_correction_engine_falls_back_without_profile(tmp_path, caplog):
    """Sans profil, on ne fait pas échouer le job : on convertit
    approximativement MAIS on le dit."""
    import uuid

    from src.core.engines.correction_engine import CorrectionEngine
    from src.core.models.domain import ColorMode, FileFormat, FileItem, JobSettings

    src = tmp_path / "art.png"
    Image.new("RGB", (4, 4), (0, 0, 0)).save(str(src), dpi=(300, 300))

    engine = CorrectionEngine(JobSettings(force_cmyk=True, icc_profile_path=""),
                              tmp_path / "work")
    item = FileItem(
        job_id=uuid.uuid4(), path=src, format=FileFormat.PNG,
        width_mm=10, height_mm=10, dpi=300, color_mode=ColorMode.RGB,
    )
    with caplog.at_level("WARNING"):
        out = engine._correct_image(item, cmyk=True, flatten=False, dpi=False)

    with Image.open(out) as result:
        assert result.mode == "CMYK"
    assert any("profil icc" in r.message.lower() for r in caplog.records), (
        "l'absence de gestion couleur doit être signalée"
    )


def test_correction_no_longer_pads_white_bleed(tmp_path):
    """Régression : la correction ajoutait un cadre BLANC en guise de fond
    perdu — exactement le liseré que le fond perdu doit éviter. C'est
    désormais BleedEngine qui s'en charge, après la correction."""
    import uuid

    from src.core.engines.correction_engine import CorrectionEngine
    from src.core.models.domain import ColorMode, FileFormat, FileItem, JobSettings

    src = tmp_path / "art.png"
    Image.new("RGB", (100, 100), (255, 0, 0)).save(str(src), dpi=(254, 254))

    settings = JobSettings(add_bleed_mm=3.0, force_cmyk=False, min_dpi=72)
    engine = CorrectionEngine(settings, tmp_path / "work")
    item = FileItem(
        job_id=uuid.uuid4(), path=src, format=FileFormat.PNG,
        width_mm=10, height_mm=10, dpi=254, color_mode=ColorMode.RGB,
    )
    out = engine._correct_image(item, cmyk=False, flatten=False, dpi=False)

    with Image.open(out) as result:
        assert result.size == (100, 100), "la correction ne doit plus agrandir l'image"
        assert result.getpixel((1, 1))[0] > 200, "aucun cadre blanc ajouté"
    assert item.width_mm == 10, "les dimensions ne sont plus modifiées ici"
