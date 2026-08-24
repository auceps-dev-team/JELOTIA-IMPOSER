# AUDIT COMPLET — JELOTIA IMPOSER

**Dépôt** : `auceps-dev-team/JELOTIA-IMPOSER` · branche `arena/01a03314-jelotia-imposer` (issue de `phase-0-setup`, commit `356d51b`)
**Date de l'audit** : 24 août 2026
**Périmètre** : 100 % du dépôt — 238 fichiers, **21 651 LOC Python** (hors tests : 16 115 ; tests : 5 536), 5 documents `docs/`, 5 notes `memory-bank/`, l'installeur, le serveur d'activation et les maquettes HTML.
**Méthode** : lecture intégrale ou par plages de **tous** les modules Python, exécution réelle de la suite de tests, de la couverture et du linter dans un environnement dédié (`/tmp/venv`, PySide6 6.11.2, `QT_QPA_PLATFORM=offscreen`), **vérification empirique** des bugs suspectés (reproduction en exécution, pas en lecture), analyse du graphe d'imports et traçabilité clé-par-clé des réglages de configuration.

**Carte mentale associée** : [`docs/audit/carte_mentale.svg`](carte_mentale.svg) (source vectorielle) et [`carte_mentale.png`](carte_mentale.png). Générateur reproductible : `python tools/generate_mindmap.py`.

> ### ⚠️ Révision 2 — après contre-audit indépendant
>
> Cet audit a été soumis à un contre-audit exécuté sur `phase-0-setup · cd25933 · v1.39.0` (Windows 11, profils ICC présents, groupe `server` installé). **20 des 21 points majeurs ont été confirmés**, dont les plus graves. Quatre corrections ont été intégrées ci-dessous et sont signalées par le marqueur **[R2]** :
>
> | # | Nature | Correction apportée |
> |---|---|---|
> | **C2** | **Erreur technique de l'audit** | Le correctif que je proposais pour les polices (`type == "n/a"`) **ne détecte rien** : c'est `ext`, index **1**, qui vaut `n/a` — pas `type`, index 2. Rejoué et confirmé sur deux PDF réels (§4.2). Le diagnostic restait juste, le remède aurait reproduit exactement le bug dénoncé en C1. |
> | **§10 🟡** | **Affirmation fausse** | L'OutputIntent « FOGRA39 en dur » n'existe pas : `_output_condition()` dérive la condition du profil réellement utilisé, et FOGRA39 n'est plus qu'un repli en l'absence de profil. Point retiré. |
> | **§10 🟡** | **Sur-comptage** | 11 `print()` annoncés → **7** dans `src/`, plus 8 dans `activation_server/`. Mon compte incluait un faux positif (`…fingerprint(`). |
> | **M4** | **Cause racine ajoutée** | `scripts/bump_version.py` n'écrit **jamais** `src/_version.py` (vérifié : il ne touche que `pyproject.toml`, l'`.iss` et `uv.lock`). Aligner les versions à la main est donc inutile — elles redivergeront au prochain bump. |
>
> Deux écarts de mesure s'expliquent par la différence de commit et d'environnement, sans invalider le fond : les compteurs de tests et de lint (§5.1, §6.2) et le nombre de versions divergentes (§6.3), détaillés sur place.
>
> Un lien que je n'avais pas fait est repris du contre-audit et intégré : **M8 + M13 se combinent en perte de données réelle**, ce qui fait remonter M8 en Sprint 1 (§10, §11).

---

## 1. Synthèse pour décideur

Jelotia Imposer est un **logiciel de pré-presse industriel sérieux et fonctionnellement abouti** : le pipeline hot folder → preflight → correction ICC → nesting 2D → imposition → export RIP existe réellement, il est cohérent de bout en bout, et il porte des choix d'ingénierie de qualité (séparation domaine Pydantic / ORM SQLAlchemy, gestion ICC réelle via littleCMS, reprise sur incident persistée en base, commentaires expliquant systématiquement les décisions non évidentes). Ce n'est pas une maquette.

Mais le projet souffre d'un **décalage important entre ce qu'il affirme être et ce qui est vérifiable**, et de **quatre défauts de qualité fonctionnelle prouvés en exécution** qui touchent le cœur de la promesse commerciale (« Précision Zéro Défaut »).

| Axe | Note | Commentaire |
|---|:--:|---|
| Architecture & découpage | **A−** | Couches nettes, graphe d'imports acyclique, domaine découplé de l'ORM et de Qt |
| Qualité fonctionnelle du cœur métier | **C+** | Pipeline réel et solide, mais preflight partiellement inopérant (2 des 6 axes annoncés) |
| Couverture & fiabilité des tests | **D** | ~32 % réels contre 85 % annoncés ; **0 test d'interface** ; chaîne ICC/CMJN jamais validée |
| Industrialisation (CI/CD, lint, versions) | **F** | Aucun pipeline, 123 erreurs de lint, 3 numéros de version divergents |
| Sécurité & licences | **C** | Ed25519 correct sur le principe, mais vérification 100 % locale et gating incomplet |
| Persistance & montée en charge | **C−** | Schéma propre mais **aucun index**, deux systèmes de migration concurrents |
| Réactivité de l'interface | **C** | 3 chemins d'exécution bloquent le thread UI, contredisant « sans aucun blocage d'interface » |
| Documentation | **B** | Riche et soignée, mais partiellement désynchronisée du code |

