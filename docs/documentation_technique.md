# JELOTIA IMPOSER — Documentation Technique

> **Architecture, API Interne, Schéma DB & Guide d'Extension**
> Version 1.5.1 — Juillet 2026

---

## 1. Architecture Globale

### 1.1 Pattern Architectural : Pipeline Événementiel

```
[Hot Folder / UI Import]
         │
         ▼
   [Job Queue]  ◄─── asyncio.Queue (thread-safe)
         │
         ▼
   [Worker Pool]  ◄─── multiprocessing.Pool (N workers = N cœurs CPU)
    ┌────┴────┐
    │         │
    ▼         ▼
[Worker 1] [Worker N]
    │
    ▼
[Pipeline séquentiel par job] :
  Import → Preflight → Correction → Nesting → Layout → Export
    │           │           │           │         │        │
    └───────────┴───────────┴───────────┴─────────┴────────┘
                                   │
                              [DB Engine]  ◄─── SQLite (journal WAL)
                                   │
                              [UI Signal]  ◄─── Qt Signals via QThread
```

### 1.2 Structure des Répertoires

```
jelotia-imposer/
├── src/
│   ├── core/                    # Logique métier pure
│   │   ├── engines/
│   │   │   ├── import_engine.py       # Lecture et extraction métadonnées
│   │   │   ├── preflight_engine.py    # Validation qualité
│   │   │   ├── correction_engine.py   # Corrections automatiques
│   │   │   ├── nesting_engine.py      # Algorithme bin packing 2D
│   │   │   ├── layout_engine.py       # Génération planches PDF
│   │   │   └── export_engine.py       # Export PDF/X, TIFF, JPEG
│   │   ├── models/
│   │   │   └── domain.py             # Modèles Pydantic (Job, FileItem, Sheet)
│   │   ├── processors/
│   │   │   ├── job_processor.py       # Pipeline séquentiel par job
│   │   │   └── worker_pool.py         # Pool multiprocessing + asyncio
│   │   ├── auto_processor.py          # Groupement automatique des fichiers
│   │   ├── output_manager.py          # Archivage et gestion des sorties
│   │   └── worker_thread.py           # Bridge QThread ↔ asyncio
│   ├── database/
│   │   ├── models.py                  # SQLAlchemy ORM
│   │   ├── repository.py             # CRUD (JobRepository)
│   │   └── migrations/               # Alembic
│   ├── ui/
│   │   ├── main_window.py            # Fenêtre principale + routing
│   │   ├── theme.py                  # ThemeManager (light/dark)
│   │   └── widgets/
│   │       ├── dashboard.py           # Tableau de bord
│   │       ├── job_queue.py           # Liste des jobs + D&D
│   │       ├── job_dialog.py          # Dialogue création job
│   │       ├── sheet_preview.py       # Prévisualisation zoomable
│   │       ├── preflight_report.py    # Rapport d'anomalies
│   │       └── settings_view.py       # Panneau de configuration
│   └── utils/
│       ├── config.py                  # Configuration système (paths)
│       ├── config_manager.py          # Gestionnaire config JSON
│       └── file_utils.py             # Utilitaires fichiers
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── docs/
├── scripts/
├── main.py
└── pyproject.toml
```

### 1.3 Flux de Données

```
Fichier PDF/TIFF → ImportEngine.process_file()
    → FileItem (métadonnées extraites)
    → PreflightEngine.run_preflight()
        → FileItem.preflight_status (OK / WARNING / ERROR)
    → CorrectionEngine.process()
        → FileItem corrigé (CMJN, DPI, bleed)
    → NestingEngine.process()
        → List[Sheet] (placement optimisé)
    → LayoutEngine.process_job_layout()
        → Sheet.export_path (PDF avec repères)
    → ExportEngine.export_sheet()
        → Fichier final PDF/X ou TIFF
```

---

## 2. API Interne des Moteurs

### 2.1 ImportEngine (`src/core/engines/import_engine.py`)

```python
class ImportEngine:
    def process_file(
        self, job_id: UUID, file_path: Path, min_dpi: int = 300
    ) -> List[FileItem]:
        """
        Lit un fichier et retourne un ou plusieurs FileItem.
        Les PDF multi-pages retournent un FileItem par page.
        
        Args:
            job_id: UUID du job parent
            file_path: Chemin du fichier source
            min_dpi: DPI minimum pour la détection
            
        Returns:
            Liste de FileItem avec métadonnées extraites
            (dimensions, DPI, mode couleur, profil ICC)
        """
```

