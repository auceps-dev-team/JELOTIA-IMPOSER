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


def job_assets_dir(job_id: UUID) -> Path:
    """Permanent (never auto-cleaned) home for the artwork files a job's
    sheets reference — unlike the ephemeral per-job folder under
    config.processing_dir (deleted by finalize_job_sheets once the sheet PDF
    is generated), this must survive indefinitely: manual sheet regeneration
    re-reads every item's source file from disk each time."""
    from src.utils.config import config

    path = config.output_dir / str(job_id) / "assets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _persist_sheet_sources(sheets: List[Sheet], job_temp_dir: Path, job_id: UUID) -> None:
    """Relocates every artwork file referenced by the sheets' PlacedItems into
    the job's permanent assets folder and repoints the items there.

    Without this, items keep referencing the corrected temp files under
    job_temp_dir, which finalize_job_sheets deletes right after export — so
    any later manual repositioning (which re-stamps the sheet from those
    files, possibly days after the job finished) would always fail with
    MissingArtworkError. Files inside job_temp_dir are moved (that dir is
    about to be deleted anyway); files elsewhere (hot-folder originals that
    get archived, arbitrary user paths) are copied.
    """
    try:
        assets_dir = job_assets_dir(job_id)
    except OSError as e:
        logger.warning(f"Could not create assets dir for job {job_id}: {e}")
        return

    relocated: Dict[Path, Path] = {}
    for sheet in sheets:
        for item in sheet.items:
            src = Path(item.source_path)
            dest = relocated.get(src)
            if dest is None:
                if not src.exists() or assets_dir in src.parents:
                    continue
                dest = assets_dir / src.name
                counter = 0
                while dest.exists():
                    counter += 1
                    dest = assets_dir / f"{src.stem}_{counter}{src.suffix}"
                try:
                    if job_temp_dir in src.parents:
                        shutil.move(str(src), str(dest))
                    else:
                        shutil.copy2(str(src), str(dest))
                except OSError as e:
                    logger.warning(f"Could not persist artwork source {src}: {e}")
                    continue
                relocated[src] = dest
            item.source_path = dest


def apply_target_size(item: FileItem, settings: JobSettings) -> None:
    """Forces the artwork's placement footprint to the target product size set
    on the gamme / job, in place, before nesting.

    Placing the pose at this size and letting the layout scale the source into
    it is exactly what a manual resize after imposition does (see
    SheetEditor.resize_to), so the pre- and post-imposition paths behave
    identically by construction — no change to stamping is needed.

    A target axis <= 0 leaves that axis at the file's natural size (0/0 = off).
    The DPI is rescaled to the effective printed resolution (worst axis) so an
    enlarged file still trips the min_dpi preflight warning at its printed size.
    """
    tw = settings.target_file_width_mm
    th = settings.target_file_height_mm
    if tw <= 0 and th <= 0:
        return
    if item.width_mm <= 0 or item.height_mm <= 0:
        return

    new_w = tw if tw > 0 else item.width_mm
    new_h = th if th > 0 else item.height_mm
    ratio = min(item.width_mm / new_w, item.height_mm / new_h)
    item.dpi = max(1, int(round(item.dpi * ratio)))
    item.width_mm = new_w
    item.height_mm = new_h


def _apply_bleed(item: FileItem, settings: JobSettings, work_dir: Path) -> None:
    """Gives `item` the configured bleed, in place.

    Two cases, and the difference matters for the sizes:
    - the file already carries enough bleed (real BleedBox): its measured
      dimensions ALREADY include it — only record how much;
    - otherwise a bleed-extended copy is produced and the item grows by
      2*bleed, so the nesting reserves the printed size.
    """
    if settings.add_bleed_mm <= 0:
        return
    from src.core.engines.bleed_engine import BleedError, available_bleed_mm, ensure_bleed

    try:
        existing = available_bleed_mm(item.path)
        new_path, applied = ensure_bleed(
            item.path, settings.add_bleed_mm, work_dir, name_hint=str(item.id)
        )
    except (BleedError, OSError) as e:
        logger.warning(f"Fond perdu impossible pour {item.path}: {e}")
        return

    if applied <= 0:
        item.bleed_mm = min(existing, settings.add_bleed_mm)
        return

    item.path = new_path
    item.width_mm += 2 * applied
    item.height_mm += 2 * applied
    item.bleed_mm = applied


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

                # 1b. Resize to the target product size (gamme / job) BEFORE
                # validating, so preflight judges the printed pose — its size
                # against the sheet and its effective DPI — not the raw file.
                apply_target_size(item, settings)

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

                # 4. Bleed: extend the artwork past the trim line so a slightly
                # drifting blade never exposes white. Done after correction so
                # the corrected file is the one extended.
                _apply_bleed(item, settings, job_temp_dir)

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

    # The sheets' items still reference intermediate files (about to be
    # deleted with job_temp_dir) — relocate them somewhere durable first so
    # manual repositioning can re-stamp the sheets later.
    if sheets:
        _persist_sheet_sources(sheets, job_temp_dir, job_id)

    # Intermediate artifacts (corrected files from every chunk, base sheet
    # PDFs) have been consumed into job_output_dir; safe to discard.
    shutil.rmtree(job_temp_dir, ignore_errors=True)

    return sheets
