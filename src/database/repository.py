from typing import Dict, List, Optional

from loguru import logger
from sqlalchemy import create_engine, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker, subqueryload

from src.core.models.domain import FileItem, Job, JobSettings, Sheet
from src.database.models import Base, FileItemModel, JobModel, QRBatchModel, SheetModel
from src.utils.config import config


class DatabaseRepository:
    def __init__(self, db_url: Optional[str] = None) -> None:
        if db_url is None:
            db_url = f"sqlite:///{config.db_path}"
        elif not db_url.startswith("sqlite:///"):
            db_url = f"sqlite:///{db_url}"

        self.engine = create_engine(db_url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self._migrate_schema()
        logger.info(f"Database initialized at {db_url}")

    def _migrate_schema(self) -> None:
        """create_all only creates missing TABLES — it never adds new columns
        to existing ones. Field databases predate `jobs.archived`, so add it
        in place if absent (SQLite ALTER TABLE ADD COLUMN is cheap and safe)."""
        added = (
            ("archived", "BOOLEAN NOT NULL DEFAULT 0"),
            ("quantities", "JSON NOT NULL DEFAULT '{}'"),
        )
        try:
            with self.engine.connect() as conn:
                cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(jobs)")]
                if not cols:
                    return
                for name, ddl in added:
                    if name not in cols:
                        conn.exec_driver_sql(f"ALTER TABLE jobs ADD COLUMN {name} {ddl}")
                        conn.commit()
                        logger.info(f"Schema migrated: jobs.{name} column added")
        except SQLAlchemyError as e:
            logger.error(f"Schema migration failed: {e}")

    def get_session(self) -> Session:
        return self.SessionLocal()

    def create_job_stub(
        self,
        job_id: str,
        name: str,
        source_paths: List[str],
        settings: JobSettings,
        quantities: Optional[Dict[str, int]] = None,
    ) -> bool:
        """Persists a job the moment it's submitted — before any files have
        been processed yet — so it survives a crash/restart and (if it later
        fails) can actually be resumed from its original source files.

        Upserts: resuming a failed job resubmits under the *same* job_id (see
        MainWindow._submit_job's reuse_job_id), so this must update the
        existing row in place rather than fail on a duplicate primary key —
        clearing any stale files/sheets from the previous failed attempt.
        """
        session = self.get_session()
        try:
            existing = session.query(JobModel).filter(JobModel.id == job_id).first()
            if existing:
                existing.name = name
                existing.status = "PENDING"
                existing.settings = settings.model_dump()
                existing.source_paths = list(source_paths)
                existing.quantities = dict(quantities or {})
                session.query(FileItemModel).filter(FileItemModel.job_id == job_id).delete()
                session.query(SheetModel).filter(SheetModel.job_id == job_id).delete()
            else:
                session.add(
                    JobModel(
                        id=job_id,
                        name=name,
                        status="PENDING",
                        settings=settings.model_dump(),
                        stats={},
                        source_paths=list(source_paths),
                        quantities=dict(quantities or {}),
                    )
                )
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Error creating job stub {job_id}: {e}")
            return False
        finally:
            session.close()

    def create_job(self, job: Job) -> Optional[str]:
        """Create a new job in the database."""
        session = self.get_session()
        try:
            db_job = JobModel(
                id=str(job.id),
                name=job.name,
                status=job.status.value,
                created_at=job.created_at,
                settings=job.settings.model_dump(),
                stats=job.stats.model_dump(),
            )
            session.add(db_job)

            for file in job.files:
                db_file = FileItemModel(
                    id=str(file.id),
                    job_id=str(job.id),
                    path=str(file.path),
                    format=file.format.value,
                    width_mm=file.width_mm,
                    height_mm=file.height_mm,
                    dpi=file.dpi,
                    color_mode=file.color_mode.value,
                    quantity=file.quantity,
                    preflight_status=file.preflight_status.value,
                    preflight_errors=[err.model_dump() for err in file.preflight_errors],
                )
                session.add(db_file)

            for sheet in job.sheets:
                db_sheet = SheetModel(
                    id=str(sheet.id),
                    job_id=str(job.id),
                    sheet_number=sheet.sheet_number,
                    width_mm=sheet.width_mm,
                    height_mm=sheet.height_mm,
                    fill_rate=sheet.fill_rate,
                    export_path=str(sheet.export_path) if sheet.export_path else None,
                    items=[item.model_dump(mode="json") for item in sheet.items],
                )
                session.add(db_sheet)

            session.commit()
            logger.info(f"Job {job.id} created successfully")
            return str(job.id)
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Error creating job {job.id}: {e}")
            return None
        finally:
            session.close()

    def get_job(self, job_id: str) -> Optional[JobModel]:
        """Retrieve a job by its ID, eagerly loading its relationships."""
        session = self.get_session()
        try:
            job = (
                session.query(JobModel)
                .options(subqueryload(JobModel.files), subqueryload(JobModel.sheets))
                .filter(JobModel.id == job_id)
                .first()
            )
            if job:
                # Force load
                job.files
                job.sheets
                session.expunge(job)
            return job
        finally:
            session.close()

    def get_dashboard_stats(self) -> Dict[str, object]:
        """Aggregate metrics for the dashboard, computed in SQL rather than by
        materializing every job/file/sheet row — the app targets 10k files/day,
        so a dashboard refresh must not load the whole DB into memory.

        Returns active job count, total preflight-error files, total generated
        sheets, average sheet fill rate, and a {ISO-date: sheet_count} map
        (sheets attributed to their parent job's created_at, since sheets carry
        no timestamp of their own)."""
        empty: Dict[str, object] = {
            "active_jobs": 0,
            "preflight_errors": 0,
            "total_sheets": 0,
            "avg_fill_rate": 0.0,
            "sheets_by_date": {},
        }
        session = self.get_session()
        try:
            active_jobs = (
                session.query(func.count(JobModel.id))
                .filter(JobModel.status.in_(("PENDING", "PROCESSING")))
                .scalar()
            ) or 0
            preflight_errors = (
                session.query(func.count(FileItemModel.id))
                .filter(FileItemModel.preflight_status == "ERROR")
                .scalar()
            ) or 0
            total_sheets = session.query(func.count(SheetModel.id)).scalar() or 0
            avg_fill_rate = session.query(func.avg(SheetModel.fill_rate)).scalar() or 0.0

            # SQLite's date() yields 'YYYY-MM-DD' strings, matching
            # datetime.date.isoformat() used on the dashboard side.
            rows = (
                session.query(
                    func.date(JobModel.created_at).label("day"),
                    func.count(SheetModel.id),
                )
                .join(SheetModel, SheetModel.job_id == JobModel.id)
                .group_by("day")
                .all()
            )
            sheets_by_date = {day: int(count) for day, count in rows if day is not None}

            return {
                "active_jobs": int(active_jobs),
                "preflight_errors": int(preflight_errors),
                "total_sheets": int(total_sheets),
                "avg_fill_rate": float(avg_fill_rate),
                "sheets_by_date": sheets_by_date,
            }
        except SQLAlchemyError as e:
            logger.error(f"Error computing dashboard stats: {e}")
            return empty
        finally:
            session.close()

    def add_qr_batch(
        self,
        *,
        source_name: str,
        template_name: Optional[str],
        formats: str,
        total: int,
        succeeded: int,
        failed: int,
        cancelled: bool,
        out_dir: str,
    ) -> bool:
        """Records one QR batch run in the history."""
        session = self.get_session()
        try:
            session.add(
                QRBatchModel(
                    source_name=source_name, template_name=template_name,
                    formats=formats, total=total, succeeded=succeeded,
                    failed=failed, cancelled=cancelled, out_dir=out_dir,
                )
            )
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Error recording QR batch: {e}")
            return False
        finally:
            session.close()

    def get_qr_batches(self, limit: int = 50) -> List[QRBatchModel]:
        """Most recent batch runs first."""
        session = self.get_session()
        try:
            batches = (
                session.query(QRBatchModel)
                .order_by(QRBatchModel.created_at.desc())
                .limit(limit)
                .all()
            )
            for batch in batches:
                session.expunge(batch)
            return batches
        finally:
            session.close()

    def files_processed_today(self) -> int:
        """Total source files across jobs created today — drives the Personnel
        daily volume cap. Counts jobs (including archived) so the cap can't be
        dodged by archiving."""
        from datetime import datetime, timezone

        session = self.get_session()
        try:
            start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0, tzinfo=None
            )
            jobs = (
                session.query(JobModel.source_paths)
                .filter(JobModel.created_at >= start)
                .all()
            )
            return sum(len(paths or []) for (paths,) in jobs)
        except SQLAlchemyError as e:
            logger.error(f"Error counting today's files: {e}")
            return 0
        finally:
            session.close()

    def get_system_counts(self) -> Dict[str, int]:
        """Lightweight totals for the system-info screen (SQL COUNTs only)."""
        session = self.get_session()
        try:
            jobs = session.query(func.count(JobModel.id)).scalar() or 0
            archived = (
                session.query(func.count(JobModel.id))
                .filter(JobModel.archived.is_(True))
                .scalar()
            ) or 0
            files = session.query(func.count(FileItemModel.id)).scalar() or 0
            sheets = session.query(func.count(SheetModel.id)).scalar() or 0
            return {
                "jobs": int(jobs),
                "jobs_archived": int(archived),
                "files": int(files),
                "sheets": int(sheets),
            }
        except SQLAlchemyError as e:
            logger.error(f"Error computing system counts: {e}")
            return {"jobs": 0, "jobs_archived": 0, "files": 0, "sheets": 0}
        finally:
            session.close()

    def delete_job(self, job_id: str) -> bool:
        """Permanently removes a job and its files/sheets rows."""
        session = self.get_session()
        try:
            job = session.query(JobModel).filter(JobModel.id == job_id).first()
            if job is None:
                return False
            session.delete(job)  # cascade removes files + sheets
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Error deleting job {job_id}: {e}")
            return False
        finally:
            session.close()

    def set_job_archived(self, job_id: str, archived: bool) -> bool:
        """Hides (or restores) a job from the Jobs view; the row and its
        sheets stay in the DB and keep counting in production history."""
        session = self.get_session()
        try:
            job = session.query(JobModel).filter(JobModel.id == job_id).first()
            if job is None:
                return False
            job.archived = archived
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Error archiving job {job_id}: {e}")
            return False
        finally:
            session.close()

    def get_all_jobs(self, include_archived: bool = False) -> List[JobModel]:
        """Retrieve all jobs, eagerly loading relationships. Archived jobs are
        excluded unless explicitly requested."""
        session = self.get_session()
        try:
            query = session.query(JobModel).options(
                subqueryload(JobModel.files), subqueryload(JobModel.sheets)
            )
            if not include_archived:
                query = query.filter(JobModel.archived.is_(False))
            jobs = query.all()
            for job in jobs:
                # Force load
                job.files
                job.sheets
                session.expunge(job)
            return jobs
        finally:
            session.close()

    def update_job_status(self, job_id: str, new_status: str) -> bool:
        """Update the status of a job."""
        session = self.get_session()
        try:
            job = session.query(JobModel).filter(JobModel.id == job_id).first()
            if job:
                job.status = new_status
                session.commit()
                return True
            return False
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Error updating job status {job_id}: {e}")
            return False
        finally:
            session.close()

    def recover_processing_jobs(self) -> int:
        """Reset any PROCESSING jobs to PENDING (crash recovery)."""
        session = self.get_session()
        try:
            jobs = session.query(JobModel).filter(JobModel.status == "PROCESSING").all()
            count = len(jobs)
            for job in jobs:
                job.status = "PENDING"
            session.commit()
            if count > 0:
                logger.info(f"Recovered {count} jobs from PROCESSING to PENDING")
            return count
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Error recovering jobs: {e}")
            return 0
        finally:
            session.close()

    def update_job_files(self, job_id: str, files: List[FileItem]) -> bool:
        """Update or insert FileItems for a given job."""
        session = self.get_session()
        try:
            # Delete existing files for this job to replace them with the processed ones
            session.query(FileItemModel).filter(FileItemModel.job_id == job_id).delete()

            for file in files:
                db_file = FileItemModel(
                    id=str(file.id),
                    job_id=str(job_id),
                    path=str(file.path),
                    format=file.format.value,
                    width_mm=file.width_mm,
                    height_mm=file.height_mm,
                    dpi=file.dpi,
                    color_mode=file.color_mode.value,
                    quantity=file.quantity,
                    preflight_status=file.preflight_status.value,
                    preflight_errors=[err.model_dump() for err in file.preflight_errors],
                )
                session.add(db_file)

            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Error updating files for job {job_id}: {e}")
            return False
        finally:
            session.close()

    def update_job_sheets(self, job_id: str, sheets: List[Sheet]) -> bool:
        """Update or insert Sheets for a given job."""
        session = self.get_session()
        try:
            # Delete existing sheets for this job to replace them
            session.query(SheetModel).filter(SheetModel.job_id == job_id).delete()

            for sheet in sheets:
                db_sheet = SheetModel(
                    id=str(sheet.id),
                    job_id=str(job_id),
                    sheet_number=sheet.sheet_number,
                    width_mm=sheet.width_mm,
                    height_mm=sheet.height_mm,
                    fill_rate=sheet.fill_rate,
                    export_path=str(sheet.export_path) if sheet.export_path else None,
                    items=[item.model_dump(mode="json") for item in sheet.items],
                )
                session.add(db_sheet)

            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Error updating sheets for job {job_id}: {e}")
            return False
        finally:
            session.close()
