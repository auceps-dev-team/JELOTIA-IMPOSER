"""Cliquet sur les lignes trop longues (E501).

Pourquoi un cliquet plutôt qu'un nettoyage massif : 91 lignes héritées dépassent
100 colonnes. Les corriger revient à 820 lignes de diff en formatant les seuls
fichiers concernés, 2 557 en formatant tout le dépôt — pour une règle purement
cosmétique, sur un projet où plusieurs personnes poussent en parallèle. Le
bénéfice ne paie ni le bruit dans `git blame` ni les conflits de fusion.

Ce script fige donc le nombre actuel comme plafond : ajouter une ligne trop
longue fait échouer la CI, en corriger permet d'abaisser le plafond. La dette
existante ne bloque personne, mais elle ne peut plus grandir.

    uv run python scripts/check_line_length.py            # vérifie
    uv run python scripts/check_line_length.py --update   # abaisse le plafond
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_FILE = ROOT / "scripts" / "e501_baseline.txt"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):  # pragma: no cover - consoles exotiques
        pass


def count_violations() -> int:
    """Nombre de lignes > 100 colonnes, tel que ruff les compte."""
    result = subprocess.run(
        ["uv", "run", "ruff", "check", ".", "--select", "E501", "--output-format=concise"],
        cwd=ROOT, capture_output=True, text=True,
    )
    return len(re.findall(r": E501 ", result.stdout))


def read_baseline() -> int:
    if not BASELINE_FILE.exists():
        return 0
    for line in BASELINE_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return int(line)
    return 0


def write_baseline(count: int) -> None:
    BASELINE_FILE.write_text(
        "# Plafond de lignes > 100 colonnes (E501).\n"
        "# Il ne doit JAMAIS augmenter. Après avoir corrigé des lignes, abaissez-le :\n"
        "#   uv run python scripts/check_line_length.py --update\n"
        f"{count}\n",
        encoding="utf-8",
    )


def main() -> int:
    current = count_violations()
    baseline = read_baseline()

    if "--update" in sys.argv:
        if current > baseline and baseline:
            print(f"Refus : {current} > plafond {baseline}. Corrigez avant d'abaisser.")
            return 1
        write_baseline(current)
        print(f"Plafond abaissé à {current}.")
        return 0

    print(f"lignes trop longues : {current}   plafond : {baseline}")
    if current > baseline:
        print(
            f"\nÉCHEC : {current - baseline} ligne(s) trop longue(s) ajoutée(s).\n"
            "Repliez-les (limite : 100 colonnes) — la dette héritée est tolérée,\n"
            "mais elle ne doit pas grandir."
        )
        return 1
    if current < baseline:
        print(f"\n{baseline - current} ligne(s) corrigée(s) : abaissez le plafond avec --update.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
