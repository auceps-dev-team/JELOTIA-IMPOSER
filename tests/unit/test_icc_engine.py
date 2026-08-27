
import pytest
from PIL import Image

from src.core.engines.icc_engine import (
    ICCError,
    convert_image_to_cmyk,
    discover_profiles,
    read_profile,
    total_ink_coverage,
)

# Le profil vient de tests/fixtures (fixture `cmyk_profile` du conftest) et non
# plus de C:/Windows : cherché sur la machine, il manquait sur tout runner de CI
# et ces tests — colorimétrie et export PDF/X, soit ce que l'imprimeur reçoit —
# se sautaient en silence derrière un vert trompeur.


@pytest.fixture
def rgb_image():
    img = Image.new("RGB", (4, 1))
    img.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255), (0, 0, 0)])
    return img


def test_read_profile_identifies_cmyk(cmyk_profile):
    info = read_profile(cmyk_profile)
    assert info is not None
    assert info.is_cmyk, f"le profil doit être CMJN, espace lu : {info.color_space!r}"
    assert info.name


def test_read_profile_returns_none_on_garbage(tmp_path):
    bad = tmp_path / "faux.icc"
    bad.write_bytes(b"pas un profil")
    assert read_profile(bad) is None


def test_discover_finds_a_profile_dropped_by_the_shop(tmp_path, monkeypatch,
                                                      cmyk_profile):
    """Le chemin documenté : l'atelier dépose le profil de sa presse dans son
    dossier Profiles et l'application doit le proposer.

    Le test s'appuyait auparavant sur un profil présent sur la machine ; sans
    dossier système — c'est-à-dire hors Windows, donc sur un runner de CI — il
    n'aurait rien trouvé et serait passé au rouge.
    """
    import shutil

    shop_dir = tmp_path / "Profiles"
    shop_dir.mkdir()
    shutil.copy(str(cmyk_profile), str(shop_dir / cmyk_profile.name))
    monkeypatch.setattr("src.core.engines.icc_engine.profiles_dir", lambda: shop_dir)

    profiles = discover_profiles(cmyk_only=True)

    assert profiles, "le profil déposé par l'atelier doit être découvert"
    assert all(p.is_cmyk for p in profiles), "cmyk_only ne doit rendre que du CMJN"
    assert all(p.path.is_file() for p in profiles)
    assert any(p.path.name == cmyk_profile.name for p in profiles)


def test_discover_ignores_non_profiles(tmp_path, monkeypatch):
    """Un dossier Profiles rempli de fichiers quelconques ne doit rien produire
    plutôt que de faire échouer la découverte."""
    shop_dir = tmp_path / "Profiles"
    shop_dir.mkdir()
    (shop_dir / "notes.txt").write_text("pas un profil")
    (shop_dir / "faux.icc").write_bytes(b"pas un profil non plus")
    monkeypatch.setattr("src.core.engines.icc_engine.profiles_dir", lambda: shop_dir)
    monkeypatch.setattr("src.core.engines.icc_engine._SYSTEM_DIRS", ())

    assert discover_profiles(cmyk_only=True) == []


def test_icc_conversion_is_colorimetric_not_the_naive_formula(rgb_image, cmyk_profile):
    """Le bénéfice réel : la conversion passe par le profil, pas par la formule
    naïve de Pillow (C = 255 - R …).

    Ce test asserait auparavant un noir « 100K propre à moins de 260 % » — vrai
    pour RSWOP, faux pour FOGRA39, qui produit légitimement un noir riche à
    330 %. Le dosage d'encre est une propriété de la condition d'impression
    visée, pas de la gestion des couleurs : le figer revenait à faire dépendre
    la suite du profil installé sur la machine.
    """
    naive = rgb_image.convert("CMYK")
    managed = convert_image_to_cmyk(rgb_image, cmyk_profile)

    naive_black = naive.getpixel((3, 0))
    icc_black = managed.getpixel((3, 0))

    assert sum(naive_black) / 255 * 100 == pytest.approx(300.0, abs=1), (
        "on documente ici le défaut du convert() naïf"
    )
    assert icc_black != naive_black, "la conversion ne doit pas être la formule naïve"
    assert icc_black[3] > 200, "le noir doit être fortement porté par le canal N"
    assert managed.info.get("icc_profile"), "le profil de destination est embarqué"


def test_white_stays_unprinted(cmyk_profile):
    """Garde-fou simple qu'aucun profil ne peut violer : du blanc ne pose pas
    d'encre. Attrape une transformation inversée ou inopérante."""
    white = convert_image_to_cmyk(Image.new("RGB", (2, 2), (255, 255, 255)), cmyk_profile)
    assert total_ink_coverage(white) < 5.0, "le blanc ne doit poser aucune encre"


def test_conversion_differs_from_naive_and_is_cmyk(rgb_image, cmyk_profile):
    managed = convert_image_to_cmyk(rgb_image, cmyk_profile)
    assert managed.mode == "CMYK"
    assert list(managed.get_flattened_data()) != list(
        rgb_image.convert("CMYK").get_flattened_data()
    )
    assert managed.info.get("icc_profile"), "le profil de destination est embarqué"


def test_already_cmyk_is_left_alone(cmyk_profile):
    img = Image.new("CMYK", (2, 2), (10, 20, 30, 40))
    assert convert_image_to_cmyk(img, cmyk_profile) is img


def test_grayscale_is_converted(rgb_image, cmyk_profile):
    grey = Image.new("L", (2, 2), 128)
    assert convert_image_to_cmyk(grey, cmyk_profile).mode == "CMYK"


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

def test_correction_engine_uses_the_configured_profile(tmp_path, cmyk_profile):
    import uuid

    from src.core.engines.correction_engine import CorrectionEngine
    from src.core.models.domain import ColorMode, FileFormat, FileItem, JobSettings

    src = tmp_path / "art.png"
    Image.new("RGB", (8, 8), (0, 0, 0)).save(str(src), dpi=(300, 300))

    settings = JobSettings(force_cmyk=True, icc_profile_path=str(cmyk_profile), min_dpi=72)
    engine = CorrectionEngine(settings, tmp_path / "work")
    item = FileItem(
        job_id=uuid.uuid4(), path=src, format=FileFormat.PNG,
        width_mm=10, height_mm=10, dpi=300, color_mode=ColorMode.RGB,
    )
    out = engine._correct_image(item, cmyk=True, flatten=False, dpi=False)

    with Image.open(out) as result:
        assert result.mode == "CMYK"
        black = result.getpixel((4, 4))
        tagged = bool(result.info.get("icc_profile"))

    naive_black = Image.new("RGB", (2, 2), (0, 0, 0)).convert("CMYK").getpixel((0, 0))
    # Le dosage exact dépend du profil (100K sous SWOP, noir riche sous
    # FOGRA39) : on vérifie que le profil configuré a bien été appliqué, pas
    # qu'il produit tel encrage.
    assert black[3] > 200, f"le noir doit porter sur le canal N, obtenu {black}"
    assert black != naive_black, "le profil configuré doit avoir été appliqué"
    assert tagged, "le fichier corrigé doit être balisé par son profil"


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
