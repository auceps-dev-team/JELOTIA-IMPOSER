"""Contrôle d'encrage total (TAC).

`total_ink_coverage()` existait, mesurait correctement, et n'était appelée nulle
part : aucune limite d'encrage n'était appliquée dans le pipeline. Le module
documentait pourtant qu'au-delà de ~300 % l'encre ne sèche plus et que le RIP
refuse le fichier.

Le déclencheur concret : un profil offset couché (FOGRA39) produit
légitimement un noir riche à 330 % — parfait pour sa presse, excessif pour le
numérique et le grand format, qui est le métier de l'atelier.
"""

import uuid

import fitz
import pytest
from PIL import Image

from src.core.engines.icc_engine import (
    estimate_ink_coverage,
    total_ink_coverage,
)
from src.core.engines.preflight_engine import PreflightEngine
from src.core.models.domain import (
    ColorMode,
    FileFormat,
    FileItem,
    JobSettings,
    PreflightErrorType,
    PreflightStatus,
)


def _item(path, fmt=FileFormat.PDF):
    return FileItem(
        job_id=uuid.uuid4(), path=path, format=fmt,
        width_mm=50.0, height_mm=50.0, dpi=300, color_mode=ColorMode.CMYK,
    )


@pytest.fixture
def black_pdf(tmp_path):
    """Aplat noir : le cas qui fait exploser l'encrage."""
    path = tmp_path / "noir.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(0, 0, 200, 200), color=(0, 0, 0), fill=(0, 0, 0))
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def white_pdf(tmp_path):
    path = tmp_path / "blanc.pdf"
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    doc.save(str(path))
    doc.close()
    return path


# --- mesure ---------------------------------------------------------------- #

def test_measurement_matches_the_reference_loop():
    """La version numpy doit donner exactement le même résultat que la boucle
    Python qu'elle remplace — sinon l'optimisation change la décision."""
    import random

    random.seed(11)
    img = Image.new("CMYK", (40, 40))
    img.putdata([
        tuple(random.randrange(256) for _ in range(4)) for _ in range(1600)
    ])

    reference = max(sum(p) for p in img.get_flattened_data()) / 255 * 100
    assert total_ink_coverage(img) == pytest.approx(reference)


def test_measurement_finds_the_worst_pixel_not_the_average():
    """Un seul pixel saturé au milieu d'une image claire doit ressortir."""
    img = Image.new("CMYK", (10, 10), (0, 0, 0, 0))
    img.putpixel((5, 5), (255, 255, 255, 255))
    assert total_ink_coverage(img) == pytest.approx(400.0)


def test_non_cmyk_measures_nothing():
    assert total_ink_coverage(Image.new("RGB", (4, 4))) == 0.0


def test_estimate_needs_a_profile_to_mean_anything(black_pdf):
    """Sans profil, mesurer reviendrait à décrire la formule naïve de Pillow,
    qui ne dit rien de la presse : on préfère ne rien affirmer."""
    assert estimate_ink_coverage(black_pdf, None) == 0.0


def test_estimate_reads_a_solid_black_as_heavy(black_pdf, cmyk_profile):
    coverage = estimate_ink_coverage(black_pdf, cmyk_profile)
    assert coverage > 300.0, f"un aplat noir sous FOGRA39 doit être lourd ({coverage:.0f} %)"


def test_estimate_reads_blank_artwork_as_light(white_pdf, cmyk_profile):
    assert estimate_ink_coverage(white_pdf, cmyk_profile) < 50.0


def test_estimate_never_raises_on_a_broken_file(tmp_path, cmyk_profile):
    """La mesure alimente un avertissement : une sonde qui échoue ne doit
    jamais faire tomber un job."""
    broken = tmp_path / "casse.pdf"
    broken.write_bytes(b"pas un pdf du tout")
    assert estimate_ink_coverage(broken, cmyk_profile) == 0.0


def test_estimate_is_fast_enough_to_run_on_every_file(black_pdf, cmyk_profile):
    """La boucle Python d'origine coûtait ~0,65 s par mégapixel : trop lent pour
    être appelé, ce qui explique probablement que la fonction soit restée
    inutilisée."""
    import time

    started = time.perf_counter()
    estimate_ink_coverage(black_pdf, cmyk_profile)
    assert time.perf_counter() - started < 2.0


# --- intégration preflight -------------------------------------------------- #

def test_preflight_warns_above_the_limit(black_pdf, cmyk_profile):
    settings = JobSettings(
        icc_profile_path=str(cmyk_profile), max_ink_coverage=280.0,
        force_cmyk=False, min_dpi=72,
    )
    item = PreflightEngine().run_preflight(_item(black_pdf), settings)

    errors = [e for e in item.preflight_errors
              if e.type == PreflightErrorType.INK_LIMIT_EXCEEDED]
    assert errors, "l'encrage excessif doit être signalé"
    assert not errors[0].is_blocking, "un avertissement, pas un blocage"
    assert "280" in errors[0].message, "la limite doit être citée"
    assert item.preflight_status == PreflightStatus.WARNING


def test_preflight_stays_quiet_below_the_limit(black_pdf, cmyk_profile):
    settings = JobSettings(
        icc_profile_path=str(cmyk_profile), max_ink_coverage=400.0,
        force_cmyk=False, min_dpi=72,
    )
    item = PreflightEngine().run_preflight(_item(black_pdf), settings)
    types = [e.type for e in item.preflight_errors]
    assert PreflightErrorType.INK_LIMIT_EXCEEDED not in types


def test_zero_disables_the_check(black_pdf, cmyk_profile):
    settings = JobSettings(
        icc_profile_path=str(cmyk_profile), max_ink_coverage=0.0,
        force_cmyk=False, min_dpi=72,
    )
    item = PreflightEngine().run_preflight(_item(black_pdf), settings)
    types = [e.type for e in item.preflight_errors]
    assert PreflightErrorType.INK_LIMIT_EXCEEDED not in types


def test_no_profile_means_no_ink_claim(black_pdf):
    """Sans profil configuré, l'encrage réel est indéterminé : mieux vaut se
    taire qu'avertir sur un chiffre qui ne correspond à aucune presse."""
    settings = JobSettings(
        icc_profile_path="", max_ink_coverage=200.0, force_cmyk=False, min_dpi=72,
    )
    item = PreflightEngine().run_preflight(_item(black_pdf), settings)
    types = [e.type for e in item.preflight_errors]
    assert PreflightErrorType.INK_LIMIT_EXCEEDED not in types


def test_a_missing_profile_file_does_not_break_preflight(black_pdf, tmp_path):
    settings = JobSettings(
        icc_profile_path=str(tmp_path / "absent.icc"),
        max_ink_coverage=200.0, force_cmyk=False, min_dpi=72,
    )
    item = PreflightEngine().run_preflight(_item(black_pdf), settings)
    assert item.preflight_status != PreflightStatus.ERROR


def test_the_default_limit_is_the_trade_figure():
    """300 % est le chiffre que cite le métier ; il reste réglable parce que le
    numérique et le grand format demandent souvent moins."""
    assert JobSettings().max_ink_coverage == 300.0
