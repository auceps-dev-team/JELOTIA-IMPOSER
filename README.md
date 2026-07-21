# Jelotia Imposer

> **Logiciel Professionnel d'Imposition Automatique Industrielle**
> Version 1.37.1 — Jelotia SARL

---

Jelotia Imposer est un logiciel de pré-presse haute cadence conçu pour automatiser l'ensemble du cycle de traitement de fichiers d'impression : vérification qualité, correction, nesting optimisé et export vers les RIP. Il est capable de gérer jusqu''à **10 000 fichiers par jour** en mode 24/7, sans intervention humaine.

---

## Table des matières

1. [Fonctionnalités](#-fonctionnalités)
2. [Architecture](#-architecture)
3. [Structure du projet](#-structure-du-projet)
4. [Prérequis](#-prérequis)
5. [Installation et lancement](#-installation-et-lancement)
6. [Configuration](#-configuration)
7. [Pipeline de traitement](#-pipeline-de-traitement)
8. [Composants principaux](#-composants-principaux)
9. [Base de données](#-base-de-données)
10. [Tests](#-tests)
11. [Build et packaging](#-build-et-packaging)
12. [Documentation](#-documentation)

---

## ✨ Fonctionnalités

| Fonctionnalité | Description |
|----------------|-------------|
| **Hot Folder** | Surveillance automatique d''un dossier d''entrée — tout fichier déposé déclenche instantanément un pipeline complet |
| **Preflight** | Vérification DPI, mode couleur CMJN, transparences, polices embarquées, dimensions |
| **Correction automatique** | Conversion RGB → CMJN avec profil ICC, rééchantillonnage, ajout fond perdu |
| **Nesting 2D** | Algorithme MaxRects (bin packing) avec taux de remplissage cible ≥ 75% |
| **Repères Graphtec ARMS** | Génération automatique de repères de découpe type 1 et type 2 |
| **Couche CutContour** | Couche de ton direct pour les workflows print & cut |
| **Export multi-format** | PDF/X-4, PDF Standard, TIFF LZW, JPEG — avec gestion ICC et options de compatibilité RIP |
| **Mode TIFF Photoshop** | Export TIFF avec Predictor 2 et RowsPerStrip 4 pour une compatibilité maximale avec les vieux RIP (Maintop, Caldera, Onyx…) |
| **QR Code & badges** | Génération de QR codes et planches de badges |
| **Gestion des licences** | Serveur d''activation en ligne avec licences signées cryptographiquement |
| **Rapport Preflight** | Vue détaillée des anomalies par fichier, avec filtres et export |
| **Tableau de bord** | Statistiques temps réel (jobs, fichiers, taux de remplissage, durée) |
| **Thèmes** | Interface claire ou sombre (PySide6 / Qt 6) |

---

## 🏗 Architecture

Le logiciel repose sur un **pipeline événementiel asynchrone** :

```
[Hot Folder / Dépôt manuel UI]
          │
          ▼
    [Job Queue]  ◄─── asyncio.Queue (thread-safe)
          │
          ▼
    [Worker Pool]  ◄─── ProcessPoolExecutor (N workers = N cœurs CPU)
     ┌────┴────┐
     │         │
     ▼         ▼
[Worker 1] [Worker N]
     │
     ▼
[Pipeline séquentiel par job]
  Import → Preflight → Correction → Nesting → Layout → Export
                                        │
                                   [DB Engine]  ◄─── SQLite (WAL)
                                        │
                                   [Qt Signals]  ◄─── Mise à jour UI
```

**Principes clés :**
- Chaque job s''exécute dans un worker isolé (`multiprocessing`) pour la parallélisation CPU.
- Le bridge `WorkerThread` (`QThread` + `asyncio`) maintient l''UI réactive pendant les traitements lourds.
- La base de données SQLite est partagée entre les workers via SQLAlchemy avec le mode WAL pour les écritures concurrentes.
- Les modèles de domaine (`JobSettings`, `FileItem`, `Sheet`) sont des structures **Pydantic v2** immutables, séparées des modèles ORM.

---

## 📁 Structure du projet

```
jelotia-imposer/
├── main.py                        # Point d''entrée de l''application
├── pyproject.toml                 # Dépendances et métadonnées du projet
├── config.json                    # Configuration principale (auto-généré)
├── alembic.ini                    # Configuration Alembic
│
├── src/
│   ├── core/                      # Logique métier pure
│   │   ├── engines/
│   │   │   ├── import_engine.py       # Lecture, extraction métadonnées
│   │   │   ├── preflight_engine.py    # Validation qualité
│   │   │   ├── correction_engine.py   # Corrections automatiques (ICC, DPI, bleed)
│   │   │   ├── nesting_engine.py      # Algorithme bin packing 2D
│   │   │   ├── layout_engine.py       # Génération planches PDF avec repères
│   │   │   ├── export_engine.py       # Export PDF/X, TIFF, JPEG vers RIP
│   │   │   ├── icc_engine.py          # Gestion profils ICC
│   │   │   ├── bleed_engine.py        # Ajout fond perdu automatique
│   │   │   └── pdf_editor.py          # Edition PDF bas niveau
│   │   ├── models/
│   │   │   └── domain.py              # Modèles Pydantic (Job, FileItem, Sheet, JobSettings)
│   │   ├── processors/
│   │   │   ├── job_processor.py       # Orchestre le pipeline complet pour un job
│   │   │   └── worker_pool.py         # Pool multiprocessing + asyncio
│   │   ├── auto_processor.py          # Groupement automatique des fichiers
│   │   ├── output_manager.py          # Archivage et gestion des sorties
│   │   └── worker_thread.py           # Bridge QThread ↔ asyncio
│   │
│   ├── database/
│   │   ├── models.py                  # Modèles SQLAlchemy ORM
│   │   ├── repository.py              # CRUD — JobRepository
│   │   └── migrations/                # Migrations Alembic
│   │
│   ├── ui/
│   │   ├── main_window.py             # Fenêtre principale + routing
│   │   ├── theme.py                   # ThemeManager (light / dark)
│   │   └── widgets/
│   │       ├── dashboard.py           # Tableau de bord statistiques
│   │       ├── job_queue.py           # File des jobs + Drag & Drop
│   │       ├── job_dialog.py          # Dialogue de création de job
│   │       ├── sheet_preview.py       # Prévisualisation zoomable des planches
│   │       ├── preflight_report.py    # Rapport d''anomalies Preflight
│   │       └── settings_view.py       # Panneau de configuration complet
│   │
│   └── utils/
│       ├── config.py                  # Configuration système (chemins statiques)
│       ├── config_manager.py          # Gestionnaire config JSON (lecture/écriture)
│       └── file_utils.py              # Utilitaires fichiers
│
├── tests/
│   ├── unit/                          # Tests unitaires par moteur
│   └── integration/                   # Tests d''intégration end-to-end
│
├── docs/
│   ├── documentation_technique.md     # Architecture, API interne, DB
│   ├── manuel_installation.md         # Guide d''installation complet
│   ├── manuel_utilisateur.md          # Guide opérateur
│   ├── procedure_maintenance.md       # Maintenance et sauvegarde
│   └── QA_tests.md                    # Plan de tests QA manuel
│
├── scripts/
│   ├── bump_version.py                # Script de gestion des versions
│   └── benchmark_runner.py            # Benchmarks de performance
│
├── installer/
│   ├── jelotia_imposer.spec           # Spec PyInstaller
│   └── jelotia_imposer.iss            # Script Inno Setup (installeur Windows)
│
└── activation_server/                 # Serveur de licences (infrastructure Jelotia)
```

---

## ⚙️ Prérequis

| Composant | Minimum | Recommandé |
|-----------|---------|------------|
| **OS** | Windows 10 64-bit | Windows 11 64-bit |
| **Processeur** | 4 cœurs / 2.0 GHz | 8 cœurs / 3.0 GHz |
| **RAM** | 8 Go | 16 Go |
| **Disque** | 500 Mo (app) | SSD 256 Go+ |
| **Python** | 3.12+ | 3.12+ |
| **uv** | Dernière version | — |

> **Note :** Le gestionnaire de paquets `uv` est obligatoire. Installation : `pip install uv` ou voir [docs.astral.sh/uv](https://docs.astral.sh/uv/).

---

## 🚀 Installation et lancement

### Depuis les sources (développement)

```bash
# 1. Cloner le dépôt
git clone https://github.com/auceps-dev-team/JELOTIA-IMPOSER.git
cd JELOTIA-IMPOSER

# 2. Installer les dépendances
uv sync

# 3. Initialiser la base de données
uv run alembic upgrade head

# 4. Lancer l''application
uv run main.py
```

### Via l''installeur Windows

1. Téléchargez `JelotiaImposer_Setup_x.xx.x.exe`.
2. Exécutez en **tant qu''administrateur**.
3. Suivez l''assistant — les dossiers de travail sont créés automatiquement.

### Dossiers créés au premier lancement

```
C:\Jelotia\
├── HotFolder\
│   ├── Input\        ← Déposez vos fichiers ici
│   ├── Processing\   ← Fichiers en cours de traitement
│   ├── Output\       ← Planches exportées
│   └── Error\        ← Fichiers rejetés
├── Archive\          ← Archivage automatique (par date)
└── Logs\             ← Fichiers de log (rotation automatique)
```

---

## 🔧 Configuration

La configuration est stockée dans `config.json` à la racine du projet et éditée depuis l''interface via **Paramètres**. Voici la structure complète avec les valeurs par défaut :

```json
{
  "paths": {
    "input":   "C:\\Jelotia\\HotFolder\\Input",
    "output":  "C:\\Jelotia\\HotFolder\\Output",
    "archive": "C:\\Jelotia\\Archive",
    "logs":    "C:\\Jelotia\\Logs"
  },
  "imposition": {
    "sheet_width":          550,
    "sheet_height":         890,
    "spacing":              3,
    "margin":               0,
    "rotation_allowed":     true,
    "plotter_marks":        "none",
    "plotter_mark_length":  15,
    "add_bleed":            0.0
  },
  "preflight": {
    "min_dpi":         300,
    "allowed_formats": "A4, A5, B2"
  },
  "export": {
    "format":                "PDF (Standard)",
    "dpi":                   300,
    "icc_profile":           "",
    "tiff_compression":      "tiff_lzw",
    "tiff_photoshop_compat": false,
    "jpeg_color_mode":       "CMYK",
    "pdf_rasterize":         false,
    "cut_contour":           false
  },
  "output": {
    "archive_days":         15,
    "enable_notifications": true
  },
  "automation": {
    "group_delay_minutes": 5,
    "max_files_per_job":   50,
    "scheduled_time":      "",
    "enable_scheduling":   false
  },
  "performance": {
    "workers":         4,
    "memory_limit_mb": 4096
  },
  "ui": {
    "theme": "dark"
  },
  "users": {
    "role": "Admin"
  }
}
```

### Options d''export notables

| Clé | Valeurs | Description |
|-----|---------|-------------|
| `format` | `PDF/X-4`, `PDF (Standard)`, `TIFF`, `JPEG` | Format de sortie des planches |
| `tiff_compression` | `tiff_lzw`, `raw` | Compression TIFF (`raw` = sans compression, pour vieux RIP) |
| `tiff_photoshop_compat` | `true` / `false` | Mode **TIFF Photoshop** : force `Predictor=2`, `RowsPerStrip=4`, sans ICC — compatible avec tous les RIP anciens et modernes |
| `pdf_rasterize` | `true` / `false` | Pixellise les exports PDF — supprime les données vectorielles, maximise la compatibilité RIP |
| `cut_contour` | `true` / `false` | Ajoute une couche CutContour (ton direct) pour les workflows print & cut |

---

## 🔄 Pipeline de traitement

Chaque fichier déposé passe séquentiellement par les étapes suivantes :

```
Fichier (PDF / TIFF / PNG / JPEG)
    │
    ▼ ImportEngine
    Extraction des métadonnées : dimensions (mm), DPI, mode couleur, profil ICC
    │
    ▼ PreflightEngine
    Vérifications : DPI ≥ seuil, CMJN, transparences, polices, fond perdu
    → Statut : OK / WARNING / ERROR
    │
    ▼ CorrectionEngine
    Corrections : RGB→CMJN (ICC), rééchantillonnage, ajout bleed, rotation
    │
    ▼ NestingEngine
    Placement optimisé sur planches (MaxRects BSSF/BLSF/BAF ou Guillotine FFDH)
    → Rotation 0°/90° si autorisée — Fill rate calculé par planche
    │
    ▼ LayoutEngine
    Génération des planches PDF avec repères de coupe, marques de fond perdu,
    numéro de planche, code job et repères plotter Graphtec ARMS
    │
    ▼ ExportEngine
    Conversion au format final : PDF/X-4, PDF Standard, TIFF LZW, JPEG
    → Fichiers prêts pour le RIP
```

---

## 🔩 Composants principaux

### `ImportEngine` — `src/core/engines/import_engine.py`
Lit les fichiers sources (PDF multi-pages, TIFF, JPEG, PNG) et retourne une liste de `FileItem` avec toutes les métadonnées extraites. Les PDF multi-pages produisent un `FileItem` par page.

### `PreflightEngine` — `src/core/engines/preflight_engine.py`
Valide la qualité de chaque fichier selon les paramètres du job. Produit un statut (`OK`, `WARNING`, `ERROR`) et une liste structurée d''anomalies.

### `CorrectionEngine` — `src/core/engines/correction_engine.py`
Applique les corrections nécessaires : conversion colorimétrique, gestion du fond perdu, aplatissement de la transparence. Utilise les profils ICC détectés sur la machine.

### `NestingEngine` — `src/core/engines/nesting_engine.py`
Algorithme de bin packing 2D basé sur `rectpack`. Supporte plusieurs stratégies interchangeables via le pattern **Strategy** (MaxRects BSSF, BLSF, BAF ; Guillotine FFDH). Calcule le `fill_rate` de chaque planche.

### `LayoutEngine` — `src/core/engines/layout_engine.py`
Génère les planches PDF finales en plaçant chaque fichier aux coordonnées calculées par le nesting. Ajoute les repères techniques (coupe, fond perdu, info job, repères Graphtec ARMS).

### `ExportEngine` — `src/core/engines/export_engine.py`
Convertit les planches vers le format final en fonction des paramètres d''export. Gère les profils ICC, la compression TIFF, et le mode de compatibilité Photoshop.

### `JobProcessor` — `src/core/processors/job_processor.py`
Orchestre l''ensemble du pipeline pour un job donné. Appelle les moteurs en séquence et met à jour la base de données à chaque étape.

### `WorkerPool` — `src/core/processors/worker_pool.py`
Gère un pool de workers (`ProcessPoolExecutor`) pour exécuter plusieurs jobs en parallèle. Chaque cœur CPU traite un job indépendamment.

---

## 🗄 Base de données

SQLite avec SQLAlchemy ORM et migrations Alembic.

### Tables principales

| Table | Rôle |
|-------|------|
| `jobs` | Un job = une session de traitement groupant N fichiers |
| `file_items` | Un enregistrement par fichier/page traité |
| `sheets` | Une planche générée par le nesting |

### Colonnes clés — `jobs`

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | UUID (PK) | Identifiant unique |
| `name` | VARCHAR | Nom du job |
| `status` | VARCHAR | `PENDING` / `PROCESSING` / `DONE` / `ERROR` |
| `settings` | JSON | Paramètres `JobSettings` sérialisés |
| `stats` | JSON | Statistiques (durée, fill_rate moyen…) |

### Colonnes clés — `file_items`

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | UUID (PK) | Identifiant unique |
| `job_id` | UUID (FK) | Référence vers `jobs.id` |
| `format` | VARCHAR | `PDF`, `TIFF`, `PNG`, `JPEG` |
| `width_mm` / `height_mm` | FLOAT | Dimensions en millimètres |
| `dpi` | INTEGER | Résolution détectée |
| `color_mode` | VARCHAR | `CMYK`, `RGB`, `GRAY` |
| `quantity` | INTEGER | Nombre d''exemplaires |
| `preflight_status` | VARCHAR | `PENDING` / `OK` / `WARNING` / `ERROR` |
| `preflight_errors` | JSON | Liste des anomalies détectées |

### Migrations Alembic

```bash
# Créer une migration après modification des modèles ORM
uv run alembic revision --autogenerate -m "description"

# Appliquer les migrations
uv run alembic upgrade head
```

---

## 🧪 Tests

```bash
# Toute la suite (282 tests)
uv run pytest tests/

# Avec couverture de code
uv run pytest tests/ --cov=src --cov-report=html

# Tests unitaires uniquement
uv run pytest tests/unit/

# Tests d''intégration uniquement
uv run pytest tests/integration/
```

---

## 📦 Build et packaging

### Générer l''exécutable Windows (PyInstaller)

```bash
uv run pyinstaller --noconfirm installer/jelotia_imposer.spec
# Résultat → dist/JelotiaImposer/JelotiaImposer.exe
```

### Générer l''installeur Windows (Inno Setup)

Ouvrez `installer/jelotia_imposer.iss` dans **Inno Setup Compiler** et cliquez **Compile**.

### Règles de versioning

| Type de changement | Incrément |
|-------------------|-----------|
| Fonctionnalité majeure ou refactoring important | `+0.1.0` |
| Correctif ou fonctionnalité mineure | `+0.0.1` |
| Changement cosmétique / négligeable | aucun |

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [documentation_technique.md](docs/documentation_technique.md) | Architecture, API interne des moteurs, schéma DB, guide d''extension |
| [manuel_installation.md](docs/manuel_installation.md) | Procédure d''installation complète, configuration initiale |
| [manuel_utilisateur.md](docs/manuel_utilisateur.md) | Guide opérateur pas-à-pas |
| [procedure_maintenance.md](docs/procedure_maintenance.md) | Sauvegarde, restauration, réinitialisation |
| [QA_tests.md](docs/QA_tests.md) | Plan de tests QA manuel |

---

## Stack technologique

| Composant | Bibliothèque | Version |
|-----------|-------------|---------|
| Interface graphique | PySide6 (Qt 6) | ≥ 6.8 |
| Lecture PDF | PyMuPDF (fitz) | 1.28 |
| Edition PDF professionnelle | pikepdf | ≥ 9.4 |
| Génération PDF | ReportLab | ≥ 4.2 |
| Images raster | Pillow | ≥ 11.0 |
| Vision / analyse | OpenCV | ≥ 4.10 |
| Nesting 2D | rectpack | 0.2.2 |
| Géométrie | Shapely | ≥ 2.0 |
| Couleurs / ICC | colour-science | ≥ 0.4 |
| QR codes | qrcode | ≥ 8.0 |
| Base de données | SQLAlchemy + SQLite | ≥ 2.0 |
| Migrations | Alembic | ≥ 1.14 |
| Validation | Pydantic v2 | ≥ 2.10 |
| Logging | loguru | ≥ 0.7 |
| Tests | pytest + pytest-cov | — |
| Surveillance dossiers | watchdog | ≥ 6.0 |
| Cryptographie / Licences | cryptography | ≥ 49.0 |

---

© Jelotia SARL — Tous droits réservés.
