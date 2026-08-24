import shutil
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger
from PySide6.QtCore import QTimer

from src.utils.config_manager import ConfigManager


class OutputManager:
    def __init__(self):
        self.config = ConfigManager()
        self._ensure_directories()
        
        # Setup cleanup timer (runs every 12 hours)
        self.cleanup_timer = QTimer()
        self.cleanup_timer.timeout.connect(self.cleanup_archives)
        self.cleanup_timer.start(12 * 3600 * 1000)
        
        # Run an initial cleanup shortly after startup
        QTimer.singleShot(5000, self.cleanup_archives)
        
    def _ensure_directories(self):
        input_path = self.config.get("paths", "input")
        if not input_path:
            input_path = str(Path.home() / "Jelotia" / "HotFolder" / "Input")
            
        base_dir = Path(input_path).parent
        self.output_dir = base_dir / "Output"
        self.error_dir = base_dir / "Error"
        self.archive_dir = base_dir / "Archive"
        self.processing_dir = base_dir / "Processing"
        
        for d in [self.output_dir, self.error_dir, self.archive_dir, self.processing_dir]:
            d.mkdir(parents=True, exist_ok=True)
            
    def move_to_output(self, file_path: str):
        p = Path(file_path)
        dest = self.output_dir / p.name
        if p.exists():
            shutil.move(str(p), str(dest))
        return str(dest)
        
    def move_to_error(self, file_path: str):
        p = Path(file_path)
        dest = self.error_dir / p.name
        if p.exists():
            shutil.move(str(p), str(dest))
        return str(dest)
        
    def generate_job_ticket(self, job_id: str, file_paths: list, dest_dir: Path):
        """Generates a simple XML Job Ticket (JDF lite) for the RIP"""
        ticket_path = dest_dir / f"job_ticket_{str(job_id)[:8]}.xml"
        try:
            with open(ticket_path, "w", encoding="utf-8") as f:
                f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
                f.write(f'<JobTicket JobID="{job_id}" Date="{datetime.now().isoformat()}">\n')
                f.write('  <Files>\n')
                for fp in file_paths:
                    f.write(f'    <File Path="{Path(fp).name}" />\n')
                f.write('  </Files>\n')
                f.write('</JobTicket>\n')
            return str(ticket_path)
        except Exception as e:
            logger.error(f"Job Ticket non généré : {e}")
            return None

    def copy_to_rip_hot_folder(self, file_paths: list, rip_dir: str):
        """Copies final files to an external RIP hot folder"""
        rip_path = Path(rip_dir)
        rip_path.mkdir(parents=True, exist_ok=True)
        copied = []
        for fp in file_paths:
            p = Path(fp)
            if p.exists():
                dest = rip_path / p.name
                shutil.copy(str(p), str(dest))
                copied.append(str(dest))
        return copied
        
    def archive_files(self, job_name: str, file_paths: list):
        """Zips the original source files into Archive/YYYY/MM/DD/"""
        today = datetime.now()
        day_dir = self.archive_dir / str(today.year) / f"{today.month:02d}" / f"{today.day:02d}"
        day_dir.mkdir(parents=True, exist_ok=True)
        
        zip_path = day_dir / f"{job_name}.zip"
        
        try:
            archived: dict[str, Path] = {}
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for fp in file_paths:
                    p = Path(fp)
                    if p.exists():
                        zipf.write(str(p), p.name)
                        archived[p.name] = p

            # Never delete an original before the archive is PROVEN readable.
            # A disk filling up mid-write yields a truncated zip without always
            # raising, and the previous code deleted the sources regardless —
            # the archive was unusable and the files were gone for good.
            self._verify_archive(zip_path, archived)

            for p in archived.values():
                if p.exists():
                    p.unlink()

            return str(zip_path)
        except Exception as e:
            logger.error(f"Archivage de « {job_name} » abandonné, "
                         f"originaux conservés : {e}")
            return None

    @staticmethod
    def _verify_archive(zip_path: Path, expected: dict) -> None:
        """Raises unless `zip_path` reopens, holds every expected member and
        passes its CRC checks. Deliberately strict: this is the last gate
        before the source files are destroyed."""
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            corrupt = zipf.testzip()
            if corrupt is not None:
                raise OSError(f"archive corrompue (membre « {corrupt} »)")
            missing = set(expected) - set(zipf.namelist())
            if missing:
                raise OSError(f"archive incomplète, manquant : {sorted(missing)}")
            for name, source in expected.items():
                info = zipf.getinfo(name)
                actual = source.stat().st_size
                if info.file_size != actual:
                    raise OSError(
                        f"« {name} » tronqué dans l'archive "
                        f"({info.file_size} au lieu de {actual} octets)"
                    )
            
    def cleanup_archives(self):
        """Deletes archives older than X days"""
        days = int(self.config.get("output", "archive_days") or 15)
        cutoff_date = datetime.now() - timedelta(days=days)
        
        # Traverse YYYY/MM/DD structure
        if not self.archive_dir.exists():
            return
            
        for year_dir in self.archive_dir.iterdir():
            if not year_dir.is_dir(): continue
            for month_dir in year_dir.iterdir():
                if not month_dir.is_dir(): continue
                for day_dir in month_dir.iterdir():
                    if not day_dir.is_dir(): continue
                    
                    try:
                        folder_date = datetime(int(year_dir.name), int(month_dir.name), int(day_dir.name))
                        if folder_date < cutoff_date:
                            shutil.rmtree(str(day_dir))
                    except ValueError:
                        pass # Ignore incorrectly named folders
                        
        # Clean empty month/year folders
        for year_dir in self.archive_dir.iterdir():
            if not year_dir.is_dir(): continue
            for month_dir in year_dir.iterdir():
                if month_dir.is_dir() and not any(month_dir.iterdir()):
                    month_dir.rmdir()
            if not any(year_dir.iterdir()):
                year_dir.rmdir()
