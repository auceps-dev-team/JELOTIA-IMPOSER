#!/usr/bin/env python3
# ruff: noqa: E501  (tableau de libellés : les couper nuirait à la lisibilité)
"""Génère la carte mentale du projet JELOTIA IMPOSER (SVG + PNG).

Rendu maison, sans dépendance graphviz : mise en page « mindmap » classique
(noeud central, branches à gauche et à droite, connecteurs en Bézier).
Palette reprise du design system Workbench (src/ui/theme.py).

Usage :  python tools/generate_mindmap.py
Sorties : docs/audit/carte_mentale.svg  et  docs/audit/carte_mentale.png
"""
from __future__ import annotations

import html
from pathlib import Path

# --------------------------------------------------------------------------- #
#  Palette (src/ui/theme.py — design system "Workbench")
# --------------------------------------------------------------------------- #
BG_APP = "#141517"
BG_PANEL = "#1B1D20"
BORDER = "#33363B"
TEXT_1 = "#E8EAED"
TEXT_2 = "#C8CBD0"
TEXT_MUTE = "#8B8F96"
ACCENT = "#FF7A1A"
STATE_OK = "#4DD97E"
STATE_WARN = "#FFB35C"
STATE_ERR = "#E5484D"

# Couleur par branche
BRANCHES: list[dict] = [
    # ---------------------------- COLONNE GAUCHE --------------------------- #
    {
        "side": "L",
        "title": "POINT D'ENTRÉE\n& CONFIGURATION",
        "color": "#FF7A1A",
        "meta": "main.py · src/utils",
        "children": [
            ("main.py", "freeze_support() → QApplication → thème → MainWindow", "ok"),
            ("utils/config_manager.py", "config.json runtime · BUG : DEFAULT_CONFIG muté (copy superficielle)", "err"),
            ("utils/config.py", "Pydantic Settings + chemins C:\\Jelotia · setup_logger dupliqué", "warn"),
            ("utils/logger.py", "loguru, rotation · 0 % de couverture", "warn"),
            ("utils/file_utils.py", "FICHIER VIDE (0 octet)", "err"),
        ],
    },
    {
        "side": "L",
        "title": "COUCHE UI\nPySide6 · 8 267 LOC",
        "color": "#5AA9FF",
        "meta": "src/ui — 17 widgets, graphe acyclique",
        "children": [
            ("main_window.py (1003 l.)", "orchestrateur : 7 vues, hot folders, gating licence, reprise", "ok"),
            ("widgets/ dashboard · job_queue · sheet_editor", "graphe 7 j fait main alors que pyqtgraph est déclaré", "warn"),
            ("pdf_editor_view.py (1070 l.)", "plus gros fichier du dépôt", "warn"),
            ("settings_view.py (532 l.)", "7 onglets en dur · 5 réglages écrits mais jamais lus", "err"),
            ("theme.py + dark_theme.qss", "QSS inline dupliqué dans les widgets", "warn"),
            ("Thread UI bloqué", "batch_export · sheet_preview · sheet_editor.add_file", "err"),
            ("0 test UI", "aucun test ne référence src.ui (5 233 stmts)", "err"),
        ],
    },
    {
        "side": "L",
        "title": "QUALITÉ\n& TESTS",
        "color": "#B08CFF",
        "meta": "tests/ — 5 536 LOC",
        "children": [
            ("pytest", "285 passed · 1 failed · 12 skipped (~22 s)", "warn"),
            ("Couverture réelle ≈ 32 %", "76 % hors UI vs 85 % annoncé au README · pas de fail_under", "err"),
            ("12 skips environnementaux", "ICC/CMJN ×11 + activation_server ×1 → jamais validés", "err"),
            ("ruff (config projet)", "123 erreurs · 1348 en jeu de règles étendu", "err"),
            ("Aucune CI/CD", "pas de .github/ · .coverage et 102 PDF versionnés", "err"),
            ("docs/QA_tests.md", "campagne terrain 2 000 fichiers · incident disque plein ouvert", "warn"),
        ],
    },
    {
        "side": "L",
        "title": "BUILD\n& DIFFUSION",
        "color": "#7ED0C0",
        "meta": "installer/ · scripts/",
        "children": [
            ("jelotia_imposer.spec", "PyInstaller onedir · console=False · 27 hiddenimports", "ok"),
            ("jelotia_imposer.iss", "Inno Setup x64 · Win 10+ · FR/EN · clé HKLM", "ok"),
            ("Versions désynchronisées", "_version 1.37.1 / pyproject 1.38.0 / docs 1.5.1", "err"),
            ("scripts/", "bump_version · benchmark_runner · integration_tests (hors pytest)", "warn"),
        ],
    },
    # ---------------------------- COLONNE DROITE --------------------------- #
    {
        "side": "R",
        "title": "CŒUR MÉTIER\nsrc/core · 1 452 LOC",
        "color": "#4DD97E",
        "meta": "orchestration & services",
        "children": [
            ("hot_folder_monitor.py", "watchdog + stabilisation 2 s · AUCUN scan initial au démarrage", "err"),
            ("auto_processor.py", "regroupement par rule_id · 30 % de couverture", "warn"),
            ("worker_thread.py / worker_pool.py", "ready_event.wait() sans timeout · finalisation sans sémaphore", "err"),
            ("job_processor.py", "pipeline import → preflight → correction → nesting → export", "ok"),
            ("ganging.py", "gang_signature sur paramètres physiques", "ok"),
            ("output_manager.py", "QTimer dans le métier · archive_files() unlink sans testzip : PERTE DE DONNÉES", "err"),
            ("reporting.py", "chr(64+i) → casse au-delà de la colonne Z", "warn"),
            ("presets · watch_rules · sheet_export_service · system_notifier", "MissingArtworkError · 2ᵉ QSystemTrayIcon", "warn"),
        ],
    },
    {
        "side": "R",
        "title": "MOTEURS\n15 modules · 3 601 LOC",
        "color": "#FFB35C",
        "meta": "src/core/engines",
        "children": [
            ("preflight_engine.py", "BUG : transparence jamais détectée (alpha vs smask) + faux positifs CMJN", "err"),
            ("preflight — polices", "boucle get_fonts() vide : embarquement jamais contrôlé", "err"),
            ("nesting_engine.py", "MaxRects/Guillotine (rectpack) + stratégie grille · legacy Rectpack", "warn"),
            ("layout_engine.py", "reportlab · repères ARMS · filigrane licence · exceptions avalées", "warn"),
            ("export_engine.py", "PDF/X-1a & X-4, TIFF, JPEG · OutputIntent dérivé du profil + ICC embarqué", "ok"),
            ("icc_engine.py", "littleCMS réel (RGB→CMJN) · non testé faute de profil", "warn"),
            ("pdf_editor.py", "undo borné 10 · _snapshot() sérialise tout le doc ×10", "warn"),
            ("bleed · correction · import · photoshop_tiff · template_composer", "TIFF RIP legacy (Predictor=2, RowsPerStrip=4)", "ok"),
            ("qr_engine · qr_batch · qr_import", "plans de lots, mapping colonnes, badges", "ok"),
        ],
    },
    {
        "side": "R",
        "title": "PERSISTANCE",
        "color": "#E5A0FF",
        "meta": "src/database — SQLite/SQLAlchemy",
        "children": [
            ("models.py", "4 tables : jobs · file_items · sheets · qr_batches", "ok"),
            ("AUCUN index", "pas même sur les FK job_id → scans sur historique volumineux", "err"),
            ("_migrate_schema() vs Alembic", "ALTER TABLE manuel (archived, quantities) hors des 2 révisions", "err"),
            ("repository.py", "get_all_jobs charge tout puis expunge · pas de pagination", "warn"),
            ("SQLite brut", "pas de PRAGMA foreign_keys · pas de check_same_thread · utcnow déprécié", "warn"),
        ],
    },
    {
        "side": "R",
        "title": "LICENCES\n& ACTIVATION",
        "color": "#E5484D",
        "meta": "src/core/licensing.py · activation_server/",
        "children": [
            ("Ed25519 hors-ligne", "clé publique en dur · README annonce à tort « RSA / AES-256 »", "warn"),
            ("Vérification 100 % locale", "contournable · empreinte SHA256(MachineGuid)[:32]", "err"),
            ("Gating = 3 boutons", "api et multi_post déclarés dans ENTERPRISE_FEATURES mais jamais gatés", "err"),
            ("Quota gratuit 50 fichiers/j", "_volume_check compare UTC et heure locale naïve", "warn"),
            ("activation_server (FastAPI)", "app · issuer · store · admin — 0 % de couverture, test skippé", "err"),
        ],
    },
    {
        "side": "R",
        "title": "DOCUMENTATION\n& PILOTAGE",
        "color": "#8B8F96",
        "meta": "docs/ · memory-bank/ · 1c Workbench/",
        "children": [
            ("README.md (29 Ko)", "vitrine commerciale · plusieurs chiffres non tenus", "warn"),
            ("docs/ ×5", "technique · installation · utilisateur · maintenance · QA (v1.5.1)", "ok"),
            ("memory-bank/ ×5", "brief · contexte · patterns · techContext · progress", "ok"),
            ("progress.md — Phase 6", "14 cases tests/QA/perf, AUCUNE cochée", "err"),
            ("1c Workbench/", "maquettes HTML du design system (source des tokens)", "ok"),
        ],
    },
]