**Verdict** : produit **utilisable en production sous surveillance**, **non prêt** pour une diffusion large ou une montée en charge sans traitement du plan d'action §10. Le risque dominant n'est pas l'architecture — elle est saine — mais **l'absence de filet de sécurité** (pas de CI, pas de tests d'interface, couverture réelle faible) sur une base de 21 651 lignes qui continue d'évoluer.

---

## 2. Ce que fait le produit

Chaîne de production automatisée pour imprimerie numérique / grand format (contexte : JELOTIA SARL, Abidjan) :

```
Dépôt fichier         Hot folder (watchdog)         Regroupement par gamme
   ────────────►   HotFolderMonitor + stabilisation   ────►   AutoProcessor
                                                                    │
   ┌────────────────────────────────────────────────────────────────┘
   ▼
JobProcessor ──► ImportEngine ──► PreflightEngine ──► CorrectionEngine (ICC/bleed/DPI)
                                                              │
                                                              ▼
                                      NestingEngine (MaxRects / Guillotine / grille)
                                                              │
                                                              ▼
                                      LayoutEngine (reportlab : repères ARMS, CutContour, filigrane)
                                                              │
                                                              ▼
                          ExportEngine ──► PDF/X-1a · PDF/X-4 · PDF · TIFF LZW/RAW · JPEG 95 % · JDF Lite XML
                                                              │
                                                              ▼
                          OutputManager (archivage ZIP daté YYYY/MM/DD + purge) · SQLite (reprise)
```

Modules périphériques : éditeur PDF intégré (undo borné), générateur QR / badges avec lots depuis tableur, ganging multi-commandes, règles de surveillance par dossier, rapports XLSX, serveur d'activation FastAPI.

---

## 3. Cartographie du code

### 3.1 Volumétrie

| Zone | LOC | Fichiers | Observation |
|---|---:|---:|---|
| `src/ui/widgets/` | 6 973 | 17 | Le plus gros bloc du projet, **0 test** |
| `src/core/engines/` | 3 601 | 15 | Cœur algorithmique |
| `src/core/` (services) | 1 452 | 11 | Orchestration |
| `src/ui/` (racine) | 1 294 | 2 | `main_window.py` 1 003 l. + `theme.py` |
| `src/database/` | 562 | 4+2 migrations | SQLAlchemy + Alembic |
| `scripts/` | 509 | 4 | Hors pytest |
| `src/core/processors/` | 469 | 2 | Pool de workers |
| `activation_server/` | 435 | 4 | FastAPI, **0 % couvert** |
| `src/utils/` | 245 | 4 | dont `file_utils.py` **vide** |
| `tests/` | 5 536 | 27 | 25 unitaires + 2 intégration |

Cinq fichiers dépassent 700 lignes : `pdf_editor_view.py` (1 070), `main_window.py` (1 003), `qr_template_designer.py` (708), et deux widgets QR. Ce sont les candidats naturels au découpage.

### 3.2 Qualité structurelle — les points forts réels

Ces points méritent d'être protégés lors de tout refactoring :

- **Séparation domaine / persistance / présentation** : `src/core/models/domain.py` (Pydantic v2) est indépendant de `src/database/models.py` (SQLAlchemy). Le domaine ne connaît ni la base ni Qt.
- **Aucun `QMessageBox` dans `src/core/`** — vérifié par grep exhaustif. Le métier ne pilote jamais l'interface ; discipline rare et précieuse.
- **Graphe d'imports de `src/ui/**` strictement descendant et acyclique** — vérifié par analyse AST. Seuls `common.py` et `job_dialog.py` sont mutualisés entre widgets.
- **Zéro erreur de syntaxe** sur 21 651 lignes (`py_compile` sur l'intégralité du dépôt), et le code compile même sous Python 3.11 alors que `pyproject.toml` exige 3.12.
- **Commentaires justificatifs** : le code explique les décisions non évidentes plutôt que de paraphraser l'instruction. Exemples : le `multiprocessing.freeze_support()` de `main.py` documente précisément le bug historique (chaque worker rouvrait une fenêtre GUI au lieu d'exécuter le job) ; `worker_pool.py` justifie le découpage en chunks ; `pdf_editor.py` explique les sémantiques de `fitz` et la dérotation.
- **Mécanismes de reprise pensés** : `create_job_stub` en upsert, `quantities` persistées, `_persist_sheet_sources` exécuté **avant** la purge du répertoire temporaire, `rule_id` propagé du hot folder jusqu'au job pour ne jamais fusionner des fichiers de gammes différentes.
- **`SheetExportService`** avec `MissingArtworkError` : refuse d'exporter une planche dont les visuels ont disparu plutôt que de produire un fichier silencieusement faux.
- **`gang_signature`** calculée sur les paramètres physiques réels — deux commandes ne sont amalgamées que si leur production est effectivement identique.
- **ICC réel** : `icc_engine.py` s'appuie sur littleCMS via Pillow, pas sur une conversion RGB→CMJN approximative.

---

## 4. Défauts fonctionnels prouvés en exécution

Ces quatre points ont été **reproduits**, pas déduits d'une lecture.

### 4.1 🔴 CRITIQUE — La détection de transparence ne fonctionne pas, et produit des faux positifs sur tout fichier CMJN

`src/core/engines/preflight_engine.py`, méthode `_analyze_pdf_deep` :

```python
if img_dict.get("colorspace") == 4 or "alpha" in img_dict:
    # → TRANSPARENCY_DETECTED
```

**Vérification empirique** : un PDF contenant une image RGBA a été généré, puis inspecté avec PyMuPDF. Le dictionnaire retourné par `extract_image()` expose l'alpha sous la clé **`smask`** — jamais `alpha`. La clé testée n'existe donc dans aucun cas.

Par ailleurs, `colorspace == 4` désigne **4 composantes, c'est-à-dire CMJN** — pas la transparence. Un fichier CMJN parfaitement conforme, c'est-à-dire précisément le fichier attendu en production, est donc signalé comme transparent.

**Double conséquence** :
1. Aucune transparence n'est jamais détectée → la promesse « Preflight 6 Axes » du README n'en couvre en réalité que 4.
2. Tout fichier CMJN déclenche un avertissement erroné → l'opérateur apprend à ignorer les alertes du preflight, ce qui neutralise l'outil entier.

**Aggravant** : `preflight_engine.py` affiche **100 % de couverture**. Les tests `test_preflight_pdf_with_transparency` et `test_preflight_pdf_no_transparency` construisent un `MagicMock` retournant `{"colorspace": 3, "alpha": True}` — un dictionnaire que PyMuPDF ne produit jamais. **Le test valide la croyance du développeur, pas le comportement de la bibliothèque.** C'est l'illustration la plus nette du risque des tests intégralement mockés.

**Correctif** :
```python
has_alpha = bool(img_dict.get("smask")) or img_dict.get("alpha") in (True, 1)
if has_alpha:
    # → TRANSPARENCY_DETECTED
```
et supprimer complètement la condition `colorspace == 4`. Le test doit être réécrit sur un **PDF RGBA réel** généré à la volée, pas sur un mock.

### 4.2 🔴 CRITIQUE — Le contrôle des polices embarquées est un stub **[R2 — correctif rectifié]**

`preflight_engine.py`, lignes 107-116 :

```python
for font in page.get_fonts():
    # commentaire admettant explicitement que le contrôle n'est pas implémenté
    pass
```

Le cinquième axe annoncé du preflight (« polices embarquées ») n'existe pas. Un fichier dont la police n'est pas embarquée passe le contrôle et sera substitué par le RIP — cause classique de réimpression.

Sur les 6 axes annoncés (résolution, mode couleur, transparence, polices, dimensions, fond perdu), **2 sont inopérants et 1 génère de faux positifs**.

> **[R2] Correction d'une erreur de la première version de cet audit.** J'écrivais que « `page.get_fonts()` retourne des tuples dont l'élément **`type`** vaut `"n/a"` pour une police non embarquée ». **C'est faux, et le contre-audit a eu raison de le relever.** C'est `ext` (**index 1**) qui vaut `n/a` ; `type` (index 2) vaut toujours `Type1`, `Type0`, `TrueType`… Implémenter le correctif tel que je l'avais écrit aurait produit un contrôle qui **ne se déclenche jamais** — c'est-à-dire la faute exacte dénoncée en §4.1, et tout aussi invisible en test.

**Vérification** (deux PDF générés à la volée : une base-14 non embarquée, une TTF DejaVu réellement embarquée) :

```
tuple = (xref, ext, type, basefont, name, encoding, referencer)

NON embarquée  (5, 'n/a', 'Type1', 'Helvetica',        'helv', 'WinAnsiEncoding')
EMBARQUÉE      (5, 'ttf', 'Type0', 'DejaVu Sans Book', 'F0',   'Identity-H')

test erroné (v1)   type == 'n/a'  ->  False / False   ← ne discrimine RIEN
test correct       ext  == 'n/a'  ->  True  / False   ← discrimine bien
```

Détail aggravant pour la version 1 de cet audit : **le commentaire déjà présent dans le code donne le bon ordre des champs** (`# font is a tuple: (xref, ext, type, basefont, name, encoding)`). L'information était sous les yeux ; je ne l'avais pas rejouée en exécution, contrairement à ce que j'avais fait pour C1. C'est précisément le manquement que je reproche au test de transparence.

**Correctif — vérifié** :
```python
for font in page.get_fonts(full=False):
    if font[1] == "n/a":        # index 1 = ext ; "n/a" ⇒ police NON embarquée
        # → FONT_NOT_EMBEDDED, en citant font[3] (basefont)
```
Le test doit être écrit sur **deux PDF réels** (une police embarquée, une non embarquée), jamais sur un mock.

### 4.3 🔴 CRITIQUE — `ConfigManager` corrompt sa propre configuration par défaut

`src/utils/config_manager.py` copie `DEFAULT_CONFIG` avec un `.copy()` **superficiel**. Les sous-dictionnaires (`imposition`, `paths`, `output`…) restent partagés avec la constante de module.

**Vérification empirique** : après un simple `ConfigManager().set("imposition", <clé>, <valeur>)`, un test d'identité (`is`) confirme que `DEFAULT_CONFIG["imposition"]` a été muté en mémoire.

**Conséquence** : le mécanisme de repli sur les valeurs par défaut est détruit dès la première écriture. Une configuration corrompue ou un `config.json` supprimé ne restaure pas les réglages d'usine mais les derniers réglages saisis. En cas de crash suivi d'un redémarrage, le comportement devient non déterministe.

**Correctif** : `copy.deepcopy(DEFAULT_CONFIG)`. Une ligne.

### 4.4 🟠 MAJEUR — Le hot folder ignore les fichiers déjà présents au démarrage

`src/core/hot_folder_monitor.py` s'appuie exclusivement sur les **événements** `watchdog`. Aucun balayage initial n'est effectué dans `start()`.

**Scénario réel** : l'application est fermée le soir (mise à jour, redémarrage Windows, coupure). Des fichiers sont déposés dans le hot folder pendant la nuit par un client ou un script. Au lancement du matin, **ces fichiers ne sont jamais traités** — ils restent indéfiniment dans le dossier d'entrée, invisibles, jusqu'à ce que quelqu'un les déplace manuellement.

Seul `main_window.recover_orphan_jobs()` (ligne 912) balaie le répertoire `Processing/`, c'est-à-dire uniquement les fichiers **déjà déplacés** par un monitor actif — et il le fait sans `rule_id`, donc en perdant la gamme d'origine et en appliquant les réglages globaux.

Pour un produit vendu sur l'automatisation « 24/7 », c'est un défaut de conception majeur.

**Correctif** : ajouter un scan initial dans `HotFolderMonitor.start()` qui injecte les fichiers existants dans le même circuit de stabilisation, avec le `rule_id` du monitor.

---

## 5. Tests et couverture — l'écart le plus préoccupant

### 5.1 Résultats mesurés

```
$ QT_QPA_PLATFORM=offscreen pytest tests/ -q
285 passed, 1 failed, 12 skipped  (~22 s)
```

**Échec unique** — `test_licensing.py::test_bundled_path_only_exists_in_frozen_build:258` : le test monkeypatche `sys.frozen` et attend un `WindowsPath`. Il n'est pas portable hors Windows. Défaut de test, pas défaut de produit — mais il **rend la suite rouge par défaut sur toute machine non-Windows**, ce qui décourage son exécution.

> **[R2] Ces trois chiffres dépendent de la machine, et c'est le point le plus important de ce paragraphe.** Le contre-audit, exécuté sous Windows 11 avec les profils ICC installés et le groupe `server`, obtient **313 passés, 0 échec, 0 skip**. Il n'y a pas contradiction : ma mesure a été faite sous Linux, sans profil CMJN ni `fastapi`. La conclusion en sort **renforcée** plutôt qu'affaiblie — ces tests **se taisent silencieusement là où les profils manquent, c'est-à-dire exactement la configuration d'un runner de CI vierge**. Créer la CI sans embarquer un profil ICC dans `tests/fixtures/` produirait une CI verte qui ne teste ni la conversion colorimétrique ni l'export PDF/X. C'est la raison d'être du point 11 du plan d'action.

**12 tests skippés, tous environnementaux et tous sur des zones à risque** :
- `test_icc_engine` ×7 et `test_export_engine` ×4 : skippés faute de profil ICC CMJN sur la machine. **La conversion colorimétrique et l'export PDF/X — c'est-à-dire ce que l'imprimeur reçoit réellement — ne sont validés par aucun test qui s'exécute effectivement.**
- `test_activation_server` ×1 : `fastapi` non installé (groupe `server` optionnel). Le serveur de licences n'est jamais testé.

Un skip silencieux sur une zone critique est plus dangereux qu'une absence de test : il donne l'illusion d'une couverture.

### 5.2 La couverture réelle est d'environ 32 %, pas 85 %

| Mesure | Valeur |
|---|---|
| Annoncé au README | **85 %** |
| Mesuré sur le périmètre non-UI (3 711 instructions) | **76 %** |
| `src/ui/**` | **5 233 instructions, 0 test** (aucun fichier de test ne référence `src.ui`) |
| **Couverture réelle sur l'ensemble du code applicatif** | **≈ 32 %** |

Il n'existe **ni section `[tool.coverage]` dans `pyproject.toml`, ni seuil `fail_under`**. La mesure n'est donc ni configurée ni contraignante.

**Modules à 0 %** : `activation_server/*`, `output_manager.py`, `worker_thread.py`, `system_notifier.py`, `utils/logger.py`.
**Modules faibles** : `auto_processor.py` 30 %, `hot_folder_monitor.py` 50 %, `config_manager.py` 56 % — soit exactement les modules où se trouvent les bugs §4.3 et §4.4.
**Modules à 100 %** : `domain.py`, `reporting.py`, `preflight_engine.py`, `photoshop_tiff.py`, `sheet_export_service.py`. Le cas de `preflight_engine.py` (§4.1) montre que ce chiffre ne garantit rien à lui seul.

### 5.3 Nature des tests

Sur 27 fichiers de test, **seuls 7 décorateurs `@patch`** au total, concentrés dans `test_preflight_engine.py` et `test_nesting_engine.py`. La grande majorité des tests travaille donc sur des objets réels — c'est une **bonne pratique**, et elle explique la solidité des moteurs de nesting, de layout et de QR.

L'ironie est que le seul module massivement mocké (`preflight_engine`) est précisément celui qui contient le bug le plus grave, invisible du fait du mock.

Les deux tests d'intégration (`test_end_to_end.py`, `test_hot_folder.py`) sont de bonne facture : ils génèrent de vrais PDF/JPEG avec PyMuPDF et Pillow et redirigent la configuration vers `tmp_path`. Aucun `tests/conftest.py` n'existe cependant, ce qui provoque la duplication de la fixture `temp_dirs` entre les deux fichiers.

### 5.4 Ce que dit le pilotage interne

`memory-bank/progress.md`, Phase 6 (« Tests, QA, performances ») : **14 cases à cocher, aucune n'est cochée.** L'équipe sait donc que cette phase n'a pas été menée. Le README, lui, annonce 85 % de couverture. **L'incohérence n'est pas dans le code, elle est dans la communication.**

---

## 6. Industrialisation — le maillon manquant

### 6.1 Aucune intégration continue

`ls -R .github` → **le répertoire n'existe pas**. Pas de workflow, pas de lint automatique, pas de test au push, pas de build vérifié, pas de politique de branche. Sur un projet de 21 651 lignes livré en binaire à des clients, c'est la lacune structurante : rien n'empêche mécaniquement une régression d'atteindre l'installeur.

### 6.2 Lint : 123 erreurs, alors que le README affirme le contraire

```
$ ruff check .          # configuration du projet : E, F, I — line-length 100
125  E501  line-too-long        (95 hors outillage d'audit)
 12  F401  unused-import
  7  E701  multiple-statements-on-one-line
  5  I001  unsorted-imports
  3  E722  bare-except
  1  F541  f-string-missing-placeholders
Found 123 errors (périmètre applicatif)
```

> **[R2]** Le contre-audit relève **160 erreurs** au lieu de 123 : l'écart provient d'un dossier `scratch/` présent sur son poste et non exclu par la configuration ruff. Cela ajoute au passage un constat mineur — **`[tool.ruff] exclude` n'est pas configuré**, si bien que tout répertoire de travail local pollue la mesure de lint. À fixer en même temps que la CI, sans quoi le seuil d'échec sera ingérable.

Avec un jeu de règles étendu (13 familles), le total atteint **1 348**, dont hors `assert` de test : `T201` (print) ×46, `S110` (`except: pass`) ×9, `UP006` ×141 et `UP045` ×102 (annotations de type au style pré-3.9/3.10 alors que le projet cible 3.12), `RUF013` ×6 (`Optional` implicite), `B904` ×2 (perte du contexte d'exception), `RUF006` ×3 (tâche asyncio sans référence retenue → risque de collecte prématurée).

`mypy` est configuré en mode **`strict = true`** dans `pyproject.toml`, mais n'est pas installé dans l'environnement de développement et n'est exécuté nulle part. Une configuration stricte jamais lancée est un faux signal de rigueur.

### 6.3 Trois numéros de version divergents

| Source | Version |
|---|---|
| `src/_version.py` (embarqué dans le binaire PyInstaller) | **1.37.1** |
| `pyproject.toml`, `README.md`, `installer/jelotia_imposer.iss` | **1.38.0** |
| `docs/*.md` (les 5 documents) | **1.5.1** |

Conséquence concrète : la fenêtre « Info Système » affichera 1.37.1 alors que le programme d'installation aura enregistré 1.38.0 dans `HKLM\SOFTWARE\Jelotia\Imposer\Version` — le support client ne peut pas identifier de façon fiable la version installée.

> **[R2] Cause racine, que la version 1 de cet audit n'identifiait pas.** J'attribuais la dérive à un oubli d'exécution de `scripts/bump_version.py`. C'est plus grave : **le script est structurellement incapable de synchroniser `src/_version.py`**. Vérification de ses cibles d'écriture — `write_pyproject()`, `write_installer()`, `sync_lockfile()` — **aucune ne touche `_version.py` ni le README**, alors que `_version.py` porte l'en-tête « *Updated by scripts/bump_version.py* ». Le fichier ment sur son propre mode de mise à jour.
>
> Le contre-audit compte d'ailleurs **quatre** versions en circulation à son commit (`_version.py` 1.37.1, `pyproject`/`.iss` 1.39.0, README 1.38.0, docs 1.5.1) contre trois au mien : la dérive **s'aggrave à chaque incrément**, ce qui est la signature d'un défaut d'outillage et non d'un oubli ponctuel.
>
> **Conséquence sur le plan d'action** : aligner les fichiers à la main (point 5 du Sprint 1) est un geste sans valeur tant que le script n'est pas corrigé. Il faut **d'abord** étendre `bump_version.py` à `_version.py` et au README, **puis** rejouer un bump.

### 6.4 Contenu versionné inapproprié

- **`.coverage`** (artefact binaire de mesure) est suivi par Git.
- **102 fichiers PDF** de `integration_test_data/` (`stress_0.pdf` … `stress_99.pdf`, `healthy.pdf`, `corrupt.pdf`) sont versionnés, plus `test_planche.pdf` à la racine. Ils devraient être **générés à la volée** — c'est déjà ce que fait `test_end_to_end.py`, la logique existe donc dans le dépôt.
- `scripts/integration_tests.py` et `scripts/benchmark_runner.py` sont des scripts autonomes hors de pytest : ils ne seront jamais exécutés par une future CI.

### 6.5 Dépendances déclarées mais jamais importées

Cinq dépendances de `pyproject.toml` n'apparaissent dans **aucun** `import` du dépôt :

| Dépendance | Poids | Statut |
|---|---|---|
| `opencv-python` | ~60 Mo | **0 import** |
| `colour-science` | lourd | **0 import** |
| `pyqtgraph` | moyen | **0 import** — alors que `dashboard.py` dessine son graphique 7 jours à la main |
| `colorama` | léger | **0 import** |
| `shapely` | moyen | **0 import** |

Elles alourdissent inutilement `uv sync` et, potentiellement, le paquet PyInstaller. `opencv-python` à lui seul peut représenter plusieurs dizaines de mégaoctets dans l'installeur final.

---

## 7. Persistance et montée en charge

**Schéma** (`src/database/models.py`) : 4 tables — `jobs` (colonnes JSON `settings`, `stats`, `source_paths`, `quantities`, indicateur `archived`), `file_items`, `sheets`, `qr_batches`.

### 7.1 🟠 Aucun index, pas même sur les clés étrangères

Aucune colonne du schéma ne porte `index=True`, y compris les `job_id` des tables filles. Chaque chargement de l'historique, chaque `_refresh_dashboard()` et chaque restauration de planche déclenche un balayage complet de table. Sur les volumes revendiqués (10 000 fichiers/jour), la base atteint plusieurs centaines de milliers de lignes en quelques mois et l'interface se dégradera de façon continue et difficile à diagnostiquer.

**Correctif** : `index=True` sur toutes les FK, plus un index sur `jobs.created_at` et `jobs.archived` (colonnes de filtrage du tableau de bord). Coût : quelques lignes et une migration.

### 7.2 🟠 Deux systèmes de migration concurrents et désynchronisés

`repository.py::_migrate_schema()` (lignes 18-70) exécute des `ALTER TABLE` manuels pour ajouter `archived` et `quantities` **au démarrage de l'application**. En parallèle, Alembic est configuré (`alembic.ini`) avec deux révisions seulement — `1e7d7ef6f9e7_initial_migration` → `4bd7b704394b_add_job_source_paths` — **qui ne connaissent ni `archived` ni `quantities`**.

Le head Alembic est donc **en retard sur le modèle ORM**. Un `alembic upgrade head` sur une base neuve, tel que le README l'indique en étape 3 du démarrage rapide, produit un schéma incomplet — que `_migrate_schema()` rattrapera silencieusement au premier lancement. Le jour où une migration Alembic touchera ces tables, le conflit sera difficile à diagnostiquer.

**Correctif** : générer une révision Alembic rattrapant les deux colonnes, puis supprimer `_migrate_schema()`. Un seul système fait autorité.

### 7.3 Autres points

- `create_engine(db_url)` sans `check_same_thread=False` ni réglage de pool, alors que l'application est multi-threadée (`WorkerPoolThread`, threads de stabilisation du hot folder).
- Pas de `PRAGMA foreign_keys = ON` : SQLite n'applique donc **pas** les contraintes de clé étrangère. Les cascades reposent uniquement sur l'ORM ; toute écriture hors ORM peut laisser des orphelins.
- `datetime.utcnow` (déprécié depuis Python 3.12, alors que le projet cible 3.12) au lieu de `datetime.now(timezone.utc)`.
- `get_all_jobs()` (lignes 357-375) charge **toutes** les lignes puis les `expunge` : aucune pagination. À 50 000 jobs, l'ouverture de la vue devient prohibitive.

---

## 8. Licences et sécurité

**Mécanisme** : licence JSON signée **Ed25519**, vérifiée hors ligne. Empreinte machine = `SHA256(MachineGuid)[:32]`. Deux niveaux : `personal` et `enterprise`. Quota gratuit : `UNLICENSED_MAX_FILES_PER_DAY = 50`.

| Constat | Sévérité |
|---|:--:|
| **Vérification 100 % locale** — aucun appel réseau dans `src/`. Une modification du binaire ou de la clé publique en dur (`licensing.py:35`) suffit à contourner la protection. | 🟠 |
| **`ENTERPRISE_FEATURES` = {ganging, watch_rules, reports, api, multi_post}** mais le gating d'interface ne couvre que **3 boutons** (`jobs_view.btn_gang`, `dashboard_view.btn_report`, `settings_view.btn_watch_rules`). **`api` et `multi_post` sont déclarés mais jamais contrôlés** — soit deux fonctionnalités payantes accessibles à tous, soit deux entrées mortes. Les deux cas sont des défauts. | 🟠 |
| Le README annonce des licences **« RSA / AES-256 »** (deux fois, lignes 135 et 233). L'implémentation réelle est **Ed25519**, sans chiffrement AES. Erreur de documentation sur un sujet où la précision est attendue par les acheteurs. | 🟡 |
| `_volume_check` compare `db.files_processed_today()` (horodatage UTC) à une date locale naïve — le quota bascule à un instant décalé du minuit de l'utilisateur. À Abidjan (UTC+0) l'écart est nul ; il apparaît dès qu'un client est dans un autre fuseau. | 🟡 |
| Le serveur d'activation (`app.py`, `issuer.py`, `store.py`, `admin.py`) est à **0 % de couverture** et son unique test est skippé. Il détient pourtant la clé privée d'émission. | 🟠 |
| `admin.py` contient **8 `print()`** en guise de journalisation côté serveur. | 🟡 |

Aucun secret n'est présent en clair dans le dépôt (la clé en dur est la clé **publique**, ce qui est correct par conception).

---

## 9. Interface et expérience utilisateur

### 9.1 🟠 Le thread UI est bloqué sur trois chemins

Le README promet un « pipeline distribué **sans aucun blocage d'interface** ». Vérification par grep exhaustif : **un seul véritable worker existe dans toute la couche UI** (`_BatchWorker` dans `qr_batch_dialog.py`), plus le `WorkerPoolThread` du pipeline principal.

Bloquent le thread UI :
- `batch_export_dialog._run_export` — export de lot en synchrone ;
- les exports de `sheet_preview` ;
- `sheet_editor.add_file` — appelle `process_job_files` sous un simple `WaitCursor`.

Sur un lot volumineux, la fenêtre est signalée « Ne répond pas » par Windows. L'utilisateur, ne sachant pas si le programme travaille ou a planté, est incité à le forcer à quitter — ce qui, combiné au §4.4, peut faire perdre des fichiers de vue.

### 9.2 Autres points d'interface

- **`settings_view.py`** (532 l.) : 7 onglets codés en dur, `ConfigManager()` instancié directement dans le widget (aucune injection possible, donc non testable).
- **`dashboard.py`** : le graphique 7 jours est dessiné manuellement alors que `pyqtgraph` est une dépendance déclarée et inutilisée ; `_clear_layout` est récursif et rejoué à chaque rafraîchissement.
- **QSS dupliqué en ligne** dans de nombreux widgets alors que `src/ui/resources/dark_theme.qss` (47 lignes) existe et n'est chargé par aucun code Python — vérifié par grep, aucun module ne lit ce fichier.
- **Duplication** : `setup_hot_folder_monitor()` et `restart_hot_folder_monitors()` dans `main_window.py` sont identiques à ~90 % (lignes 632-700). Toute correction devra être appliquée deux fois.
- Le thème est effectivement lu depuis la configuration par `main.py` (lignes 17-23) — c'est le seul des cinq réglages « orphelins » à avoir un consommateur, mais **hors** de `theme.py`, ce qui rend la relation invisible depuis le widget de réglages.

### 9.3 🟠 Cinq réglages écrits par l'interface ne sont lus par personne

`settings_view.save_settings()` (lignes 464-518) écrit des clés dont la traçabilité a été vérifiée une par une par grep sur l'ensemble du dépôt :

| Clé écrite par l'interface | Lue par | Effet réel |
|---|---|---|
| `performance.workers` | **personne** | `WorkerPoolThread` n'est jamais alimenté depuis la configuration → toujours `cpu_count() - 1` |
| `performance.memory_limit_mb` | **personne** | Aucune limite mémoire n'est appliquée |
| `users.role` | **personne** | **Aucun contrôle d'accès n'existe dans le produit** |
| `preflight.allowed_formats` | **personne** | La liste des formats autorisés est ignorée |
| `ui.theme` | `main.py` uniquement | Fonctionne (au redémarrage), mais hors de `theme.py` |

L'utilisateur règle le nombre de workers, la limite mémoire et son rôle utilisateur, l'interface confirme l'enregistrement, **et rien ne change**. C'est un problème de confiance produit autant que de code. Le cas de `users.role` est le plus sensible : il suggère une gestion des droits qui n'existe pas.

Réglages effectivement consommés (à conserver) : `output.archive_days` (`output_manager.py:113`), `automation.enable_scheduling` (`auto_processor.py:58`), ainsi que les chemins, les paramètres d'imposition et d'export.

---

## 10. Inventaire complet des défauts, par sévérité

### 🔴 Critique — à traiter avant toute diffusion

| # | Défaut | Emplacement |
|---|---|---|
| C1 | Transparence jamais détectée + faux positifs sur tout CMJN | `preflight_engine._analyze_pdf_deep` |
| C2 | Contrôle des polices embarquées = stub vide | `preflight_engine.py:107-116` |
| C3 | `ConfigManager` mute `DEFAULT_CONFIG` (copie superficielle) | `utils/config_manager.py` |
| C4 | Aucune CI/CD, aucun garde-fou automatisé | `.github/` inexistant |
| C5 | Couverture réelle ≈ 32 % contre 85 % annoncés ; 0 test d'interface | `tests/` |
| C6 | Chaîne ICC/CMJN et export PDF/X jamais validés (11 skips) | `test_icc_engine`, `test_export_engine` |

### 🟠 Majeur — à traiter dans le trimestre

| # | Défaut | Emplacement |
|---|---|---|
| M1 | Hot folder : aucun scan initial → fichiers pré-existants ignorés | `hot_folder_monitor.start()` |
| M2 | Aucun index en base, pas même sur les FK | `database/models.py` |
| M3 | `_migrate_schema()` concurrent d'Alembic, head désynchronisé | `repository.py:18-70` |
| M4 | Trois numéros de version divergents (1.37.1 / 1.38.0 / 1.5.1) | `_version.py`, `pyproject.toml`, `docs/` |
| M5 | Thread UI bloqué sur 3 chemins d'export | `batch_export_dialog`, `sheet_preview`, `sheet_editor` |
| M6 | 5 réglages d'interface sans consommateur, dont `users.role` | `settings_view.save_settings` |
| M7 | `ready_event.wait()` sans timeout → gel possible de l'interface | `worker_thread.submit_job`, `submit_finalize` |
| **M8** | **`archive_files()` supprime les originaux sans vérifier le ZIP → perte de données (voir encadré)** | `output_manager.py:100-105` |
| M9 | `api` et `multi_post` déclarés payants mais jamais gatés | `licensing.ENTERPRISE_FEATURES` |
| M10 | Vérification de licence 100 % locale, contournable | `licensing.py` |
| M11 | Finalisation du pool sans sémaphore (seuls les chunks sont bornés) | `worker_pool.py` |
| M12 | 123 erreurs ruff alors que le README affirme le lint propre | dépôt entier |
| **M13** | **Incident QA ouvert : disque plein → planches 4 à 20 non exportées, aucun message utilisateur (voir encadré)** | `docs/QA_tests.md` test 14.5 |

> ### [R2] ⛔ M8 + M13 : une chaîne de perte de données définitive
>
> Pris isolément, M8 et M13 semblaient deux défauts modérés. **Combinés, ils détruisent des fichiers client sans le dire** — ce lien, apporté par le contre-audit, est vérifié :
>
> 1. Le disque sature pendant l'export (scénario **déjà survenu**, incident QA 14.5, toujours ouvert) ;
> 2. `zipfile` écrit une archive **tronquée** ; refermer un `ZipFile` sur un disque plein ne lève pas systématiquement d'exception ;
> 3. `archive_files()` enchaîne immédiatement — le `unlink()` des originaux suit le bloc `with zipfile…` **sans aucun contrôle intermédiaire** ;
> 4. Le `except Exception: pass` du niveau supérieur absorbe ce qui pourrait remonter ;
> 5. **Résultat : les originaux sont supprimés, l'archive est inexploitable, et l'opérateur ne voit rien.**
>
> Mesure à l'appui : **`testzip`, `disk_usage`, `shutil.disk_*` et `free_space` totalisent 0 occurrence dans tout `src/`**. Il n'existe donc, nulle part dans le produit, ni vérification d'intégrité d'archive ni contrôle d'espace disque.
>
> **C'est le défaut le plus coûteux de tout cet audit** : un bug de calcul se corrige et se rejoue, un fichier client supprimé ne se récupère pas. M8 est en conséquence remonté de Sprint 2 en **Sprint 1**, aux côtés de M13 qui y figurait déjà. Le correctif est de quelques lignes : `zf.testzip()` (ou relecture de la liste des membres) **avant** tout `unlink()`, et un `shutil.disk_usage()` comparé à la taille estimée avant de lancer l'export.

### 🟡 Mineur — dette à résorber

`src/utils/file_utils.py` **vide (0 octet)** · `setup_logger()` dupliqué entre `config.py` et `logger.py` · `reporting.export_production_xlsx` utilise `chr(64 + index)` → casse au-delà de la colonne Z · `pdf_editor._snapshot()` sérialise le document entier ×10 (mémoire ∝ taille du PDF) · `OutputManager.__init__` crée un `QTimer` (Qt dans la couche métier) · `SystemNotifier` instancie un **second** `QSystemTrayIcon` · `LayoutEngine._stamp_artwork` avale ses exceptions · `RectpackNestingStrategy` legacy (`add_bin()` par élément, rotation ±0.1 mm, `job_id=None`) · `_submit_job` crée un stub PENDING hors transaction · `setup_hot_folder_monitor` / `restart_hot_folder_monitors` dupliqués à 90 % · 3 `except:` nus, 9 `except Exception: pass`, **7 `print()` dans `src/` + 8 dans `activation_server/`** · 5 dépendances déclarées jamais importées · `.coverage` et 102 PDF versionnés · 4 `datetime.utcnow` dépréciés · `mypy strict` configuré mais jamais exécuté · aucun `tests/conftest.py` · `[tool.ruff] exclude` non configuré · README annonce « RSA / AES-256 » (2 mentions) au lieu d'Ed25519 · `dark_theme.qss` jamais chargé.

> **[R2] Deux rectifications dans cette liste.**
> - **Point retiré — OutputIntent FOGRA39 « en dur » : l'affirmation était fausse**, y compris à mon propre commit. `export_engine._output_condition()` (ligne 267) **dérive la condition de sortie du profil réellement utilisé** via `icc_engine.read_profile()`, avec un commentaire explicite (« *so the PDF stops claiming FOGRA39 when the operator selected something else* ») ; le code **embarque même le profil** en `/DestOutputProfile`, comme PDF/X l'exige, et journalise un avertissement quand il ne le peut pas. « FOGRA39 » n'est plus qu'une valeur de repli en l'absence totale de profil. C'est du bon code, que j'avais rangé à tort parmi les défauts.
> - **Sur-comptage corrigé — `print()` : 11 → 7** dans `src/`. Mon grep capturait `…fingerprint(` comme une occurrence de `print(`. Le décompte exact est 7 dans `src/` (`config_manager` ×3, `output_manager` ×2, `auto_processor` ×1, `hot_folder_monitor` ×1) et 8 dans `activation_server/admin.py`.

---

## 11. Plan d'action recommandé

### Sprint 1 — Rétablir la véracité fonctionnelle et le filet de sécurité (~1 semaine)

1. **C1** — Corriger la détection de transparence (`smask`), supprimer la condition `colorspace == 4`, **réécrire le test sur un PDF RGBA réel**.
2. **C2** — Implémenter le contrôle des polices embarquées : **`font[1] == "n/a"`** (champ `ext` — **et non `font[2]`/`type`, qui ne discrimine rien**, cf. §4.2), avec test sur **deux PDF réels** (une police embarquée, une non embarquée).
3. **C3** — `copy.deepcopy(DEFAULT_CONFIG)` dans `ConfigManager`, plus un test de non-régression sur l'identité.
4. **C4** — Créer `.github/workflows/ci.yml` : `ruff check` + `pytest` + `pytest --cov` sur Windows et Linux, à chaque push. C'est le point de levier le plus élevé du plan : il empêche toute régression future d'atteindre l'installeur. **Y inclure dès le départ le profil ICC du point 11** — sinon la CI démarrera verte en sautant silencieusement colorimétrie et PDF/X — **et un `[tool.ruff] exclude`**, faute de quoi le seuil d'échec variera selon les dossiers de travail locaux.
5. **M4** — **D'abord** étendre `scripts/bump_version.py` à `src/_version.py` et au README (il ne les écrit pas aujourd'hui : c'est la cause racine, cf. §6.3), **ensuite** rejouer un bump pour aligner les sources, **puis** ajouter au workflow CI une vérification de cohérence des versions. Aligner à la main sans corriger le script ne tiendrait pas un incrément.
6. **M13 + M8 — perte de données, priorité absolue du sprint** : contrôler l'espace disque (`shutil.disk_usage()`) avant export et remonter une erreur explicite à l'utilisateur ; **vérifier l'intégrité du ZIP (`testzip()`) avant tout `unlink()` d'originaux** ; clore l'incident QA 14.5. Voir l'encadré du §10.

### Sprint 2 — Fiabiliser la production (~2 semaines)

7. **M1** — Scan initial du hot folder au démarrage, avec `rule_id`.
8. **M2 / M3** — Index sur toutes les FK + `created_at` + `archived` ; une révision Alembic rattrapant `archived` et `quantities` ; suppression de `_migrate_schema()`.
9. *(M8 a été remonté en Sprint 1, point 6 — voir l'encadré perte de données du §10.)*
10. **M7** — Ajouter un timeout à `ready_event.wait()` et propager l'échec proprement.
11. **C6** — Embarquer un profil ICC CMJN libre (par ex. Coated FOGRA39 depuis le jeu ICC ouvert) dans `tests/fixtures/` pour dé-skipper les 11 tests ICC/export. **À traiter avec le point 4** : sans ce profil, la CI d'un runner vierge sautera ces tests en silence et affichera un vert trompeur.
12. **M6** — Soit câbler `performance.workers`, `memory_limit_mb` et `preflight.allowed_formats` sur leurs consommateurs, soit **retirer ces champs de l'interface**. Pour `users.role`, retirer le champ tant qu'aucun contrôle d'accès n'existe.

### Sprint 3 — Consolider (~1 mois)

13. **C5** — Premiers tests d'interface avec `pytest-qt` sur `main_window`, `settings_view` et `job_queue` ; viser 50 % global puis fixer `fail_under = 50` dans `pyproject.toml`.
14. **M5** — Déporter les trois exports bloquants sur des `QRunnable` / `QThreadPool`.
15. **M9 / M10** — Câbler ou retirer `api` et `multi_post` ; envisager une revalidation en ligne périodique et optionnelle.
16. **M12** — `ruff check --fix` sur les 18 corrections automatiques, puis traitement des E501 par lots ; installer `mypy` et démarrer le typage strict module par module.
17. Nettoyage : retirer `.coverage` et les 102 PDF du suivi Git (les générer à la volée), supprimer les 5 dépendances inutilisées, découper `pdf_editor_view.py` et `main_window.py`, mutualiser `setup_hot_folder_monitor` / `restart_hot_folder_monitors`, créer `tests/conftest.py`, corriger `chr(64+i)`, supprimer ou remplir `file_utils.py`.
18. **Documentation** — Aligner le README sur la réalité mesurée (couverture, Ed25519, blocage d'interface, 6 axes de preflight) et réactualiser les 5 documents `docs/` (v1.5.1 → version courante).

---

## 12. Conclusion

Le code de Jelotia Imposer est **meilleur que ses tests, et plus modeste que sa documentation**.

L'architecture est saine et manifestement pensée par quelqu'un qui connaît le métier de la pré-presse : séparation des couches respectée sans exception, domaine découplé de l'ORM et de Qt, mécanismes de reprise sur incident réellement conçus plutôt que bricolés, et un usage systématique du commentaire pour justifier les décisions non évidentes — pratique rare qui rend le code reprenable par un tiers.

Ce qui manque n'est pas de la compétence, c'est de la **vérification** : pas de CI, une couverture réelle trois fois inférieure à celle affichée, aucun test d'interface sur 8 267 lignes, et — le symptôme le plus révélateur — un module de preflight à 100 % de couverture dont deux des six contrôles annoncés ne fonctionnent pas, parce que les tests valident un mock inventé plutôt que le comportement réel de PyMuPDF.

`memory-bank/progress.md` le dit d'ailleurs sans détour : la Phase 6 « Tests, QA, performances » compte 14 objectifs, **aucun coché**. Le diagnostic de cet audit rejoint donc celui de l'équipe elle-même. La priorité n'est pas de réécrire quoi que ce soit — c'est de **mettre en place le filet de sécurité (Sprint 1) puis de rendre le discours conforme à la mesure**. Les six correctifs critiques représentent quelques jours de travail pour un gain de fiabilité considérable, et la mise en place d'une CI est ce qui garantira que ce gain ne se perdra pas au prochain incrément.

---

*Audit réalisé par lecture intégrale du dépôt, exécution réelle de la suite de tests et vérification empirique en environnement isolé. Chaque chiffre cité provient d'une mesure, non d'une estimation.*
