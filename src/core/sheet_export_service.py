import logging
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from src.core.engines.export_engine import ExportEngine
from src.core.engines.layout_engine import LayoutEngine
from src.core.models.domain import JobSettings, Sheet

logger = logging.getLogger(__name__)


class SheetExportService:
    """
    Regenerates a Sheet's base PDF from its current PlacedItem layout and
    exports it in one or more formats. This is the single place that knows how
    to turn an in-memory Sheet (possibly hand-edited) back into output files —
    used both after manual repositioning and for grouped multi-format export,
    since neither can rely on the intermediate PDF produced during the initial
    job run (it's deleted once that job's own export completes).
    """

    def __init__(self):
        self.layout_engine = LayoutEngine()
        self.export_engine = ExportEngine()

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
        Renders `sheet` (as currently laid out) to a fresh base PDF, then exports
        it once per entry in `formats` (e.g. ["PDF", "TIFF"]).

        Returns a dict mapping each requested format to its output Path.
        """
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
