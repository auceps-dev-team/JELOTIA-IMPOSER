# JELOTIA IMPOSER — Manuel Utilisateur

> **Logiciel Professionnel d'Imposition Automatique Industrielle**
> Version 1.5.1 — Juillet 2026

---

## 1. Guide de Démarrage Rapide

### 1.1 Premier Lancement

1. Lancez l'application via le raccourci **Jelotia Imposer** sur le bureau ou exécutez `main.py`.
2. L'application s'ouvre sur le **Tableau de Bord** (Dashboard).
3. Configurez les chemins dans **Paramètres > Chemins** :
   - **Dossier d'entrée** : `C:/Jelotia/HotFolder/Input`
   - **Dossier de sortie** : `C:/Jelotia/HotFolder/Output`
   - **Dossier d'archive** : `C:/Jelotia/Archive`
   - **Dossier de logs** : `C:/Jelotia/Logs`
4. Cliquez **Sauvegarder** et redémarrez si nécessaire.

### 1.2 Votre Premier Job

1. Naviguez vers **Gestion des Jobs** via la barre latérale.
2. Cliquez **+ Nouveau Job** ou glissez-déposez des fichiers PDF/TIFF/PNG/JPEG.
3. Nommez le job, sélectionnez la priorité et ajustez les paramètres si besoin.
4. Cliquez **Valider** — le système lance automatiquement le Preflight.
5. Si des anomalies sont détectées, un rapport apparaît :
   - **Corriger automatiquement** : applique les corrections recommandées.
   - **Ignorer et continuer** : crée le job sans correction.
6. Le job passe en statut **PROCESSING** puis **DONE** une fois terminé.

### 1.3 Mode Hot Folder (Automatique)

1. Activez le Hot Folder depuis le **Tableau de Bord** (bouton **Démarrer Hot Folder**).
2. Déposez vos fichiers dans le dossier d'entrée configuré.
3. Le système détecte automatiquement les nouveaux fichiers, les groupe et lance le traitement.
4. Les planches exportées apparaissent dans le dossier de sortie.

---

## 2. Description des Écrans

### 2.1 Tableau de Bord (Dashboard)

Le tableau de bord offre une vue synthétique de l'activité :

| Carte | Description |
|-------|-------------|
| **Jobs Actifs** | Nombre de jobs en cours de traitement |
| **Planches Générées** | Total des planches créées dans la session |
| **Erreurs Preflight** | Nombre d'erreurs détectées lors du dernier contrôle |
| **Taux de Remplissage** | Moyenne du fill rate sur les planches générées |

**Graphique de Production** : Affiche l'historique de production sur les 7 derniers jours.

**Bouton Hot Folder** : Démarre ou arrête la surveillance automatique du dossier d'entrée.

### 2.2 Gestion des Jobs

Cet écran affiche l'ensemble des jobs sous forme de tableau :

| Colonne | Description |
|---------|-------------|
| Nom du Job | Identifiant unique du job |
| Statut | `PENDING`, `PROCESSING`, `DONE`, `ERROR`, `CANCELLED` |
| Fichiers | Nombre de fichiers dans le job |
| Planches | Nombre de planches générées |
| Date | Date de création |
| Actions | Bouton **Détails** pour voir le détail du job |

**Actions disponibles** :
- **Nouveau Job** : Crée un job manuellement via le dialogue de création.
- **Drag & Drop** : Glissez des fichiers/dossiers directement sur le tableau.
- **Clic droit** : Menu contextuel avec options Annuler / Reprendre / Voir les erreurs.
- **Recherche** : Filtrez les jobs par nom.
- **Filtre par statut** : Sélectionnez un statut spécifique.

### 2.3 Prévisualisation des Planches

Vue interactive pour inspecter les planches générées :

- **Zoom** : Molette de souris ou boutons `+` / `-`.
- **Pan** : Cliquez et maintenez pour déplacer la vue.
- **Ajuster** : Recentre la planche dans la fenêtre.
- **Navigation** : Boutons Précédent / Suivant pour parcourir les planches.
- **Export rapide** : Exporte la planche affichée en PDF.

### 2.4 Rapport Preflight

Lorsqu'un fichier présente des anomalies, le rapport Preflight s'affiche :

- **Arbre d'erreurs** : Structure hiérarchique par fichier → anomalie.
- **Panneau de détails** : Description complète et solution suggérée.
- **Actions** :
  - **Appliquer corrections auto** : Corrige toutes les anomalies automatiquement.
  - **Exporter Rapport** : Sauvegarde le rapport au format HTML.
  - **Ignorer et créer le Job** : Passe outre les avertissements.

### 2.5 Paramètres

L'écran de configuration est organisé en onglets :

| Onglet | Contenu |
|--------|---------|
| **Chemins** | Dossiers Input, Output, Archive, Logs |
| **Imposition** | Dimensions planche (largeur × hauteur), espacement, rotation |
| **Preflight** | DPI minimum, formats autorisés |
| **Export** | Format de sortie (PDF/TIFF/JPEG), résolution, profil ICC |
| **Utilisateurs** | Rôle de l'utilisateur actuel |
| **Performance** | Nombre de workers, limite mémoire |
| **Thème** | Basculer entre mode Clair et Sombre |

---

## 3. Procédures Opérateurs

### 3.1 Traitement Standard

1. Déposer les fichiers dans le Hot Folder ou créer un job manuellement.
2. Vérifier le statut sur le Tableau de Bord.
3. En cas d'erreur Preflight, corriger ou ignorer.
4. Récupérer les planches dans le dossier de sortie.
5. Vérifier le taux de remplissage (objectif : ≥ 75%).

### 3.2 Gestion des Erreurs

| Erreur | Action |
|--------|--------|
| DPI insuffisant | Le fichier est rééchantillonné automatiquement (si correction auto activée) |
| Mode couleur RGB | Converti en CMJN avec le profil ICC configuré |
| Fichier corrompu | Déplacé vers `/Error`, notification opérateur |
| Fond perdu manquant | Ajouté automatiquement (2-3mm configurable) |
| Transparence | Aplatie automatiquement lors de la correction |

### 3.3 Récupération après Crash

Si l'application s'arrête brutalement :
1. Relancez l'application.
2. Les jobs en état **PROCESSING** sont automatiquement détectés et repassés en **PENDING**.
3. Les fichiers dans le dossier `/Processing` sont recyclés.
4. Aucune intervention manuelle n'est nécessaire.

---

## 4. Raccourcis et Astuces

- **Glisser-déposer** : Fonctionne sur le tableau des jobs pour créer rapidement un job.
- **Barre de statut** : Affiche en permanence le job actif, la progression et la mémoire utilisée.
- **Notifications système** : Les alertes apparaissent dans la zone de notification Windows.
- **Thème sombre** : Recommandé pour le confort visuel en production prolongée.
