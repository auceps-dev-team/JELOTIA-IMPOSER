import logging
import shutil
from pathlib import Path
from typing import List, Tuple
from uuid import UUID

from src.core.engines.correction_engine import CorrectionEngine
from src.core.engines.import_engine import ImportEngine
from src.core.engines.nesting_engine import NestingEngine, RectpackNestingStrategy
from src.core.engines.preflight_engine import PreflightEngine
from src.core.models.domain import FileItem, JobSettings, PreflightStatus, Sheet

logger = logging.getLogger(__name__)


def process_job_files(
    job_id: UUID, file_paths: List[Path], settings: JobSettings
) -> Tuple[List[FileItem], List[Sheet]]:
    """
    Processes a list of file paths for a single job.
    Executes Import -> Preflight -> Correction sequentially for each file.
    Designed to run inside an isolated process (Worker).

    Args:
        job_id (UUID): The ID of the Job.
        file_paths (List[Path]): The raw files to process.
        settings (JobSettings): The settings associated with the Job.

    Returns:
        List[FileItem]: The fully processed FileItems.
    """
    from src.utils.config import config

    # All per-job intermediate artifacts (corrected files, base sheet PDFs) are
    # confined to this job-scoped subfolder, never written loose into
    # processing_dir's root. MainWindow.recover_orphan_jobs() scans that root
    # for crash-recovery and would otherwise pick up our own temp files as
    # brand-new "orphan" jobs, reprocessing them endlessly on every restart.
    job_temp_dir = config.processing_dir / str(job_id)

    import_engine = ImportEngine()
    preflight_engine = PreflightEngine()
    correction_engine = CorrectionEngine(settings, job_temp_dir)

    processed_items = []

    for file_path in file_paths:
        logger.info(f"Worker processing file: {file_path}")
        try:
            # 1. Import (Extracts metadata, creates FileItem(s))
            # Handle multi-page PDFs which return multiple FileItems
            file_items = import_engine.process_file(job_id, file_path, min_dpi=settings.min_dpi)

            for item in file_items:
                if item.preflight_status == PreflightStatus.ERROR:
                    # Item is already corrupted during import
                    processed_items.append(item)
                    continue

                # 2. Preflight (Validates the item)
                item = preflight_engine.run_preflight(item, settings)

                # 3. Correction (Fixes the item if possible and requested)
                # We only correct if there are warnings (like RGB or no bleed)
                # Blocking errors (like corrupted file) bypass correction
                if item.preflight_status == PreflightStatus.WARNING:
                    try:
                        item = correction_engine.process(item)
                    except Exception as ce:
                        logger.error(f"Correction failed for {item.path}: {ce}")
                        # If correction fails, we might mark it as ERROR or keep it WARNING depending on severity
                        # For now, let's keep it as is, or we could add an error.

                processed_items.append(item)
        except Exception as e:
            logger.exception(f"Fatal error processing file {file_path}: {e}")
            # If an unhandled exception occurs, create a generic error FileItem
            # (Note: ImportEngine already does this, but we wrap just in case)
            pass

    # 4. Nesting (Places corrected files on sheets)
    nesting_engine = NestingEngine(RectpackNestingStrategy(algo_type="maxrects"))
    sheets = []
    try:
        sheets = nesting_engine.process(processed_items, settings)
    except Exception as e:
        logger.exception(f"Fatal error during nesting: {e}")
        # Note: we still return processed_items even if nesting fails

    # 5. Layout (Generates PDF for sheets)
    if sheets:
        from src.core.engines.export_engine import ExportEngine
        from src.core.engines.layout_engine import LayoutEngine
        layout_engine = LayoutEngine()
        export_engine = ExportEngine()
        try:
            sheets = layout_engine.process_job_layout(job_id, sheets, settings, job_temp_dir)

            # 6. Export (Converts to PDF/X, TIFF, or JPEG based on settings)
            job_output_dir = config.output_dir / str(job_id)
            for sheet in sheets:
                if sheet.export_path and sheet.export_path.exists():
                    final_path = export_engine.export_sheet(
                        job_id=job_id,
                        sheet=sheet,
                        base_pdf_path=sheet.export_path,
                        settings=settings,
                        output_dir=job_output_dir
                    )
                    # Update export_path to the final output file
                    sheet.export_path = final_path

            # Intermediate artifacts (corrected files, base sheet PDFs) have
            # been consumed into job_output_dir; safe to discard.
            shutil.rmtree(job_temp_dir, ignore_errors=True)
        except Exception as e:
            logger.exception(f"Fatal error during layout or export generation: {e}")
    else:
        # No sheets produced (e.g. nesting failed), but CorrectionEngine may
        # still have written files into job_temp_dir — clean those up too.
        shutil.rmtree(job_temp_dir, ignore_errors=True)

    return processed_items, sheets
