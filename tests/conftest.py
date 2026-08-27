"""Fixtures partagées par toute la suite.

Le profil CMJN est fourni ici plutôt que cherché sur la machine : les tests
s'appuyaient sur `C:/Windows/.../RSWOP.icm` et se sautaient en silence dès qu'il
manquait, c'est-à-dire sur tout runner de CI. La colorimétrie et l'export PDF/X
n'étaient alors validés nulle part, tout en affichant un vert rassurant.

Voir `tests/fixtures/README.md` pour la provenance et la licence du profil.
"""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CMYK_PROFILE = FIXTURES_DIR / "ISOcoated_v2_bas.ICC"


@pytest.fixture(scope="session")
def cmyk_profile() -> Path:
    """Profil CMJN FOGRA39 versionné avec le dépôt.

    Volontairement une erreur dure et non un skip : si le fichier disparaît, la
    suite doit le dire franchement plutôt que de reprendre l'habitude de sauter
    les tests de couleur.
    """
    if not CMYK_PROFILE.is_file():
        raise RuntimeError(
            f"Profil CMJN de test introuvable : {CMYK_PROFILE}. "
            "Il est versionné avec le dépôt (voir tests/fixtures/README.md)."
        )
    return CMYK_PROFILE


@pytest.fixture(scope="session")
def embedded_ttf() -> str:
    """Police TTF réellement embarquable, disponible sur toute plateforme.

    Bitstream Vera est livrée avec reportlab, dépendance dure du projet : rien à
    verser au dépôt et le cas « police embarquée » du preflight tourne partout,
    au lieu d'être sauté hors Windows.
    """
    import reportlab

    return str(Path(reportlab.__file__).parent / "fonts" / "Vera.ttf")