### 2.2 PreflightEngine (`src/core/engines/preflight_engine.py`)

```python
class PreflightEngine:
    def run_preflight(
        self, item: FileItem, settings: JobSettings
    ) -> FileItem:
        """
        Exécute toutes les vérifications qualité sur un FileItem.
        
        Vérifications :
        - Résolution ≥ min_dpi (configurable)
        - Mode couleur (CMJN attendu, RGB = warning)
        - Dimensions vs format autorisé
        - Transparence (canal alpha)
        - Polices embarquées (PDF)
        - Fond perdu (bleed)
        
        Returns:
            FileItem avec preflight_status et preflight_errors mis à jour
        """
```

### 2.3 CorrectionEngine (`src/core/engines/correction_engine.py`)

```python
class CorrectionEngine:
    def __init__(self, settings: JobSettings, processing_dir: Path):
        """
        Args:
            settings: Paramètres du job (DPI cible, bleed, etc.)
            processing_dir: Répertoire temporaire de traitement
        """
    
    def process(self, item: FileItem) -> FileItem:
        """
        Applique les corrections nécessaires :
        - Conversion RGB → CMJN (avec profil ICC)
        - Rééchantillonnage DPI
        - Ajout fond perdu (2-3mm configurable)
        - Aplatissement transparence
        - Redimensionnement / rotation
        """
```

### 2.4 NestingEngine (`src/core/engines/nesting_engine.py`)

```python
class NestingEngine:
    def __init__(self, strategy: NestingStrategy):
        """Strategy pattern : RectpackNestingStrategy ou custom."""
    
    def process(
        self, items: List[FileItem], settings: JobSettings
    ) -> List[Sheet]:
        """
        Place les FileItems sur des planches optimisées.
        
        Algorithmes disponibles :
        - MaxRects BSSF (Best Short Side Fit)
        - MaxRects BLSF (Best Long Side Fit)
        - MaxRects BAF (Best Area Fit)
        - Guillotine FFDH
        
        Contraintes :
        - Espacement configurable (défaut 3mm)
        - Rotation 0°/90° si autorisée
        - Tri par surface décroissante
        - fill_rate calculé par planche
        """
```

### 2.5 LayoutEngine (`src/core/engines/layout_engine.py`)

```python
class LayoutEngine:
    def process_job_layout(
        self, job_id: UUID, sheets: List[Sheet],
        settings: JobSettings, output_dir: Path
    ) -> List[Sheet]:
        """
        Génère le PDF de chaque planche avec :
        - Placement des fichiers selon coordonnées nesting
        - Repères de coupe (croix techniques)
        - Repères de fond perdu
        - Numéro de planche et code Job
        - Marges configurables
        """
```

### 2.6 ExportEngine (`src/core/engines/export_engine.py`)

```python
class ExportEngine:
    def export_sheet(
        self, job_id: UUID, sheet: Sheet,
        base_pdf_path: Path, settings: JobSettings,
        output_dir: Path
    ) -> Path:
        """
        Convertit la planche brute en format final :
        - PDF/X-1a : CMJN forcé, profil ICC Fogra39, OutputIntent
        - PDF/X-4 : Transparences gérées
        - TIFF LZW/ZIP : 4 canaux CMJN
        - JPEG HQ : Qualité 95%
        
        Returns:
            Chemin vers le fichier exporté final
        """
```

---

## 3. Schéma de Base de Données

### 3.1 Tables

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│     jobs         │     │   file_items      │     │    sheets        │
├─────────────────┤     ├──────────────────┤     ├─────────────────┤
│ id (PK, UUID)   │◄───┤ job_id (FK)       │     │ id (PK, UUID)   │
│ name             │     │ id (PK, UUID)    │     │ job_id (FK)     │
│ status           │     │ path             │     │ sheet_number    │
│ created_at       │     │ format           │     │ width_mm        │
│ settings (JSON)  │     │ width_mm         │     │ height_mm       │
│ stats (JSON)     │     │ height_mm        │     │ fill_rate       │
│                  │     │ dpi              │     │ export_path     │
│                  │     │ color_mode       │     │ items (JSON)    │
│                  │◄───┤ quantity          │     │                 │
│                  │     │ preflight_status │     │                 │
│                  │     │ preflight_errors │     │                 │
└─────────────────┘     └──────────────────┘     └─────────────────┘
        │                                               │
        └───────────────────────────────────────────────┘
                    1:N relationships
