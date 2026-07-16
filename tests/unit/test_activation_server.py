"""Activation server: token redemption policy + HTTP endpoint.

Skipped entirely when the optional `server` group isn't installed, so the
default `uv run pytest` stays green; run with `uv run --group server pytest`.
"""

import base64

import pytest

fastapi = pytest.importorskip("fastapi")  # noqa: F841
from fastapi.testclient import TestClient  # noqa: E402

from activation_server.app import create_app  # noqa: E402
from activation_server.issuer import activate  # noqa: E402
from activation_server.store import Token, TokenStore  # noqa: E402
from src.core import licensing  # noqa: E402
from src.core.licensing import parse_license  # noqa: E402


@pytest.fixture
def keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    priv = base64.b64encode(private.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )).decode()
    pub = base64.b64encode(private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )).decode()
    return priv, pub


@pytest.fixture
def store(tmp_path):
    s = TokenStore(tmp_path / "activation.db")
    yield s
    s.close()


def _verify(key_text, pub, **kw):
    return parse_license(key_text, public_key_b64=pub, **kw)


# --- issuer policy --------------------------------------------------------- #

def test_enterprise_token_issues_unbound_enterprise_license(keypair, store):
    priv, pub = keypair
    store.add_token(Token("T-ENT", tier="enterprise", licensee="Client X",
                          max_activations=3))
    res = activate(store, priv, "T-ENT", "FINGERPRINT-1")

    assert res.ok and res.tier == "enterprise"
    lic = _verify(res.license_key, pub)
    assert lic.valid and lic.is_enterprise and lic.licensee == "Client X"
    assert lic.machine_id == "", "Entreprise n'est pas liée à un poste"


def test_personal_bound_token_binds_to_the_activating_machine(keypair, store):
    priv, pub = keypair
    store.add_token(Token("T-PERS", tier="personal", licensee="Atelier Y",
                          max_files_per_day=500, bind_machine=True))
    res = activate(store, priv, "T-PERS", "MACHINE-A")

    # Valid on the machine that activated, rejected elsewhere.
    assert _verify(res.license_key, pub, fingerprint="MACHINE-A").valid
    wrong = _verify(res.license_key, pub, fingerprint="MACHINE-B")
    assert not wrong.valid and "poste" in wrong.reason.lower()


def test_unknown_and_revoked_tokens_are_refused(keypair, store):
    priv, _pub = keypair
    assert not activate(store, priv, "NOPE", "FP").ok
    store.add_token(Token("T-REV", tier="enterprise"))
    store.revoke("T-REV")
    res = activate(store, priv, "T-REV", "FP")
    assert not res.ok and "révoqué" in res.error.lower()


def test_activation_limit_enforced_but_same_machine_reactivates(keypair, store):
    priv, _pub = keypair
    store.add_token(Token("T-1", tier="personal", bind_machine=True, max_activations=1))

    first = activate(store, priv, "T-1", "MACHINE-A")
    assert first.ok and not first.reactivation

    # Same machine again → allowed (reinstall), no new slot consumed.
    again = activate(store, priv, "T-1", "MACHINE-A")
    assert again.ok and again.reactivation
    assert store.activation_count("T-1") == 1

    # A different machine → refused, the single slot is taken.
    other = activate(store, priv, "T-1", "MACHINE-B")
    assert not other.ok and "activations" in other.error.lower()


def test_expired_entitlement_refused(keypair, store):
    priv, _pub = keypair
    store.add_token(Token("T-EXP", tier="enterprise", expires="2020-01-01"))
    res = activate(store, priv, "T-EXP", "FP")
    assert not res.ok and "expir" in res.error.lower()


# --- HTTP endpoint --------------------------------------------------------- #

def test_activate_endpoint_returns_installable_license(keypair, store, monkeypatch):
    priv, pub = keypair
    monkeypatch.setattr(licensing, "PUBLIC_KEY_B64", pub)
    store.add_token(Token("T-HTTP", tier="enterprise", licensee="JELOTIA SARL"))
    client = TestClient(create_app(store=store, private_key_b64=priv))

    resp = client.post("/activate", json={
        "purchase_token": "T-HTTP", "fingerprint": "FP-9", "app_version": "1.35.0",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["tier"] == "enterprise" and body["reactivation"] is False
    # The returned key installs cleanly against the app's verifier.
    assert parse_license(body["license_key"]).is_enterprise


def test_activate_endpoint_rejects_bad_token(keypair, store):
    priv, _pub = keypair
    client = TestClient(create_app(store=store, private_key_b64=priv))
    resp = client.post("/activate", json={"purchase_token": "X", "fingerprint": "FP"})
    assert resp.status_code == 400
    assert "inconnu" in resp.json()["detail"].lower()


def test_health(keypair, store):
    priv, _pub = keypair
    client = TestClient(create_app(store=store, private_key_b64=priv))
    assert client.get("/health").json() == {"status": "ok"}
