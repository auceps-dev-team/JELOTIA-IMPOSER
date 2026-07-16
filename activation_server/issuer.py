"""Turn a redeemed purchase token into a signed license.

Framework-agnostic on purpose: the FastAPI layer only does HTTP; the actual
policy (token valid? activation slots left? machine-bound?) lives here and is
unit-tested without a server. Reuses build_signed_license() so the payload shape
stays identical to what the app's parse_license() verifies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from activation_server.store import TokenStore
from src.core.licensing import build_signed_license


@dataclass
class ActivationResult:
    ok: bool
    license_key: str = ""
    tier: str = ""
    licensee: str = ""
    error: str = ""
    reactivation: bool = False   # True if this machine had already activated


def activate(
    store: TokenStore,
    private_key_b64: str,
    purchase_token: str,
    fingerprint: str,
    today: Optional[date] = None,
) -> ActivationResult:
    token = (purchase_token or "").strip()
    fp = (fingerprint or "").strip()
    if not token or not fp:
        return ActivationResult(False, error="Jeton et empreinte requis")

    row = store.get(token)
    if row is None:
        return ActivationResult(False, error="Jeton d'achat inconnu")
    if row["revoked"]:
        return ActivationResult(False, error="Jeton révoqué")

    # An expired entitlement can't mint a license — reject before signing.
    if row["expires"]:
        try:
            if date.fromisoformat(row["expires"]) < (today or date.today()):
                return ActivationResult(False, error="Entitlement expiré")
        except ValueError:
            return ActivationResult(False, error="Date d'expiration invalide")

    already = store.has_activation(token, fp)
    if not already and store.activation_count(token) >= row["max_activations"]:
        return ActivationResult(
            False, error="Nombre d'activations atteint pour ce jeton"
        )

    machine_id = fp if row["bind_machine"] else ""
    features = [f for f in (row["features"] or "").split(",") if f.strip()]
    license_key = build_signed_license(
        private_key_b64,
        tier=row["tier"],
        licensee=row["licensee"],
        machine_id=machine_id,
        max_files_per_day=row["max_files_per_day"],
        expires=row["expires"],
        features=features,
    )

    if not already:
        store.record_activation(token, fp)

    return ActivationResult(
        ok=True,
        license_key=license_key,
        tier=row["tier"],
        licensee=row["licensee"],
        reactivation=already,
    )
