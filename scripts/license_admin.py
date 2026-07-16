"""Vendor-side license administration for JELOTIA — NOT shipped to customers.

Generate the signing key pair once, then issue licenses. The private key stays
on JELOTIA's machine and MUST NEVER be committed or sent to a customer; the app
only ever carries the public key.

    # One-time setup: create the key pair and print the public key to embed
    uv run python scripts/license_admin.py keygen

    # Issue a license bound to a customer's machine (they read their machine
    # id from F7·INFO SYSTÈME):
    uv run python scripts/license_admin.py issue \
        --tier personal --licensee "Atelier Kribi" \
        --machine <machine_id> --max-files 500 --out atelier_kribi.key

    uv run python scripts/license_admin.py issue \
        --tier enterprise --licensee "JELOTIA SARL" --out jelotia.key
"""

import argparse
import base64
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Private key kept OUTSIDE the repo, next to the app's data folder.
PRIVATE_KEY_FILE = Path.home() / "Jelotia" / "license_signing_key.b64"
LICENSING_MODULE = ROOT / "src" / "core" / "licensing.py"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def _keygen() -> int:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if PRIVATE_KEY_FILE.exists():
        print(f"Une clé privée existe déjà : {PRIVATE_KEY_FILE}")
        print("Supprimez-la manuellement pour en régénérer une")
        print("(cela invalide toutes les licences déjà émises).")
        return 1

    private = Ed25519PrivateKey.generate()
    priv_raw = private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    priv_b64 = base64.b64encode(priv_raw).decode("ascii")
    pub_b64 = base64.b64encode(pub_raw).decode("ascii")

    PRIVATE_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    PRIVATE_KEY_FILE.write_text(priv_b64, encoding="utf-8")

    # Embed the public key in the app automatically.
    text = LICENSING_MODULE.read_text(encoding="utf-8")
    new_text, count = re.subn(
        r'PUBLIC_KEY_B64 = "[^"]*"', f'PUBLIC_KEY_B64 = "{pub_b64}"', text, count=1
    )
    if count:
        LICENSING_MODULE.write_text(new_text, encoding="utf-8")

    print("Paire de clés générée.")
    print(f"  Clé privée (SECRÈTE, ne jamais partager/committer) : {PRIVATE_KEY_FILE}")
    embedded = "oui" if count else "À COLLER manuellement"
    print(f"  Clé publique embarquée dans {LICENSING_MODULE.name} : {embedded}")
    if not count:
        print(f"  PUBLIC_KEY_B64 = \"{pub_b64}\"")
    return 0


def _issue(args) -> int:
    from src.core.licensing import build_signed_license

    if not PRIVATE_KEY_FILE.exists():
        print("Aucune clé privée — lancez d'abord : license_admin.py keygen")
        return 1
    private_b64 = PRIVATE_KEY_FILE.read_text(encoding="utf-8").strip()

    key_text = build_signed_license(
        private_b64,
        tier=args.tier,
        licensee=args.licensee,
        machine_id=args.machine or "",
        max_files_per_day=args.max_files,
        expires=args.expires or "",
        features=[f.strip() for f in (args.features or "").split(",") if f.strip()],
    )

    out = Path(args.out) if args.out else None
    if out:
        out.write_text(key_text, encoding="utf-8")
        print(f"Licence {args.tier} émise pour « {args.licensee } » → {out}")
    else:
        print(key_text)
    return 0


def main() -> int:
    sys.path.insert(0, str(ROOT))
    parser = argparse.ArgumentParser(description="Administration des licences JELOTIA")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("keygen", help="générer la paire de clés (une seule fois)")

    issue = sub.add_parser("issue", help="émettre une licence")
    issue.add_argument("--tier", choices=["personal", "enterprise"], required=True)
    issue.add_argument("--licensee", required=True, help="nom du client")
    issue.add_argument("--machine", default="", help="machine_id (Personnel = lié au poste)")
    issue.add_argument("--max-files", type=int, default=0,
                       help="plafond fichiers/jour (0 = illimité)")
    issue.add_argument("--expires", default="", help="expiration AAAA-MM-JJ (vide = perpétuelle)")
    issue.add_argument("--features", default="",
                       help="modules Entreprise additionnels, séparés par ,")
    issue.add_argument("--out", default="", help="fichier de sortie (sinon affiché)")

    args = parser.parse_args()
    if args.command == "keygen":
        return _keygen()
    if args.command == "issue":
        return _issue(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
