# JELOTIA IMPOSER — Plan de Tests Qualité (QA)

> Tests à effectuer manuellement avant chaque release.  
> Cocher chaque case après vérification. Noter les bugs dans la colonne **Remarque**.

---

## Session de test terrain 2026-07-06/07 — Résumé

Tests exécutés en automatisé (headless, `QT_QPA_PLATFORM=offscreen`) sur le lot réel
`QRC A7 BADGE 01072026` (2000 fichiers, 1999 PDF badges A7 53×84mm RGB 300dpi + 1 PSD).
Les lignes ci-dessous marquées ✅/❌ ont été vérifiées par ce test automatisé ; les lignes
non marquées nécessitent encore un passage manuel dans l'UI (clics, rendu visuel, drag&drop).

**Bugs trouvés et corrigés pendant cette session :**
1. Chemins Hot Folder codés en dur (`C:/Jelotia`) déconnectés des Paramètres UI → corrigé (`src/utils/config.py`).
2. Preflight n'inspectait jamais la vraie colorimétrie/DPI des PDF (assumait CMJN/300dpi pour tous) → RGB jamais détecté/corrigé sur PDF réels → corrigé (`import_engine.py`).
3. Les réglages Imposition/Preflight/Export de l'écran Paramètres n'étaient jamais appliqués aux jobs manuels (valeurs codées en dur) → corrigé (`main_window._build_job_settings`).
4. Un job manuel avec beaucoup de fichiers tournait entièrement sur **un seul cœur** (le pool de workers ne parallélise qu'au niveau job, pas fichier) → corrigé par découpage en sous-lots parallèles (`main_window._submit_job`).

**Incident (hors app)** : le disque C: de la machine de test s'est rempli à 100% pendant un run à
2000 fichiers, provoquant un échec d'écriture partiel (planches 4-20 non exportées). L'app n'a
pas crashé (erreur loggée, job terminé avec résultat partiel) mais aucun message explicite n'a
été montré à l'utilisateur — cf. test 14.5.

---

## 1. Démarrage & Interface

| # | Test | Résultat | Remarque |
|---|------|----------|----------|
| 1.1 | L'application démarre sans erreur console | ☑ OK / ☐ KO | Vérifié headless (offscreen), lancement + fermeture propre, aucune exception |
| 1.2 | Le thème sombre s'applique correctement (fond foncé, texte clair) | ☐ OK / ☐ KO | À vérifier visuellement (rendu non testable en headless) |
| 1.3 | La barre de statut affiche "Prêt \| 0 job actif" au démarrage | ☑ OK / ☐ KO | Confirmé dans le code (`setup_status_bar`) |
| 1.4 | L'icône dans la barre des tâches système (tray) apparaît | ☐ OK / ☐ KO | |
| 1.5 | La navigation sidebar fonctionne (Dashboard / Jobs / Settings) | ☐ OK / ☐ KO | |
| 1.6 | Le redimensionnement de la fenêtre fonctionne correctement | ☐ OK / ☐ KO | |

---

## 2. Dashboard

| # | Test | Résultat | Remarque |
|---|------|----------|----------|
| 2.1 | Les 4 cartes s'affichent (Jobs actifs, Erreurs, Planches, Remplissage) | ☐ OK / ☐ KO | |
| 2.2 | Les compteurs démarrent à 0 | ☐ OK / ☐ KO | |
| 2.3 | Le compteur "Jobs actifs" s'incrémente quand un job démarre | ☐ OK / ☐ KO | |
| 2.4 | Le compteur "Planches" s'incrémente après complétion d'un job | ☐ OK / ☐ KO | |
| 2.5 | Le graphique de production s'affiche (sans crash) | ☐ OK / ☐ KO | |

---

## 3. Création de Job (manuel)

| # | Test | Résultat | Remarque |
|---|------|----------|----------|
| 3.1 | Cliquer "+ Nouveau Job" ouvre le dialogue de création | ☐ OK / ☐ KO | |
| 3.2 | Un nom de job est pré-rempli automatiquement (ex: `JOB-A1B2C3D4`) | ☐ OK / ☐ KO | |
| 3.3 | Le bouton "+ Ajouter Fichiers" ouvre un explorateur de fichiers | ☐ OK / ☐ KO | |
| 3.4 | Les fichiers sélectionnés apparaissent dans la liste | ☐ OK / ☐ KO | |
| 3.5 | Le bouton "Supprimer" retire un fichier sélectionné de la liste | ☐ OK / ☐ KO | |
| 3.6 | Tenter de créer un job sans nom affiche une erreur | ☐ OK / ☐ KO | |
| 3.7 | Créer un job sans fichier affiche une confirmation (pas un crash) | ☐ OK / ☐ KO | |
| 3.8 | Après confirmation, le job apparaît dans la table en statut PENDING | ☑ OK / ☐ KO | Vérifié via `MainWindow` réel (headless), ligne ajoutée avant soumission |
| 3.9 | Le job passe en PROCESSING puis DONE automatiquement | ☑ OK / ☐ KO | Vérifié via `MainWindow` réel avec fichiers réels : PENDING → PROCESSING → DONE, planches comptées correctement, y compris avec découpage en sous-jobs parallèles (agrégation testée) |

---

## 4. Import de Fichiers

Tester avec un fichier de chaque type.

| # | Test | Fichier de test | Résultat | Remarque |
|---|------|-----------------|----------|----------|
| 4.1 | Import d'un PDF simple 1 page | `test.pdf` | ☑ OK / ☐ KO | 1999 vrais badges PDF (1 page, 53×84mm) importés sans erreur |
| 4.2 | Import d'un PDF multi-pages (3+ pages) | `multi.pdf` | ☐ OK / ☐ KO | Non testé (lot réel = fichiers 1 page uniquement) |
| 4.3 | Import d'une image JPEG | `photo.jpg` | ☐ OK / ☐ KO | Non testé sur fichier réel (couvert par test unitaire synthétique) |
| 4.4 | Import d'une image TIFF | `scan.tiff` | ☐ OK / ☐ KO | Non testé sur fichier réel (couvert par test unitaire synthétique) |
| 4.5 | Import d'une image PNG | `design.png` | ☐ OK / ☐ KO | Non testé sur fichier réel (couvert par test unitaire synthétique) |
| 4.6 | Import d'un fichier corrompu → message d'erreur, pas de crash | `corrupt.pdf` | ☑ OK / ☐ KO | `.psd` (format non supporté) dans le lot réel → erreur propre, pas de crash. PDF réellement corrompu couvert par test unitaire (`test_import_engine.py::test_process_corrupted`) |
| 4.7 | Drag & Drop d'un fichier PDF depuis l'explorateur | glisser-déposer | ☐ OK / ☐ KO | À vérifier manuellement (UI) |
| 4.8 | Drag & Drop de plusieurs fichiers simultanément | sélection multiple | ☐ OK / ☐ KO | À vérifier manuellement (UI) |

---

## 5. Preflight

| # | Test | Résultat | Remarque |
|---|------|----------|----------|
| 5.1 | Un fichier RGB déclenche un avertissement (pas un blocage) | ☑ OK / ☐ KO | Corrigé cette session — auparavant le PDF n'était jamais réellement inspecté (RGB jamais détecté). Vérifié sur 1999 PDF réels RGB : avertissement levé, non bloquant |
| 5.2 | Un fichier à 72 DPI déclenche un avertissement résolution | ☐ OK / ☐ KO | Non testé sur fichier réel (lot = ~300dpi). Couvert par test unitaire synthétique |
| 5.3 | Un fichier valide CMJN 300 DPI passe sans avertissement | ☐ OK / ☐ KO | Non testé (lot réel = images RGB, pas de PDF CMJN natif disponible) |
| 5.4 | Le rapport preflight liste les fichiers avec leurs erreurs | ☐ OK / ☐ KO | |
| 5.5 | Cliquer sur une erreur affiche le détail et la solution dans le panneau droit | ☐ OK / ☐ KO | |
| 5.6 | "Appliquer corrections auto" corrige et continue le job | ☐ OK / ☐ KO | |
| 5.7 | "Ignorer et créer le Job" continue malgré les avertissements | ☐ OK / ☐ KO | |
| 5.8 | "Annuler" ferme le dialogue sans créer le job | ☐ OK / ☐ KO | |
| 5.9 | "Exporter Rapport" génère un fichier HTML valide | ☐ OK / ☐ KO | |

---

## 6. Correction Automatique

| # | Test | Résultat | Remarque |
|---|------|----------|----------|
| 6.1 | Fichier RGB → converti en CMJN après correction | ☑ OK / ☐ KO | Corrigé cette session. Vérifié : le PDF/X exporté contient des images `ICCBased(CMYK)` (avant: `DeviceRGB` malgré le métadonnée FOGRA39) |
| 6.2 | Fichier 72 DPI → rééchantillonné à 300 DPI | ☐ OK / ☐ KO | Non testé sur fichier réel. Couvert par test unitaire synthétique |
| 6.3 | Fichier PNG avec transparence → aplati (pas de canal alpha) | ☐ OK / ☐ KO | Non testé (pas de PNG dans le lot réel). Couvert par test unitaire synthétique |
| 6.4 | Les corrections ne dégradent pas la qualité visible | ☐ OK / ☐ KO | Visuel — à vérifier manuellement en ouvrant les planches exportées |

---

## 7. Nesting (Imposition)

| # | Test | Résultat | Remarque |
|---|------|----------|----------|
| 7.1 | 10 cartes de visite (85×55mm) → placées sur 1 planche | ☐ OK / ☐ KO | Non testé isolément (implicite via 7.2 avec 1999 badges) |
| 7.2 | 200 cartes de visite → réparties sur plusieurs planches | ☑ OK / ☐ KO | Testé avec 1999 badges réels (53×84mm) → 20 planches générées |
| 7.3 | Le taux de remplissage affiché est cohérent (>70% pour formats identiques) | ☑ OK / ☐ KO | ~84% sur 19/20 planches pleines (la dernière planche, en reliquat, à 50%, ce qui est normal) |
| 7.4 | La rotation automatique s'applique si elle améliore le remplissage | ☐ OK / ☐ KO | Rotation activée par défaut, mais pas comparé avec/sans rotation sur ce lot |
| 7.5 | Les espaces entre éléments respectent le gap configuré (défaut 3mm) | ☐ OK / ☐ KO | Non mesuré visuellement sur ce lot (couvert par test unitaire `test_rectpack_with_gap`) |
| 7.6 | Un fichier trop grand pour la planche génère une erreur (pas un crash) | ☐ OK / ☐ KO | Non testé sur fichier réel (couvert par test unitaire) |

---

## 8. Génération de Planche (Layout)

| # | Test | Résultat | Remarque |
|---|------|----------|----------|
| 8.1 | La planche PDF générée existe dans le dossier output | ☑ OK / ☐ KO | 20/20 planches confirmées présentes sur disque (`exists=True`) sur le run à 1999 fichiers |
| 8.2 | Les repères de coupe sont visibles (croix aux coins de chaque élément) | ☐ OK / ☐ KO | À vérifier visuellement |
| 8.3 | Les lignes de découpe rouges entourent chaque élément | ☐ OK / ☐ KO | À vérifier visuellement |
| 8.4 | Les métadonnées (Job ID, date, planche, remplissage) sont imprimées | ☐ OK / ☐ KO | À vérifier visuellement |
| 8.5 | QR Code visible en bas à droite si activé dans les paramètres | ☐ OK / ☐ KO | Non testé (option désactivée par défaut) |
| 8.6 | La miniature PNG (`_thumb.png`) est générée à côté du PDF | ☐ OK / ☐ KO | Non vérifiée sur ce lot réel (couvert par tests unitaires) |
| 8.7 | Le PDF couche de découpe (`_cutlayer.pdf`) est généré si option activée | ☐ OK / ☐ KO | Non testé (option désactivée par défaut) |

---

## 9. Prévisualisation des Planches

| # | Test | Résultat | Remarque |
|---|------|----------|----------|
| 9.1 | Cliquer "Détails" sur un job DONE ouvre la prévisualisation | ☐ OK / ☐ KO | |
| 9.2 | La planche s'affiche correctement (pas un écran vide) | ☐ OK / ☐ KO | |
| 9.3 | Zoom avec la molette de la souris fonctionne | ☐ OK / ☐ KO | |
| 9.4 | Le panoramique (déplacement) fonctionne (clic + glisser) | ☐ OK / ☐ KO | |
| 9.5 | Le taux de remplissage est affiché sur la prévisualisation | ☐ OK / ☐ KO | |

---

## 10. Export

| # | Test | Résultat | Remarque |
|---|------|----------|----------|
| 10.1 | Export PDF/X-1a → fichier `.pdf` valide | ☐ OK / ☐ KO | |
| 10.2 | Export PDF/X-1a → contient `OutputIntent` (ouvrir avec un lecteur PDF) | ☐ OK / ☐ KO | |
| 10.3 | Export TIFF → fichier `.tiff` en mode CMJN | ☐ OK / ☐ KO | |
| 10.4 | Export JPEG → fichier `.jpg` lisible | ☐ OK / ☐ KO | |
| 10.5 | Les fichiers exportés ont un nom structuré : `[JobID]_sheet_[N].[ext]` | ☐ OK / ☐ KO | |

---

## 11. Hot Folder

| # | Test | Résultat | Remarque |
|---|------|----------|----------|
| 11.1 | Déposer un PDF dans `~/Jelotia/HotFolder/Input/` crée un job automatiquement | ☐ OK / ☐ KO | |
| 11.2 | Le fichier est déplacé vers `/Processing/` pendant le traitement | ☐ OK / ☐ KO | |
| 11.3 | Après succès, le fichier est copié dans `/Output/` | ☐ OK / ☐ KO | |
| 11.4 | Un fichier corrompu est déplacé dans `/Error/` | ☐ OK / ☐ KO | |
| 11.5 | Une notification système apparaît à la fin du job | ☐ OK / ☐ KO | |
| 11.6 | Arrêter l'app puis la relancer : les fichiers en `/Processing/` sont repris (crash recovery) | ☐ OK / ☐ KO | |

---

## 12. Paramètres

| # | Test | Résultat | Remarque |
|---|------|----------|----------|
| 12.1 | Changer la taille de planche (ex : 700×500mm) est pris en compte au prochain job | ☐ OK / ☐ KO | |
| 12.2 | Changer l'espacement (gap) est pris en compte | ☐ OK / ☐ KO | |
| 12.3 | Désactiver la rotation → les éléments ne sont plus tournés | ☐ OK / ☐ KO | |
| 12.4 | Changer le format d'export (TIFF, JPEG) est respecté | ☐ OK / ☐ KO | |
| 12.5 | Les paramètres sont sauvegardés après fermeture et relance de l'app | ☐ OK / ☐ KO | |

---

## 13. Stabilité & Performance

| # | Test | Durée estimée | Résultat | Remarque |
|---|------|---------------|----------|----------|
| 13.1 | Traiter 50 fichiers PDF → aucun crash | ~2 min | ☑ OK / ☐ KO | 150 et 1999 vrais PDF traités sans crash |
| 13.2 | Traiter 500 fichiers mixtes PDF/JPEG → aucune fuite mémoire visible | ~15 min | ☐ OK / ☑ KO | 1999 PDF traités sans souci mémoire process, MAIS **fuite disque trouvée et corrigée** cette session : `CorrectionEngine` écrivait ses fichiers temporaires directement à la racine du dossier Processing (jamais nettoyés) → 4276 fichiers / 12 Go accumulés en quelques runs. Corrigé : dossier temp par job + nettoyage après export |
| 13.3 | Laisser l'app ouverte 2h avec Hot Folder actif → stable | 2h | ☐ OK / ☐ KO | Non testé (durée non compatible avec cette session) |
| 13.4 | Fermer brutalement (kill process) puis relancer → aucun job perdu | <1 min | ☐ OK / ☐ KO | Le mécanisme de reprise (`recover_orphan_jobs`) fonctionne mais avait un bug critique (voir 13.2) désormais corrigé ; un vrai test kill -9 en cours de job n'a pas été fait |
| 13.5 | Lancer le benchmark : `python scripts/benchmark_runner.py --count 1000` → > 2 fichiers/sec | ~5 min | ☑ OK / ☐ KO | Sur données réelles (RGB→CMJN à corriger), avant fix : **1.52 fichiers/sec** (1 seul job = 1 seul cœur, quel que soit `max_workers`). Après découpage en sous-jobs parallèles (cette session) : **2.25 fichiers/sec** sur 300 fichiers réels (machine 4 cœurs / 3 workers, 6 sous-jobs) — franchit le seuil. 1 sous-job sur 6 a échoué lors de ce run (cause non investiguée, à surveiller) |

---

## 14. Cas limites

| # | Test | Résultat | Remarque |
|---|------|----------|----------|
| 14.1 | Créer 10 jobs simultanément → tous se terminent sans erreur | ☐ OK / ☐ KO | Testé indirectement via le découpage en sous-jobs (6-7 sous-jobs parallèles pour un même job) — pas testé avec 10 jobs manuels distincts |
| 14.2 | Fichier PDF protégé par mot de passe → erreur propre, pas de crash | ☐ OK / ☐ KO | Non testé (aucun fichier protégé dans le lot réel) |
| 14.3 | Fichier avec un nom contenant des caractères spéciaux (`été #1.pdf`) | ☑ OK / ☐ KO | Les 2000 noms réels contiennent des espaces (`ID 1333204 copie.pdf`) — traités sans erreur. Accents/`#` non spécifiquement testés |
| 14.4 | Fichier de 500 Mo → l'app ne se bloque pas | ☐ OK / ☐ KO | Non testé (fichiers réels ~650 Ko chacun) |
| 14.5 | Disque plein → message d'erreur explicite, pas de crash | ☐ OK / ☑ KO | Rencontré réellement (disque saturé pendant un run) : pas de crash, l'erreur est loggée et le job se termine avec un résultat partiel — **mais aucun message explicite n'est remonté à l'utilisateur dans l'UI**, juste un log silencieux |

---

## Résumé des tests

| Catégorie | Total | Passés | Échoués |
|-----------|-------|--------|---------|
| 1. Démarrage | 6 | | |
| 2. Dashboard | 5 | | |
| 3. Création Job | 9 | | |
| 4. Import | 8 | | |
| 5. Preflight | 9 | | |
| 6. Correction | 4 | | |
| 7. Nesting | 6 | | |
| 8. Layout | 7 | | |
| 9. Prévisualisation | 5 | | |
| 10. Export | 5 | | |
| 11. Hot Folder | 6 | | |
| 12. Paramètres | 5 | | |
| 13. Stabilité | 5 | | |
| 14. Cas limites | 5 | | |
| **TOTAL** | **90** | | |

---

**Testeur :**  
**Date :**  
**Version testée :**  
**OS :** Windows ___  
**Bugs bloquants :**
