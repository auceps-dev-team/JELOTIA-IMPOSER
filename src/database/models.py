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
    created_at = Column(DateTime, default=datetime.utcnow)
    settings = Column(JSON, nullable=False)
    stats = Column(JSON, nullable=False)
    # Original input file paths as submitted, kept so a failed/interrupted
    # job can actually be resumed (re-run through the whole pipeline) rather
    # than just having its status reset with nothing to re-process.
    source_paths = Column(JSON, nullable=False, default=list)
    # Archived jobs are hidden from the Jobs view but kept in the DB (and
    # still count in dashboard/production history) for potential reuse.
    archived = Column(Boolean, nullable=False, default=False)

    files = relationship("FileItemModel", back_populates="job", cascade="all, delete-orphan")
    sheets = relationship("SheetModel", back_populates="job", cascade="all, delete-orphan")


class FileItemModel(Base):
    __tablename__ = "file_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    job_id = Column(String(36), ForeignKey("jobs.id"), nullable=False)
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
    job_id = Column(String(36), ForeignKey("jobs.id"), nullable=False)
    sheet_number = Column(Integer, nullable=False)
    width_mm = Column(Float, nullable=False)
    height_mm = Column(Float, nullable=False)
    fill_rate = Column(Float, default=0.0)
    export_path = Column(String(1024), nullable=True)
    items = Column(JSON, nullable=False)

    job = relationship("JobModel", back_populates="sheets")
