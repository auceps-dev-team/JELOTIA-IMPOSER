"""Manage purchase tokens for the activation server (vendor-side).

    # Create a token for an Enterprise sale (5 machines, not machine-bound)
    python -m activation_server.admin add --tier enterprise \
        --licensee "Client X" --max-activations 5

    # A single-machine Personal token, capped at 500 files/day
    python -m activation_server.admin add --tier personal \
        --licensee "Atelier Y" --bind-machine --max-files 500

    python -m activation_server.admin list
    python -m activation_server.admin revoke --token JELO-XXXX-XXXX
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

from activation_server.store import Token, TokenStore


def _db_path(args) -> str:
    return args.db or os.environ.get("JELOTIA_ACTIVATION_DB") or str(
        Path.home() / "Jelotia" / "activation.db"
    )


def _new_token() -> str:
    body = secrets.token_hex(8).upper()
    return f"JELO-{body[:4]}-{body[4:8]}-{body[8:12]}-{body[12:16]}"


def _add(store: TokenStore, args) -> int:
    token = args.token or _new_token()
    store.add_token(Token(
        token=token,
        tier=args.tier,
        licensee=args.licensee,
        max_files_per_day=args.max_files,
        expires=args.expires or "",
        features=",".join(f.strip() for f in (args.features or "").split(",") if f.strip()),
        bind_machine=args.bind_machine,
        max_activations=args.max_activations,
    ))
    print(f"Jeton créé pour « {args.licensee} » ({args.tier}) :")
    print(f"  {token}")
    print(f"  activations max : {args.max_activations}"
          f"{' · lié au poste' if args.bind_machine else ''}")
    return 0


def _list(store: TokenStore, _args) -> int:
    rows = store.list_tokens()
    if not rows:
        print("Aucun jeton.")
        return 0
    print(f"{'JETON':<26} {'TIER':<11} {'UTIL.':<7} {'RÉVOQUÉ':<8} LICENCIÉ")
    for r in rows:
        used = f"{r['used']}/{r['max_activations']}"
        print(f"{r['token']:<26} {r['tier']:<11} {used:<7} "
              f"{'oui' if r['revoked'] else '—':<8} {r['licensee']}")
    return 0


def _revoke(store: TokenStore, args) -> int:
    if store.revoke(args.token):
        print(f"Jeton révoqué : {args.token}")
        return 0
    print(f"Jeton introuvable : {args.token}")
    return 1


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    parser = argparse.ArgumentParser(description="Gestion des jetons d'activation JELOTIA")
    parser.add_argument("--db", default="", help="chemin du store (sinon env/défaut)")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="créer un jeton d'achat")
    add.add_argument("--tier", choices=["personal", "enterprise"], required=True)
    add.add_argument("--licensee", required=True)
    add.add_argument("--token", default="", help="jeton imposé (sinon généré)")
    add.add_argument("--max-files", type=int, default=0, help="plafond fichiers/jour (0=illimité)")
    add.add_argument("--expires", default="", help="expiration AAAA-MM-JJ (vide=perpétuelle)")
    add.add_argument("--features", default="", help="modules Entreprise en plus, séparés par ,")
    add.add_argument("--bind-machine", action="store_true",
                     help="lier la licence au poste qui active (Personnel)")
    add.add_argument("--max-activations", type=int, default=1,
                     help="nombre de postes pouvant activer ce jeton")

    lst = sub.add_parser("list", help="lister les jetons")  # noqa: F841

    rev = sub.add_parser("revoke", help="révoquer un jeton")
    rev.add_argument("--token", required=True)

    args = parser.parse_args()
    store = TokenStore(_db_path(args))
    try:
        if args.command == "add":
            return _add(store, args)
        if args.command == "list":
            return _list(store, args)
        if args.command == "revoke":
            return _revoke(store, args)
    finally:
        store.close()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
