import base64
import json
from datetime import date, timedelta

import pytest

from src.core import licensing
from src.core.licensing import (
    LicenseTier,
    machine_fingerprint,
    parse_license,
    sign_payload,
    unlicensed,
)


@pytest.fixture
def keypair():
    """An ephemeral Ed25519 pair, so tests never depend on the embedded key."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    priv = base64.b64encode(
        private.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
    ).decode()
    pub = base64.b64encode(
        private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    ).decode()
    return priv, pub


def make_key(keypair, **payload):
    priv, _pub = keypair
    body = {
        "tier": "personal", "licensee": "Test", "machine_id": "",
        "max_files_per_day": 0, "expires": "", "features": [],
    }
    body.update(payload)
    body["sig"] = sign_payload(body, priv)
    return base64.b64encode(json.dumps(body, separators=(",", ":")).encode()).decode()


# --------------------------------------------------------------------------- #
#  Tiers & capabilities                                                        #
# --------------------------------------------------------------------------- #

def test_enterprise_unlocks_everything(keypair):
    _priv, pub = keypair
    key = make_key(keypair, tier="enterprise", licensee="JELOTIA SARL")
    lic = parse_license(key, public_key_b64=pub)

    assert lic.valid and lic.is_enterprise
    assert lic.label == "Entreprise"
    assert lic.allows("ganging") and lic.allows("watch_rules") and lic.allows("reports")
    assert lic.unlimited_volume
    assert lic.watermark is False


def test_personal_locks_advanced_modules_and_stamps_watermark(keypair):
    _priv, pub = keypair
    key = make_key(keypair, tier="personal", max_files_per_day=500)
    lic = parse_license(key, public_key_b64=pub)

    assert lic.valid and not lic.is_enterprise
    assert lic.label == "Personnel"
    assert lic.allows("ganging") is False
    assert lic.allows("watch_rules") is False
    assert lic.allows("qr") is True, "les modules de base restent ouverts"
    assert lic.max_files_per_day == 500 and not lic.unlimited_volume
    assert lic.watermark is True


def test_personal_can_be_granted_a_specific_enterprise_feature(keypair):
    _priv, pub = keypair
    key = make_key(keypair, tier="personal", features=["reports"])
    lic = parse_license(key, public_key_b64=pub)
    assert lic.allows("reports") is True
    assert lic.allows("ganging") is False


# --------------------------------------------------------------------------- #
#  Security: signature, tampering, binding, expiry                             #
# --------------------------------------------------------------------------- #

def test_tampering_breaks_the_signature(keypair):
    _priv, pub = keypair
    key = make_key(keypair, tier="personal", max_files_per_day=500)
    data = json.loads(base64.b64decode(key))
    data["tier"] = "enterprise"          # try to self-upgrade
    data["max_files_per_day"] = 0
    forged = base64.b64encode(json.dumps(data, separators=(",", ":")).encode()).decode()

    lic = parse_license(forged, public_key_b64=pub)
    assert not lic.valid
    assert "signature" in lic.reason.lower()


def test_wrong_public_key_rejects(keypair):
    key = make_key(keypair, tier="enterprise")
    other = "A" * 43 + "="  # not the matching key
    lic = parse_license(key, public_key_b64=other)
    assert not lic.valid


def test_machine_binding(keypair):
    _priv, pub = keypair
    key = make_key(keypair, tier="personal", machine_id="MACHINE-A")

    ok = parse_license(key, public_key_b64=pub, fingerprint="MACHINE-A")
    assert ok.valid

    wrong = parse_license(key, public_key_b64=pub, fingerprint="MACHINE-B")
    assert not wrong.valid
    assert "poste" in wrong.reason.lower()


def test_expiry(keypair):
    _priv, pub = keypair
    yesterday = (date(2026, 7, 14) - timedelta(days=1)).isoformat()
    key = make_key(keypair, tier="enterprise", expires=yesterday)

    expired = parse_license(key, public_key_b64=pub, today=date(2026, 7, 14))
    assert not expired.valid and "expir" in expired.reason.lower()

    tomorrow = (date(2026, 7, 14) + timedelta(days=1)).isoformat()
    key2 = make_key(keypair, tier="enterprise", expires=tomorrow)
    assert parse_license(key2, public_key_b64=pub, today=date(2026, 7, 14)).valid


@pytest.mark.parametrize("garbage", ["", "pas une clé", "eyJ0aWVyIjoieCJ9"])
def test_garbage_is_rejected_not_crashed(garbage, keypair):
    _priv, pub = keypair
    lic = parse_license(garbage, public_key_b64=pub)
    assert not lic.valid and lic.reason


def test_unlicensed_is_restricted_personal():
    lic = unlicensed()
    assert not lic.valid
    assert lic.tier == LicenseTier.PERSONAL
    assert lic.allows("ganging") is False
    assert lic.allows("qr") is True
    assert lic.watermark is True
    assert lic.max_files_per_day == licensing.UNLICENSED_MAX_FILES_PER_DAY


# --------------------------------------------------------------------------- #
#  Machine fingerprint                                                         #
# --------------------------------------------------------------------------- #

def test_fingerprint_is_stable_and_opaque():
    a = machine_fingerprint()
    b = machine_fingerprint()
    assert a == b, "l'empreinte doit être stable sur un même poste"
    assert len(a) == 32 and a.isalnum()


# --------------------------------------------------------------------------- #
#  Install / load round-trip                                                   #
# --------------------------------------------------------------------------- #

def test_install_and_current_license_roundtrip(keypair, tmp_path, monkeypatch):
    _priv, pub = keypair
    monkeypatch.setattr(licensing, "PUBLIC_KEY_B64", pub)
    monkeypatch.setattr(licensing, "license_file", lambda: tmp_path / "license.key")
    monkeypatch.setattr(licensing, "_cached", None, raising=False)

    key = make_key(keypair, tier="enterprise", licensee="JELOTIA")
    installed = licensing.install_license(key)
    assert installed.valid and installed.is_enterprise
    assert (tmp_path / "license.key").exists()

    monkeypatch.setattr(licensing, "_cached", None, raising=False)
    assert licensing.current_license(refresh=True).is_enterprise


def test_install_rejects_invalid_without_writing(keypair, tmp_path, monkeypatch):
    _priv, pub = keypair
    monkeypatch.setattr(licensing, "PUBLIC_KEY_B64", pub)
    monkeypatch.setattr(licensing, "license_file", lambda: tmp_path / "license.key")

    result = licensing.install_license("clé bidon")
    assert not result.valid
    assert not (tmp_path / "license.key").exists(), "une clé invalide ne doit pas être stockée"