STATE_COLORS = {"ok": STATE_OK, "warn": STATE_WARN, "err": STATE_ERR}

# --------------------------------------------------------------------------- #
#  Mise en page
# --------------------------------------------------------------------------- #
W = 3400
COL_W = 1180           # largeur d'une colonne de branches
CENTER_W = 420
CHILD_H = 46
CHILD_GAP = 6
BRANCH_GAP = 54
HEAD_H = 78
PAD_TOP = 190

FONT = "'Segoe UI', 'DejaVu Sans', Helvetica, Arial, sans-serif"
MONO = "'Cascadia Mono', 'DejaVu Sans Mono', Consolas, monospace"


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def measure(branch: dict) -> float:
    return HEAD_H + 14 + len(branch["children"]) * (CHILD_H + CHILD_GAP)


def layout() -> tuple[list[dict], float]:
    """Chaque colonne est centrée verticalement sur le noyau, pour éviter
    qu'une colonne plus courte laisse un grand vide en bas."""
    left = [b for b in BRANCHES if b["side"] == "L"]
    right = [b for b in BRANCHES if b["side"] == "R"]
    col_heights = {}
    for name, col in (("L", left), ("R", right)):
        col_heights[name] = sum(measure(b) for b in col) + BRANCH_GAP * (len(col) - 1)

    tallest = max(col_heights.values())
    total = PAD_TOP + tallest + 150

    placed: list[dict] = []
    for name, col in (("L", left), ("R", right)):
        y = PAD_TOP + (tallest - col_heights[name]) / 2
        for b in col:
            h = measure(b)
            b["_y"] = y
            b["_h"] = h
            placed.append(b)
            y += h + BRANCH_GAP
    return placed, total


