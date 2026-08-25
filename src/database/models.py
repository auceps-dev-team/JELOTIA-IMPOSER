import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def generate_uuid() -> str:
    return str(uuid.uuid4())


class JobModel(Base):
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, default="PENDING")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    settings = Column(JSON, nullable=False)
    stats = Column(JSON, nullable=False)
    # Original input file paths as submitted, kept so a failed/interrupted
    # job can actually be resumed (re-run through the whole pipeline) rather
    # than just having its status reset with nothing to re-process.
    source_paths = Column(JSON, nullable=False, default=list)
    # Per-file copy counts {path: qty} as submitted. Persisted because every
    # re-submission path (resume, duplicate, gang) rebuilds the job from these
    # rows — without them a "50 copies" order silently restarts at 1.
    quantities = Column(JSON, nullable=False, default=dict)
    # Archived jobs are hidden from the Jobs view but kept in the DB (and
    # still count in dashboard/production history) for potential reuse.
    archived = Column(Boolean, nullable=False, default=False, index=True)

    files = relationship("FileItemModel", back_populates="job", cascade="all, delete-orphan")
    sheets = relationship("SheetModel", back_populates="job", cascade="all, delete-orphan")


class QRBatchModel(Base):
    """History of QR batch runs (F4·QR): what was generated, from which file,
    with which template, and where the output landed — the cahier's
    ExportHistory, scoped to batches."""

    __tablename__ = "qr_batches"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    source_name = Column(String(255), nullable=False, default="")
    template_name = Column(String(255), nullable=True)
    formats = Column(String(100), nullable=False, default="")
    total = Column(Integer, nullable=False, default=0)
    succeeded = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    cancelled = Column(Boolean, nullable=False, default=False)
    out_dir = Column(String(1024), nullable=False, default="")


class FileItemModel(Base):
    __tablename__ = "file_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    job_id = Column(String(36), ForeignKey("jobs.id"), nullable=False, index=True)
    path = Column(String(1024), nullable=False)
    format = Column(String(10), nullable=False)
    width_mm = Column(Float, nullable=False)
    height_mm = Column(Float, nullable=False)
    dpi = Column(Integer, nullable=False)
    color_mode = Column(String(10), nullable=False)
    quantity = Column(Integer, default=1)
    preflight_status = Column(String(50), default="PENDING")
    preflight_errors = Column(JSON, nullable=False)

    job = relationship("JobModel", back_populates="files")


class SheetModel(Base):
    __tablename__ = "sheets"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    job_id = Column(String(36), ForeignKey("jobs.id"), nullable=False, index=True)
    sheet_number = Column(Integer, nullable=False)
    width_mm = Column(Float, nullable=False)
    height_mm = Column(Float, nullable=False)
    fill_rate = Column(Float, default=0.0)
    export_path = Column(String(1024), nullable=True)
    items = Column(JSON, nullable=False)

    job = relationship("JobModel", back_populates="sheets")
