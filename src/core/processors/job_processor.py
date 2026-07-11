import logging
import shutil
from pathlib import Path
from typing import Dict, List, Optional
from uuid import UUID

from src.core.engines.correction_engine import CorrectionEngine
from src.core.engines.import_engine import ImportEngine
from src.core.engines.nesting_engine import NestingEngine, ShelfNestingStrategy
from src.core.engines.preflight_engine import PreflightEngine
from src.core.models.domain import FileItem, JobSettings, PreflightStatus, Sheet

logger = logging.getLogger(__name__)


def process_job_files(
    job_id: UUID,
    file_paths: List[Path],
    settings: JobSettings,
    quantities: Optional[Dict[str, int]] = None,
    work_dir: Optional[Path] = None,
) -> List[FileItem]:
    """
    Processes a list of file paths for a single job (or a chunk of one — see
    finalize_job_sheets for why nesting is deliberately NOT done here).
    Executes Import -> Preflight -> Correction sequentially for each file.
    Designed to run inside an isolated process (Worker).

    Args:
        job_id (UUID): The ID of the (logical) Job. Large jobs are split into
            chunks dispatched to different workers, but all chunks of one
            logical job share this same job_id, so their corrected files land
            in the same job_temp_dir for finalize_job_sheets to pick up.
        file_paths (List[Path]): The raw files to process.
        settings (JobSettings): The settings associated with the Job.
        quantities (dict, optional): Maps a source path (str) to how many
            copies of it should end up on the sheet — lets the user print
            several exemplars of one file alongside others in the same job.
            Every FileItem produced from that path (e.g. every page of a
            multi-page PDF) gets the same override. Defaults to 1 (unchanged
            behavior) for paths not present in the map.
        work_dir (Path, optional): Where CorrectionEngine writes corrected
            files. Defaults to the usual ephemeral per-job folder under
            config.processing_dir (cleaned up by finalize_job_sheets once the
            sheet PDF is generated). Callers that add a file to an *already
            finished* job (which never runs finalize_job_sheets again) must
            pass a permanent directory instead, since manual sheet edits
            re-read each item's corrected file from disk on every
            regeneration — an ephemeral path would go stale.

    Returns:
        List[FileItem]: The fully processed FileItems.
    """
    from src.utils.config import config

    # All per-job intermediate artifacts (corrected files) are confined to
    # this job-scoped subfolder, never written loose into processing_dir's
    # root. MainWindow.recover_orphan_jobs() scans that root for crash-recovery
    # and would otherwise pick up our own temp files as brand-new "orphan"
    # jobs, reprocessing them endlessly on every restart.
    job_temp_dir = work_dir if work_dir is not None else config.processing_dir / str(job_id)

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

            requested_qty = (quantities or {}).get(str(file_path))
            if requested_qty:
                for item in file_items:
                    item.quantity = requested_qty

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

    return processed_items


def finalize_job_sheets(
    job_id: UUID, file_items: List[FileItem], settings: JobSettings, job_name: Optional[str] = None
) -> List[Sheet]:
    """
    Nests, lays out and exports the sheets for a whole logical job in one
    shot, from the combined FileItems of every chunk. Nesting needs the
    complete file set to pack sheets well — running it once per chunk (as a
    naive per-worker pipeline would) makes each chunk fill its own sheet
    independently, drastically under-using the sheet whenever a job is split
    into chunks (automation.max_files_per_job): e.g. a 200-file job split into
    4 chunks of 50 would produce 4 sparsely-filled sheets instead of combining
    all 200 files into however many sheets are actually needed.

    Designed to run inside an isolated process (Worker), once per logical job
    after all of its chunks' process_job_files() calls have completed.
    """
    from src.utils.config import config

    job_temp_dir = config.processing_dir / str(job_id)

    nesting_engine = NestingEngine(ShelfNestingStrategy())
    sheets: List[Sheet] = []
    try:
        sheets = nesting_engine.process(file_items, settings)
    except Exception as e:
        logger.exception(f"Fatal error during nesting: {e}")
        # Note: we still return whatever we have (empty) even if nesting fails

    if sheets:
        from src.core.engines.export_engine import ExportEngine
        from src.core.engines.layout_engine import LayoutEngine
        layout_engine = LayoutEngine()
        export_engine = ExportEngine()
        try:
            sheets = layout_engine.process_job_layout(job_id, sheets, settings, job_temp_dir)

            # Export (Converts to PDF/X, TIFF, or JPEG based on settings)
            job_output_dir = config.output_dir / str(job_id)
            for sheet in sheets:
                if sheet.export_path and sheet.export_path.exists():
                    final_path = export_engine.export_sheet(
                        job_id=job_id,
                        sheet=sheet,
                        base_pdf_path=sheet.export_path,
                        settings=settings,
                        output_dir=job_output_dir,
                        job_name=job_name,
                    )
                    # Update export_path to the final output file
                    sheet.export_path = final_path
        except Exception as e:
            logger.exception(f"Fatal error during layout or export generation: {e}")

    # Intermediate artifacts (corrected files from every chunk, base sheet
    # PDFs) have been consumed into job_output_dir; safe to discard.
    shutil.rmtree(job_temp_dir, ignore_errors=True)

    return sheets
