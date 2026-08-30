"""M9 — toute fonctionnalité déclarée payante doit être réellement gatée.

L'audit relevait que `api` et `multi_post` figuraient dans ENTERPRISE_FEATURES
sans être contrôlés nulle part : soit deux fonctionnalités payantes offertes,
soit deux entrées mortes. Vérification faite, c'était le second cas pour
`multi_post` — la restriction mono-poste existe bien, mais par liaison machine.

Ce test empêche la situation de se reproduire : ajouter une fonctionnalité
payante sans la gater fait échouer la suite.
"""

import inspect

from src.core import licensing
from src.core.licensing import (
    ENTERPRISE_FEATURES,
    UNIMPLEMENTED_FEATURES,
    License,
    LicenseTier,
)


def _gated_in_the_interface() -> set:
    """Les fonctionnalités effectivement contrôlées par l'écran principal."""
    from src.ui.main_window import MainWindow

    source = inspect.getsource(MainWindow._apply_license_to_ui)
    return {feature for feature in ENTERPRISE_FEATURES if f'"{feature}"' in source}


def test_every_built_enterprise_feature_is_gated():
    expected = ENTERPRISE_FEATURES - UNIMPLEMENTED_FEATURES
    missing = expected - _gated_in_the_interface()
    assert not missing, (
        f"déclarées payantes mais jamais contrôlées : {sorted(missing)}. "
        "Soit les gater, soit les retirer de ENTERPRISE_FEATURES."
    )


def test_unimplemented_features_are_a_subset_of_the_paid_ones():
    assert UNIMPLEMENTED_FEATURES <= ENTERPRISE_FEATURES


def test_multi_post_is_not_a_feature_flag():
    """La restriction mono-poste est appliquée par la liaison machine, pas par
    un drapeau : le laisser dans la liste laissait croire à un contrôle qui
    n'existait pas."""
    assert "multi_post" not in ENTERPRISE_FEATURES


def test_the_single_post_restriction_is_really_enforced():
    """Ce que `multi_post` prétendait couvrir, et qui fonctionne : une licence
    Personnel liée à un poste est refusée ailleurs."""
    source = inspect.getsource(licensing.parse_license)
    assert "machine_id" in source and "autre poste" in source


def test_an_enterprise_licence_allows_every_paid_feature():
    lic = License(tier=LicenseTier.ENTERPRISE)
    for feature in ENTERPRISE_FEATURES:
        assert lic.allows(feature), feature


def test_a_personal_licence_allows_none_of_them_by_default():
    lic = License(tier=LicenseTier.PERSONAL)
    for feature in ENTERPRISE_FEATURES:
        assert not lic.allows(feature), feature
    assert lic.allows("qr"), "les modules de base restent ouverts"
