# JELOTIA IMPOSER — Procédure de Maintenance

> Version 1.5.1 — Juillet 2026

---

## 1. Sauvegarde de la Base de Données

### 1.1 Sauvegarde Manuelle

La base de données SQLite est stockée dans le fichier `jelotia.db` à la racine du projet.

```bash
# Sauvegarde avec horodatage
copy jelotia.db "backup\jelotia_%DATE:~6,4%%DATE:~3,2%%DATE:~0,2%.db"
```

### 1.2 Sauvegarde Automatisée (Planificateur de Tâches Windows)

Créez une tâche planifiée pour sauvegarder quotidiennement :

1. Ouvrez **Planificateur de tâches Windows** (`taskschd.msc`).
2. Créez une tâche :
   - **Déclencheur** : Tous les jours à 02:00
   - **Action** : Exécuter un script
   - **Script** :

```bat
@echo off
set BACKUP_DIR=C:\Jelotia\Backup
set DATE_STAMP=%DATE:~6,4%%DATE:~3,2%%DATE:~0,2%

if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"

copy /Y "C:\Program Files\JelotiaImposer\jelotia.db" "%BACKUP_DIR%\jelotia_%DATE_STAMP%.db"
copy /Y "C:\Program Files\JelotiaImposer\config.json" "%BACKUP_DIR%\config_%DATE_STAMP%.json"

:: Nettoyage des sauvegardes > 30 jours
forfiles /p "%BACKUP_DIR%" /s /m *.db /d -30 /c "cmd /c del @path" 2>nul
forfiles /p "%BACKUP_DIR%" /s /m *.json /d -30 /c "cmd /c del @path" 2>nul

echo Sauvegarde terminée : %DATE_STAMP%
```

### 1.3 Vérification d'Intégrité

```bash
# Vérifier l'intégrité de la DB SQLite
uv run python -c "import sqlite3; conn = sqlite3.connect('jelotia.db'); print(conn.execute('PRAGMA integrity_check').fetchone())"
# Résultat attendu : ('ok',)
```

---

## 2. Rotation des Logs

### 2.1 Configuration Loguru

Les logs sont gérés par **loguru** avec rotation automatique configurée dans `main.py` :

| Paramètre | Valeur | Description |
|-----------|--------|-------------|
| Rotation | 10 Mo | Nouveau fichier après 10 Mo |
| Rétention | 30 jours | Suppression automatique |
| Compression | zip | Compression des anciens fichiers |
| Format | `{time} | {level} | {name}:{function}:{line} - {message}` | — |

### 2.2 Emplacement des Logs

```
C:\Jelotia\Logs\
├── jelotia.log           ← Log courant
├── jelotia.log.1.zip     ← Archive (rotation)
├── jelotia.log.2.zip
└── ...
```

### 2.3 Nettoyage Manuel

Si l'espace disque est critique :

```bash
# Supprimer les logs de plus de 7 jours
forfiles /p "C:\Jelotia\Logs" /s /m *.zip /d -7 /c "cmd /c del @path"
```

### 2.4 Niveaux de Log

| Niveau | Usage |
|--------|-------|
| `DEBUG` | Détails techniques (désactivé en production) |
| `INFO` | Événements normaux (démarrage, job terminé) |
| `WARNING` | Anomalies non bloquantes (preflight warning) |
| `ERROR` | Erreurs récupérables (fichier corrompu) |
| `CRITICAL` | Erreurs fatales (crash, DB inaccessible) |

Pour changer le niveau de log :

```python
# Dans main.py, modifier le niveau
logger.add("jelotia.log", level="DEBUG")  # Plus verbeux
logger.add("jelotia.log", level="WARNING")  # Moins verbeux
```

---

## 3. Mise à Jour

### 3.1 Mise à Jour depuis les Sources