```

### 3.2 Colonnes Détaillées

#### Table `jobs`

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | `VARCHAR(36)` PK | UUID unique |
| `name` | `VARCHAR(255)` | Nom du job |
| `status` | `VARCHAR(50)` | `PENDING`, `PROCESSING`, `DONE`, `ERROR` |
| `created_at` | `DATETIME` | Date de création |
| `settings` | `JSON` | Paramètres du job (JobSettings sérialisé) |
| `stats` | `JSON` | Statistiques (durée, fill_rate moyen, etc.) |

#### Table `file_items`

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | `VARCHAR(36)` PK | UUID unique |
| `job_id` | `VARCHAR(36)` FK | Référence vers `jobs.id` |
| `path` | `VARCHAR(1024)` | Chemin du fichier source |
| `format` | `VARCHAR(10)` | `PDF`, `TIFF`, `PNG`, `JPEG` |
| `width_mm` / `height_mm` | `FLOAT` | Dimensions en millimètres |
| `dpi` | `INTEGER` | Résolution détectée |
| `color_mode` | `VARCHAR(10)` | `CMYK`, `RGB`, `GRAY` |
| `quantity` | `INTEGER` | Nombre d'exemplaires |
| `preflight_status` | `VARCHAR(50)` | `PENDING`, `OK`, `WARNING`, `ERROR` |
| `preflight_errors` | `JSON` | Liste des anomalies détectées |

#### Table `sheets`

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | `VARCHAR(36)` PK | UUID unique |
| `job_id` | `VARCHAR(36)` FK | Référence vers `jobs.id` |
| `sheet_number` | `INTEGER` | Numéro séquentiel de la planche |
| `width_mm` / `height_mm` | `FLOAT` | Dimensions de la planche |
| `fill_rate` | `FLOAT` | Taux de remplissage (0.0 à 1.0) |
| `export_path` | `VARCHAR(1024)` | Chemin du fichier exporté |
| `items` | `JSON` | Liste des PlacedItem (coordonnées x, y, rotation) |

### 3.3 Migrations

Les migrations sont gérées par **Alembic**. Pour créer une nouvelle migration :

```bash
uv run alembic revision --autogenerate -m "description"
uv run alembic upgrade head
```

---

## 4. Guide d'Extension / Plugins

### 4.1 Ajouter un Nouveau Moteur

1. Créer le fichier dans `src/core/engines/`.
2. Implémenter l'interface attendue (méthode `process()` ou équivalente).
3. L'intégrer dans `src/core/processors/job_processor.py` au bon endroit du pipeline.
4. Ajouter les tests unitaires dans `tests/unit/`.

### 4.2 Ajouter une Stratégie de Nesting

Le `NestingEngine` utilise le pattern **Strategy** :

```python
from src.core.engines.nesting_engine import NestingStrategy

class MyCustomStrategy(NestingStrategy):
    def nest(self, items, sheet_width, sheet_height, spacing):
        # Votre algorithme ici
        return placed_items, fill_rate
```

Puis injectez-la :

```python
engine = NestingEngine(MyCustomStrategy())
```

### 4.3 Ajouter un Format d'Export

1. Créer une méthode dans `ExportEngine` (ex: `_export_svg()`).
2. L'ajouter au `match` dans `export_sheet()`.
3. Ajouter le format dans la liste des options de `SettingsView`.

### 4.4 Ajouter un Widget UI

1. Créer le fichier dans `src/ui/widgets/`.
2. Hériter de `QWidget`.
3. L'ajouter au `QStackedWidget` dans `MainWindow.setup_stacked_widget()`.
4. Ajouter un bouton dans la sidebar (`setup_sidebar()`).

---

## 5. Stack Technologique

| Composant | Bibliothèque | Version |
|-----------|-------------|---------|
| PDF Read/Write | PyMuPDF (fitz) | 1.24+ |
| PDF professionnel | pikepdf | 9.x |
| PDF génération | ReportLab | 4.x |
| Images | Pillow | 10.x |
| Vision/analyse | OpenCV | 4.9+ |
| Nesting 2D | rectpack | 0.2.2 |
| Géométrie | Shapely | 2.x |
| QR Codes | qrcode | 7.x |
| Couleurs/ICC | colour-science | 0.4 |
| UI | PySide6 (Qt 6.7+) | 6.6+ |
| Graphiques | pyqtgraph | 0.13+ |
| DB | SQLite via SQLAlchemy | 2.x |
| Config | Pydantic v2 + JSON | — |
| Logs | loguru | 0.7+ |
| Tests | pytest + pytest-cov | — |
