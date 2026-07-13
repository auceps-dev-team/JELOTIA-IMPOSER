import csv
import logging
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


class TableImportError(Exception):
    """Raised when an import file can't be read (unsupported extension, empty
    file, unreadable content)."""


def read_table(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    """Reads a .xlsx / .csv file into (headers, rows), where each row is a
    {header: value} dict with string values. The first line is treated as the
    header row. Blank rows are skipped."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        return _read_xlsx(path)
    if ext in (".csv", ".txt", ".tsv"):
        return _read_csv(path)
    raise TableImportError(
        f"Format d'import non supporté : {ext or '(sans extension)'} "
        "(attendu .xlsx ou .csv)."
    )


def _headers_from(raw_header) -> List[str]:
    """Builds unique, non-empty column names from a raw header row (fills in
    'Colonne N' for blanks and disambiguates duplicates so mapping combos never
    collide)."""
    headers: List[str] = []
    seen: Dict[str, int] = {}
    for i, cell in enumerate(raw_header or []):
        name = str(cell).strip() if cell is not None else ""
        if not name:
            name = f"Colonne {i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
        else:
            seen[name] = 1
        headers.append(name)
    return headers


def _read_xlsx(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    try:
        import openpyxl
    except ImportError as e:  # pragma: no cover - dependency is declared
        raise TableImportError("openpyxl requis pour lire les fichiers Excel.") from e

    try:
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    except Exception as e:
        raise TableImportError(f"Fichier Excel illisible : {e}") from e

    try:
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        raw_header = next(rows_iter, None)
        if raw_header is None:
            return [], []
        headers = _headers_from(raw_header)

        rows: List[Dict[str, str]] = []
        for raw in rows_iter:
            if raw is None or all(c is None for c in raw):
                continue
            rows.append(
                {
                    headers[i]: ("" if c is None else str(c))
                    for i, c in enumerate(raw)
                    if i < len(headers)
                }
            )
        return headers, rows
    finally:
        wb.close()


def _read_csv(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    try:
        # utf-8-sig transparently strips a BOM if Excel wrote one.
        with open(path, newline="", encoding="utf-8-sig") as f:
            sample = f.read(4096)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
            except csv.Error:
                dialect = csv.excel
            raw_rows = list(csv.reader(f, dialect))
    except OSError as e:
        raise TableImportError(f"Fichier CSV illisible : {e}") from e

    if not raw_rows:
        return [], []

    headers = _headers_from(raw_rows[0])
    rows: List[Dict[str, str]] = []
    for raw in raw_rows[1:]:
        if not any((cell or "").strip() for cell in raw):
            continue
        rows.append(
            {headers[i]: (raw[i] if i < len(raw) else "") for i in range(len(headers))}
        )
    return headers, rows
