import logging
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from src.core.engines.export_engine import ExportEngine
from src.core.engines.layout_engine import LayoutEngine
from src.core.models.domain import JobSettings, Sheet

logger = logging.getLogger(__name__)


class MissingArtworkError(Exception):
    """Raised when a Sheet can't be regenerated because one or more of its
    items' source artwork no longer exists on disk (e.g. a corrected temp file
    that was cleaned up once the job's own export completed)."""


class SheetExportService:
    """
    The single place that knows how to turn an in-memory Sheet back into
    output files, via two different paths depending on whether the layout
    actually changed:

    - `convert_and_export`: the sheet's own rendered export (`sheet.export_path`)
      is still valid — just convert it to other formats. Use this for grouped
      export and quick format export, since it never touches the original
      artwork (which may already be gone — see MissingArtworkError below).
    - `regenerate_and_export`: the item layout changed (manual repositioning)
      and the sheet must be re-rendered from its PlacedItem source files. This
      only works while those source files still exist.
    """

    def __init__(self):
        self.layout_engine = LayoutEngine()
        self.export_engine = ExportEngine()

    def convert_and_export(
        self,
        sheet: Sheet,
        settings: JobSettings,
        formats: List[str],
        output_dir: Path,
        job_name: Optional[str] = None,
    ) -> Dict[str, Path]:
        """
        Converts the sheet's existing export to one or more formats, without
        touching the original artwork sources.
        """
        if not sheet.export_path or not sheet.export_path.exists():
            raise MissingArtworkError(
                f"La planche {sheet.sheet_number} n'a pas (ou plus) de fichier exporté à convertir."
            )

        results: Dict[str, Path] = {}
        for fmt in formats:
            fmt_settings = settings.model_copy(update={"export_format": fmt})
            results[fmt] = self.export_engine.convert_existing(
                job_id=sheet.job_id,
                sheet=sheet,
                existing_path=sheet.export_path,
                settings=fmt_settings,
                output_dir=output_dir,
                job_name=job_name,
            )
        return results

    def regenerate_and_export(
        self,
        sheet: Sheet,
        settings: JobSettings,
        formats: List[str],
        output_dir: Path,
        work_dir: Path,
        job_name: Optional[str] = None,
    ) -> Dict[str, Path]:
        """
        Re-stamps `sheet`'s artwork at its current PlacedItem positions into a
        fresh base PDF, then exports it once per entry in `formats`. Needed
        after manual repositioning, since the layout actually changed.

        Raises MissingArtworkError up front (before generating anything) if any
        item's source file is gone, rather than silently producing a sheet with
        blank/missing elements.
        """
        missing = [it.source_path for it in sheet.items if not Path(it.source_path).exists()]
        if missing:
            names = ", ".join(str(p) for p in missing)
            raise MissingArtworkError(
                "Impossible de régénérer la planche : "
                f"{len(missing)} élément(s) introuvable(s) sur le disque ({names}). "
                "Ces fichiers sources (souvent des versions corrigées temporaires) ont été "
                "nettoyés après la fin du job — la disposition ne peut pas être réappliquée."
            )

        results: Dict[str, Path] = {}
        try:
            base_pdf_path = self.layout_engine.generate_sheet_pdf(sheet.job_id, sheet, settings, work_dir)

            for fmt in formats:
                fmt_settings = settings.model_copy(update={"export_format": fmt})
                final_path = self.export_engine.export_sheet(
                    job_id=sheet.job_id,
                    sheet=sheet,
                    base_pdf_path=base_pdf_path,
                    settings=fmt_settings,
                    output_dir=output_dir,
                    job_name=job_name,
                )
                results[fmt] = final_path
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

        return results