def render() -> str:
    placed, height = layout()
    cx = W / 2
    cy = height / 2

    out: list[str] = []
    a = out.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height:.0f}" '
      f'viewBox="0 0 {W} {height:.0f}" font-family="{FONT}">')

    # ---- defs -----------------------------------------------------------
    a('<defs>')
    a(f'<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
      f'<stop offset="0%" stop-color="{BG_APP}"/>'
      f'<stop offset="100%" stop-color="#0E0F11"/></linearGradient>')
    a(f'<radialGradient id="glow" cx="50%" cy="50%" r="50%">'
      f'<stop offset="0%" stop-color="{ACCENT}" stop-opacity="0.30"/>'
      f'<stop offset="100%" stop-color="{ACCENT}" stop-opacity="0"/></radialGradient>')
    a('<filter id="soft" x="-30%" y="-30%" width="160%" height="160%">'
      '<feDropShadow dx="0" dy="3" stdDeviation="6" flood-color="#000" flood-opacity="0.55"/></filter>')
    a('</defs>')

    a(f'<rect width="{W}" height="{height:.0f}" fill="url(#bg)"/>')

    # trame de fond
    a(f'<g stroke="{BORDER}" stroke-opacity="0.20" stroke-width="1">')
    for gx in range(0, W, 60):
        a(f'<line x1="{gx}" y1="0" x2="{gx}" y2="{height:.0f}"/>')
    for gy in range(0, int(height), 60):
        a(f'<line x1="0" y1="{gy}" x2="{W}" y2="{gy}"/>')
    a('</g>')

    # ---- titre ----------------------------------------------------------
    a(f'<text x="60" y="76" font-size="40" font-weight="700" fill="{TEXT_1}" '
      f'letter-spacing="1.5">CARTE MENTALE — JELOTIA IMPOSER</text>')
    a(f'<text x="62" y="112" font-size="20" fill="{TEXT_MUTE}" font-family="{MONO}">'
      f'21 651 LOC Python · 9 domaines · 15 moteurs · 17 widgets · audit du 24/08/2026</text>')

    # légende
    lx = W - 700
    a(f'<text x="{lx}" y="60" font-size="17" fill="{TEXT_MUTE}" font-weight="600">LÉGENDE</text>')
    for i, (key, label) in enumerate((("ok", "sain / point fort"),
                                      ("warn", "à surveiller / dette"),
                                      ("err", "défaut critique"))):
        y = 88 + i * 26
        a(f'<rect x="{lx}" y="{y - 12}" width="14" height="14" rx="3" fill="{STATE_COLORS[key]}"/>')
        a(f'<text x="{lx + 24}" y="{y}" font-size="16" fill="{TEXT_2}">{esc(label)}</text>')

    # ---- noyau ----------------------------------------------------------
    a(f'<circle cx="{cx}" cy="{cy}" r="330" fill="url(#glow)"/>')
    core_w, core_h = CENTER_W, 210
    a(f'<rect x="{cx - core_w/2}" y="{cy - core_h/2}" width="{core_w}" height="{core_h}" rx="24" '
      f'fill="{BG_PANEL}" stroke="{ACCENT}" stroke-width="3" filter="url(#soft)"/>')
    a(f'<text x="{cx}" y="{cy - 52}" text-anchor="middle" font-size="17" '
      f'fill="{ACCENT}" font-family="{MONO}" letter-spacing="4">PRÉ-PRESSE AUTOMATISÉ</text>')
    a(f'<text x="{cx}" y="{cy - 6}" text-anchor="middle" font-size="44" font-weight="800" '
      f'fill="{TEXT_1}" letter-spacing="1">JELOTIA</text>')
    a(f'<text x="{cx}" y="{cy + 38}" text-anchor="middle" font-size="44" font-weight="800" '
      f'fill="{TEXT_1}" letter-spacing="1">IMPOSER</text>')
    a(f'<text x="{cx}" y="{cy + 72}" text-anchor="middle" font-size="16" fill="{TEXT_MUTE}" '
      f'font-family="{MONO}">PySide6 · SQLite · PyMuPDF · v1.38.0</text>')

    # ---- branches -------------------------------------------------------
    for b in placed:
        right = b["side"] == "R"
        color = b["color"]
        by = b["_y"]
        bw = COL_W
        bx = cx + CENTER_W / 2 + 150 if right else cx - CENTER_W / 2 - 150 - bw

        # connecteur noyau → branche
        anchor_x = cx + CENTER_W / 2 if right else cx - CENTER_W / 2
        tip_x = bx if right else bx + bw
        mid_y = by + HEAD_H / 2
        c1 = anchor_x + (tip_x - anchor_x) * 0.45
        a(f'<path d="M {anchor_x} {cy} C {c1} {cy}, {c1} {mid_y}, {tip_x} {mid_y}" '
          f'fill="none" stroke="{color}" stroke-width="3.5" stroke-opacity="0.85"/>')
        a(f'<circle cx="{tip_x}" cy="{mid_y}" r="6" fill="{color}"/>')

        # en-tête de branche
        a(f'<rect x="{bx}" y="{by}" width="{bw}" height="{HEAD_H}" rx="14" '
          f'fill="{BG_PANEL}" stroke="{color}" stroke-width="2.5" filter="url(#soft)"/>')
        a(f'<rect x="{bx}" y="{by}" width="7" height="{HEAD_H}" rx="3.5" fill="{color}"/>')
        lines = b["title"].split("\n")
        tx = bx + 24
        if len(lines) == 1:
            a(f'<text x="{tx}" y="{by + 38}" font-size="25" font-weight="700" fill="{TEXT_1}">'
              f'{esc(lines[0])}</text>')
        else:
            a(f'<text x="{tx}" y="{by + 31}" font-size="23" font-weight="700" fill="{TEXT_1}">'
              f'{esc(lines[0])}</text>')
            a(f'<text x="{tx}" y="{by + 55}" font-size="23" font-weight="700" fill="{TEXT_1}">'
              f'{esc(lines[1])}</text>')
        a(f'<text x="{bx + bw - 20}" y="{by + 48}" text-anchor="end" font-size="15" '
          f'fill="{TEXT_MUTE}" font-family="{MONO}">{esc(b["meta"])}</text>')

        # rail vertical
        rail_x = bx + 34
        last_y = by + HEAD_H + 14 + (len(b["children"]) - 1) * (CHILD_H + CHILD_GAP) + CHILD_H / 2
        a(f'<path d="M {rail_x} {by + HEAD_H} L {rail_x} {last_y}" stroke="{color}" '
          f'stroke-width="2" stroke-opacity="0.5" fill="none"/>')

        # feuilles
        for i, (label, note, state) in enumerate(b["children"]):
            y = by + HEAD_H + 14 + i * (CHILD_H + CHILD_GAP)
            sc = STATE_COLORS[state]
            a(f'<path d="M {rail_x} {y + CHILD_H/2} L {rail_x + 22} {y + CHILD_H/2}" '
              f'stroke="{color}" stroke-width="2" stroke-opacity="0.5"/>')
            a(f'<rect x="{rail_x + 22}" y="{y}" width="{bw - (rail_x + 22 - bx) - 18}" '
              f'height="{CHILD_H}" rx="9" fill="#212328" stroke="{BORDER}" stroke-width="1"/>')
            a(f'<rect x="{rail_x + 22}" y="{y}" width="5" height="{CHILD_H}" rx="2.5" fill="{sc}"/>')
            a(f'<text x="{rail_x + 40}" y="{y + 20}" font-size="17" font-weight="600" '
              f'fill="{TEXT_1}" font-family="{MONO}">{esc(label)}</text>')
            a(f'<text x="{rail_x + 40}" y="{y + 38}" font-size="15" fill="{TEXT_MUTE}">'
              f'{esc(note)}</text>')

    # ---- bandeau de synthèse -------------------------------------------
    fy = height - 62
    a(f'<rect x="0" y="{fy - 34}" width="{W}" height="96" fill="#0E0F11" fill-opacity="0.9"/>')
    stats = [
        ("21 651", "LOC Python", TEXT_1),
        ("285 / 1 / 12", "tests OK / KO / skip", STATE_WARN),
        ("≈ 32 %", "couverture réelle", STATE_ERR),
        ("123", "erreurs ruff", STATE_ERR),
        ("0", "pipeline CI", STATE_ERR),
        ("2", "bugs prouvés en exécution", STATE_ERR),
        ("5", "réglages UI orphelins", STATE_WARN),
        ("3", "versions divergentes", STATE_WARN),
    ]
    step = W / len(stats)
    for i, (value, label, color) in enumerate(stats):
        x = step * (i + 0.5)
        a(f'<text x="{x}" y="{fy}" text-anchor="middle" font-size="30" font-weight="700" '
          f'fill="{color}" font-family="{MONO}">{esc(value)}</text>')
        a(f'<text x="{x}" y="{fy + 24}" text-anchor="middle" font-size="15" '
          f'fill="{TEXT_MUTE}">{esc(label)}</text>')

    a('</svg>')
    return "\n".join(out)


def main() -> None:
    out_dir = Path(__file__).resolve().parents[1] / "docs" / "audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    svg_path = out_dir / "carte_mentale.svg"
    svg_path.write_text(render(), encoding="utf-8")
    print(f"SVG écrit : {svg_path}")
    png_path = out_dir / "carte_mentale.png"
    # PyMuPDF est déjà une dépendance du projet : on l'utilise pour la
    # rasterisation plutôt que d'ajouter cairosvg (qui exige libcairo).
    try:
        import pymupdf

        doc = pymupdf.open(str(svg_path))
        doc[0].get_pixmap(dpi=72).save(str(png_path))
        print(f"PNG écrit : {png_path}")
        return
    except Exception as exc:  # pragma: no cover - dépend de l'environnement
        print(f"PyMuPDF indisponible pour le PNG ({exc}) — tentative cairosvg…")
    try:
        import cairosvg

        cairosvg.svg2png(url=str(svg_path), write_to=str(png_path), scale=1.0)
        print(f"PNG écrit : {png_path}")
    except Exception:
        print("PNG non généré (le SVG reste la source de vérité).")


if __name__ == "__main__":
    main()
