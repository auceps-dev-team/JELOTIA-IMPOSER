from typing import List, Optional

from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker, subqueryload

from src.core.models.domain import Job
from src.database.models import Base, FileItemModel, JobModel, SheetModel
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
        logger.info(f"Database initialized at {db_url}")

    def get_session(self) -> Session:
        return self.SessionLocal()

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
                    items=[item.model_dump() for item in sheet.items],
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

    def get_all_jobs(self) -> List[JobModel]:
        """Retrieve all jobs, eagerly loading relationships."""
        session = self.get_session()
        try:
            jobs = (
                session.query(JobModel)
                .options(subqueryload(JobModel.files), subqueryload(JobModel.sheets))
                .all()
            )
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
