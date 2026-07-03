# JELOTIA IMPOSER — Manuel d'Installation

> Version 1.5.1 — Juillet 2026

---

## 1. Prérequis Système

### 1.1 Configuration Minimale

| Composant | Minimum | Recommandé |
|-----------|---------|------------|
| **OS** | Windows 10 (64-bit) | Windows 11 (64-bit) |
| **Processeur** | 4 cœurs / 2.0 GHz | 8 cœurs / 3.0 GHz |
| **RAM** | 8 Go | 16 Go |
| **Disque** | 500 Mo (application) + espace pour fichiers | SSD 256 Go+ |
| **Écran** | 1920×1080 | 2560×1440 |
| **Python** | 3.12+ | 3.12+ |

### 1.2 Logiciels Requis

- **Python 3.12+** : [python.org](https://www.python.org/downloads/)
- **uv** (gestionnaire de paquets) : `pip install uv` ou [docs.astral.sh/uv](https://docs.astral.sh/uv/)
- **Git** (optionnel, pour les mises à jour) : [git-scm.com](https://git-scm.com/)

---

## 2. Procédure d'Installation

### 2.1 Installation depuis les sources

```bash
# 1. Cloner le dépôt
git clone <URL_DU_DEPOT> jelotia-imposer
cd jelotia-imposer

# 2. Installer les dépendances
uv sync

# 3. Initialiser la base de données
uv run alembic upgrade head

# 4. Lancer l'application
uv run main.py
```

### 2.2 Installation via l'installeur Windows (`.exe`)

1. Téléchargez le fichier `JelotiaImposer_Setup_1.5.1.exe`.
2. Exécutez l'installeur **en tant qu'administrateur**.
3. Suivez l'assistant :
   - Acceptez la licence.
   - Choisissez le répertoire d'installation (défaut : `C:\Program Files\JelotiaImposer`).
   - L'installeur crée automatiquement les dossiers de travail.
4. Un raccourci est créé sur le Bureau et dans le Menu Démarrer.

### 2.3 Dossiers Créés Automatiquement

```
C:\Jelotia\
├── HotFolder\
│   ├── Input\        ← Déposez vos fichiers ici
│   ├── Processing\   ← Fichiers en cours de traitement
│   ├── Output\       ← Planches exportées
│   └── Error\        ← Fichiers rejetés
├── Archive\          ← Archivage (structure par date)
└── Logs\             ← Fichiers de log (rotation automatique)
```

---

## 3. Configuration Initiale

### 3.1 Premier Démarrage

Au premier lancement, l'application crée un fichier `config.json` avec les valeurs par défaut. Vous pouvez les modifier depuis **Paramètres** dans l'interface.

### 3.2 Configuration des Chemins

Ouvrez **Paramètres > Chemins** et configurez :

| Paramètre | Valeur par défaut | Description |
|-----------|-------------------|-------------|
| Dossier d'entrée | `C:\Jelotia\HotFolder\Input` | Surveillance Hot Folder |
| Dossier de sortie | `C:\Jelotia\HotFolder\Output` | Planches exportées |
| Dossier d'archive | `C:\Jelotia\Archive` | Archivage automatique |
| Dossier de logs | `C:\Jelotia\Logs` | Fichiers de log |

### 3.3 Configuration de l'Imposition

| Paramètre | Valeur par défaut | Description |
|-----------|-------------------|-------------|
| Largeur planche | 320 mm | Largeur du support |
| Hauteur planche | 450 mm | Hauteur du support |
| Espacement | 5 mm | Gap entre les éléments |
| Rotation autorisée | Oui | Test rotation 0°/90° |

### 3.4 Configuration du Preflight

| Paramètre | Valeur par défaut | Description |
|-----------|-------------------|-------------|
| DPI minimum | 300 | Seuil de résolution |
| Formats autorisés | A4, A5, B2 | Formats de fichier acceptés |

### 3.5 Configuration de l'Export

| Paramètre | Valeur par défaut | Description |
|-----------|-------------------|-------------|
| Format | PDF | PDF, TIFF ou JPEG |
| Résolution | 300 dpi | Résolution de sortie |
| Profil ICC | Coated FOGRA39 | Profil couleur de sortie |

---

## 4. Sauvegarde et Restauration

### 4.1 Sauvegarde

Les données à sauvegarder :

| Élément | Emplacement | Fréquence |
|---------|-------------|-----------|
| Base de données | `jelotia.db` (racine projet) | Quotidienne |
| Configuration | `config.json` (racine projet) | Après chaque modification |
| Logs | `C:\Jelotia\Logs\` | Hebdomadaire |

**Commande de sauvegarde :**

```bash
# Copier la DB et la config
copy jelotia.db backup\jelotia_%DATE%.db
copy config.json backup\config_%DATE%.json
```

### 4.2 Restauration

```bash
# Arrêter l'application
# Restaurer les fichiers
copy backup\jelotia_YYYYMMDD.db jelotia.db
copy backup\config_YYYYMMDD.json config.json
# Relancer l'application
uv run main.py
```

### 4.3 Réinitialisation Complète

Pour réinitialiser toute la configuration :

```bash
# Supprimer la DB et la config
del jelotia.db
del config.json

# Réinitialiser les migrations
uv run alembic upgrade head

# Relancer (un nouveau config.json sera créé avec les défauts)
uv run main.py
```

---

## 5. Vérification de l'Installation

Après installation, vérifiez que tout fonctionne :

1. **Lancement** : L'application s'ouvre sans erreur.
2. **Dashboard** : Les 4 cartes de statistiques s'affichent.
3. **Hot Folder** : Le bouton "Démarrer Hot Folder" est fonctionnel.
4. **Création Job** : Le bouton "+ Nouveau Job" ouvre le dialogue.
5. **Paramètres** : Tous les onglets sont accessibles et modifiables.

En cas de problème, consultez les logs dans `C:\Jelotia\Logs\` ou lancez avec :

```bash
uv run main.py 2>&1 | tee debug.log
```
