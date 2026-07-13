import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from src.core.engines.qr_engine import QREngine, safe_filename
from src.core.models.domain import CardTemplate, QRCodeSettings, QRItem

logger = logging.getLogger(__name__)


@dataclass
class ColumnMapping:
    """Which imported columns feed each QRItem field. Only `url_col` is
    required; the others fall back to a generated name / quantity 1."""
    url_col: str
    filename_col: Optional[str] = None
    quantity_col: Optional[str] = None


@dataclass
class BatchPlan:
    """The QRItems to generate, plus counts of rows dropped while building it."""
    items: List[QRItem]
    duplicates_skipped: int = 0
    empty_skipped: int = 0

    @property
    def total(self) -> int:
        return len(self.items)


@dataclass
class BatchItemResult:
    item: QRItem
    paths: Dict[str, Path] = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class BatchResult:
    out_dir: Path
    results: List[BatchItemResult] = field(default_factory=list)
    cancelled: bool = False

    @property
    def succeeded(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.ok)


def build_plan(
    rows: List[Dict[str, str]], mapping: ColumnMapping, allow_duplicates: bool = True
) -> BatchPlan:
    """Turns imported rows into QRItems using the column mapping. Rows with an
    empty URL are dropped (empty_skipped); when duplicates are rejected, rows
    whose URL was already seen are dropped (duplicates_skipped)."""
    items: List[QRItem] = []
    seen: set[str] = set()
    duplicates = 0
    empty = 0

    for index, row in enumerate(rows):
        data = (row.get(mapping.url_col) or "").strip()
        if not data:
            empty += 1
            continue

        if not allow_duplicates:
            if data in seen:
                duplicates += 1
                continue
            seen.add(data)

        filename = ""
        if mapping.filename_col:
            filename = (row.get(mapping.filename_col) or "").strip()
        if not filename:
            filename = f"qr_{index + 1:05d}"

        quantity = 1
        if mapping.quantity_col:
            raw_qty = (row.get(mapping.quantity_col) or "").strip()
            if raw_qty:
                try:
                    quantity = max(1, int(float(raw_qty)))
                except ValueError:
                    quantity = 1

        # The whole row travels with the item so template text zones can
        # substitute {Colonne} placeholders per row (variable-data printing).
        items.append(QRItem(data=data, filename=filename, quantity=quantity, row=dict(row)))

    return BatchPlan(items=items, duplicates_skipped=duplicates, empty_skipped=empty)


def _unique_base(base: str, used: set[str]) -> str:
    """Ensures output base names are unique so two rows sharing a filename
    don't overwrite each other's files."""
    if base not in used:
        used.add(base)
        return base
    n = 2
    while f"{base}_{n}" in used:
        n += 1
    unique = f"{base}_{n}"
    used.add(unique)
    return unique


def generate_batch(
    engine: QREngine,
    items: List[QRItem],
    settings: QRCodeSettings,
    out_dir: Path,
    formats: List[str],
    progress_cb: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    template: Optional[CardTemplate] = None,
) -> BatchResult:
    """Generates every item in every requested format into out_dir, collecting
    per-item success/failure (one bad row never aborts the whole batch).

    With a `template`, each item is composed onto the card template instead
    (background PDF + QR at its zone + text zones with per-row {Colonne}
    substitution) — output is then one vector PDF per row, whatever `formats`
    says. `progress_cb(done, total)` is called after each item;
    `should_cancel()` is polled before each item so a UI can stop a long run.
    Output base names are de-duplicated to avoid silent overwrites."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    composer = None
    if template is not None:
        from src.core.engines.template_composer import TemplateComposer

        composer = TemplateComposer()

    result = BatchResult(out_dir=out_dir)
    used_names: set[str] = set()
    total = len(items)

    for done, item in enumerate(items, start=1):
        if should_cancel is not None and should_cancel():
            result.cancelled = True
            break

        base = _unique_base(safe_filename(item.filename) or f"qr_{done:05d}", used_names)
        item_named = item.model_copy(update={"filename": base})
        try:
            if composer is not None:
                path = composer.compose(
                    template, item_named.data, settings,
                    out_dir / f"{base}.pdf", row=item_named.row,
                )
                paths = {"PDF": path}
            else:
                paths = engine.generate_item(item_named, settings, out_dir, formats)
            result.results.append(BatchItemResult(item=item_named, paths=paths))
        except Exception as e:
            logger.warning(f"QR batch: échec pour {base}: {e}")
            result.results.append(BatchItemResult(item=item_named, error=str(e)))

        if progress_cb is not None:
            progress_cb(done, total)

    return result


def imposition_payload(result: BatchResult) -> tuple:
    """Turns a finished batch into what the imposition pipeline needs:
    (file_paths, {path: quantity}). Prefers each item's PDF output (vector —
    what the sheets are stamped from); quantities come from the imported
    quantity column so 'Qte=50' really places 50 copies on the sheets."""
    paths: List[str] = []
    quantities: Dict[str, int] = {}
    for r in result.results:
        if not r.ok:
            continue
        path = r.paths.get("PDF") or next(iter(r.paths.values()), None)
        if path is None:
            continue
        paths.append(str(path))
        quantities[str(path)] = max(1, r.item.quantity)
    return paths, quantities


def zip_outputs(src_dir: Path, zip_path: Path) -> Path:
    """Zips every generated file directly under src_dir into zip_path."""
    src_dir = Path(src_dir)
    zip_path = Path(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in sorted(src_dir.iterdir()):
            if entry.is_file() and entry.resolve() != zip_path.resolve():
                zf.write(str(entry), entry.name)
    return zip_path