```bash
# 1. Arrêter l'application

# 2. Sauvegarder
copy jelotia.db jelotia.db.bak
copy config.json config.json.bak

# 3. Récupérer la nouvelle version
git pull origin main

# 4. Mettre à jour les dépendances
uv sync

# 5. Appliquer les migrations DB
uv run alembic upgrade head

# 6. Relancer
uv run main.py
```

### 3.2 Mise à Jour via l'Installeur

1. Arrêtez l'application.
2. Lancez le nouvel installeur — il détecte et met à jour l'installation existante.
3. Relancez l'application.
4. Les migrations DB sont appliquées automatiquement au premier démarrage.

### 3.3 Rollback

En cas de problème après une mise à jour :

```bash
# 1. Arrêter l'application

# 2. Restaurer la base de données
copy jelotia.db.bak jelotia.db

# 3. Revenir à la version précédente
git checkout <tag_version_precedente>
uv sync

# 4. Relancer
uv run main.py
```

---

## 4. Surveillance et Diagnostic

### 4.1 Indicateurs de Santé

| Indicateur | Seuil Normal | Action si Dépassé |
|-----------|-------------|-------------------|
| Mémoire RAM | < 4 Go | Réduire le nombre de workers |
| CPU | < 80% moyen | Normal sous charge |
| Taille DB | < 500 Mo | Archiver les anciens jobs |
| Logs | < 1 Go total | Forcer la rotation |
| File d'attente | < 100 jobs | Augmenter les workers |

### 4.2 Commandes de Diagnostic

```bash
# Vérifier la version
uv run python -c "import toml; print(toml.load('pyproject.toml')['project']['version'])"

# Compter les jobs en base
uv run python -c "
from src.database.models import Base, JobModel
from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session
engine = create_engine('sqlite:///jelotia.db')
with Session(engine) as s:
    total = s.query(func.count(JobModel.id)).scalar()
    print(f'Total jobs: {total}')
"

# Tester la connectivité DB
uv run python -c "
from sqlalchemy import create_engine
engine = create_engine('sqlite:///jelotia.db')
conn = engine.connect()
print('DB OK')
conn.close()
"
```

### 4.3 Résolution de Problèmes Courants

| Problème | Cause Probable | Solution |
|----------|---------------|----------|
| L'application ne démarre pas | Dépendance manquante | `uv sync` |
| Hot Folder ne détecte rien | Chemin incorrect | Vérifier Paramètres > Chemins |
| Jobs bloqués en PROCESSING | Crash précédent | Redémarrer (recovery auto) |
| Erreur "no running event loop" | Bug asyncio | Redémarrer l'application |
| Mémoire excessive | Trop de workers | Réduire dans Paramètres > Performance |
| DB corrompue | Arrêt brutal | Restaurer depuis sauvegarde |

---

## 5. Archivage et Nettoyage

### 5.1 Archivage Automatique

Les fichiers traités sont archivés automatiquement dans `C:\Jelotia\Archive\` avec la structure :

```
Archive/
├── 2026/
│   ├── 07/
│   │   ├── 01/
│   │   │   ├── JOB-ABC123/
│   │   │   │   ├── fichier1.pdf
│   │   │   │   └── fichier2.tiff
│   │   │   └── ...
│   │   └── 02/
│   └── ...
```

### 5.2 Nettoyage Automatique

Le paramètre `archive_days` (défaut : 15 jours) contrôle la durée de rétention des archives. Les archives plus anciennes sont supprimées automatiquement.

Pour modifier :

1. **Via l'interface** : Paramètres > (section output/archivage)
2. **Via config.json** : `"output": {"archive_days": 30}`

### 5.3 Purge Manuelle de la DB

Pour supprimer les anciens jobs de la base :

```bash
uv run python -c "
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
engine = create_engine('sqlite:///jelotia.db')
cutoff = (datetime.utcnow() - timedelta(days=90)).isoformat()
with engine.begin() as conn:
    result = conn.execute(text(f\"DELETE FROM jobs WHERE created_at < '{cutoff}' AND status = 'DONE'\"))
    print(f'{result.rowcount} anciens jobs supprimés')
"
```
