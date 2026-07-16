# Serveur d'activation JELOTIA

Service HTTP qui délivre des licences signées à distance. Une machine cliente
envoie son empreinte + un jeton d'achat ; le serveur vérifie le jeton, signe une
licence avec la **clé privée qu'il est seul à détenir**, et la renvoie. L'app
l'installe puis fonctionne hors-ligne.

Ce dossier ne part **jamais** dans le build de l'application desktop (FastAPI /
uvicorn sont dans le groupe de dépendances optionnel `server`).

## Modèle

```
Client (app)                     Serveur JELOTIA
   │  POST /activate                     │
   │  {purchase_token, fingerprint} ───► │  vérifie le jeton (store)
   │                                     │  signe la licence (clé privée)
   │  ◄─── {license_key, tier, ...}      │  enregistre l'activation
   │  install_license(license_key)       │
```

- **Jeton d'achat** : remis au client après la vente (`admin.py add`). Porte le
  droit (tier, plafond, expiration, nb de postes), pas de secret.
- **Clé privée** : jamais dans le code, jamais côté client. Vit uniquement dans
  le processus serveur, via variable d'environnement ou fichier.
- **Empreinte** : renvoyée par l'app (`machine_fingerprint()` — F7). Une licence
  Personnel est liée à ce poste (`--bind-machine`) ; une Entreprise ne l'est pas.

## Configuration (variables d'environnement)

| Variable | Rôle | Défaut |
|---|---|---|
| `JELOTIA_SIGNING_KEY_B64` | clé privée base64 (prioritaire) | — |
| `JELOTIA_SIGNING_KEY_FILE` | chemin vers la clé privée | `~/Jelotia/license_signing_key.b64` |
| `JELOTIA_ACTIVATION_DB` | store de jetons (SQLite) | `~/Jelotia/activation.db` |

La clé privée est la **même** que celle générée par `scripts/license_admin.py
keygen` (elle correspond à la clé publique embarquée dans l'app). Ne jamais la
committer ni la copier sur une machine cliente.

## Créer des jetons

```bash
# Vente Entreprise : 5 postes, non liée à une machine
uv run --group server python -m activation_server.admin add \
    --tier enterprise --licensee "Client X" --max-activations 5

# Personnel : un seul poste, lié à la machine qui active, plafond 500/jour
uv run --group server python -m activation_server.admin add \
    --tier personal --licensee "Atelier Y" --bind-machine --max-files 500

uv run --group server python -m activation_server.admin list
uv run --group server python -m activation_server.admin revoke --token JELO-XXXX-XXXX
```

## Lancer le serveur

```bash
uv sync --group server
uv run --group server uvicorn activation_server.app:app --host 0.0.0.0 --port 8080
```

Endpoints :
- `POST /activate` → `{purchase_token, fingerprint, app_version?}` renvoie
  `{license_key, tier, licensee, reactivation}` (400 si jeton invalide/épuisé).
- `GET /health` → `{"status": "ok"}`.

Réactiver la même machine avec le même jeton est **idempotent** (réinstallation)
et ne consomme pas de poste supplémentaire.

## Sécurité / exploitation

- Mettre le serveur derrière HTTPS (reverse proxy). Le jeton transite en clair
  sinon.
- Sauvegarder `activation.db` (jetons + activations). Il ne contient aucun secret
  mais perdre les activations réinitialise les compteurs de postes.
- Sauvegarder la clé privée hors-ligne. La perdre = ne plus pouvoir émettre de
  licence (et régénérer invalide toutes les licences déjà installées).
