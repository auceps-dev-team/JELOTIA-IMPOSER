from pathlib import Path
from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
)

from src.core.models.domain import JobSettings, Sheet
from src.core.sheet_export_service import SheetExportService
from src.utils.config import config

_PDF_FALLBACK_FORMAT = "PDF/X-4"


class BatchExportDialog(QDialog):
    """Exports every Sheet of a job, one file per sheet per checked format."""

    def __init__(self, job_name: str, sheets: List[Sheet], settings: JobSettings, parent=None):
        super().__init__(parent)
        self.job_name = job_name
        self.sheets = sheets
        self.settings = settings
        self.setWindowTitle(f"Export groupé — {job_name}")
        self.resize(420, 280)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        info = QLabel(
            f"{len(self.sheets)} planche(s) seront exportées, une par planche, "
            "dans chaque format coché ci-dessous."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        layout.addWidget(QLabel("Formats :"))
        self.chk_pdf = QCheckBox("PDF")
        self.chk_pdf.setChecked(True)
        self.chk_tiff = QCheckBox("TIFF")
        self.chk_jpeg = QCheckBox("JPEG")
        for chk in (self.chk_pdf, self.chk_tiff, self.chk_jpeg):
            layout.addWidget(chk)

        layout.addWidget(QLabel("Dossier de destination :"))
        dest_row = QHBoxLayout()
        default_dest = str((config.output_dir / self.job_name)) if self.job_name else str(config.output_dir)
        self.dest_input = QLineEdit(default_dest)
        btn_browse = QPushButton("Parcourir...")
        btn_browse.clicked.connect(self._browse)
        dest_row.addWidget(self.dest_input)
        dest_row.addWidget(btn_browse)
        layout.addLayout(dest_row)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_export = QPushButton("Exporter")
        btn_export.setObjectName("primary")
        btn_export.clicked.connect(self._run_export)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_export)
        layout.addLayout(btn_row)

    def _browse(self):
        chosen = QFileDialog.getExistingDirectory(
            self, "Choisir le dossier de destination", self.dest_input.text()
        )
        if chosen:
            self.dest_input.setText(chosen)

    def _selected_formats(self) -> List[str]:
        formats = []
        if self.chk_pdf.isChecked():
            current = self.settings.export_format.upper()
            formats.append(self.settings.export_format if "PDF" in current else _PDF_FALLBACK_FORMAT)
        if self.chk_tiff.isChecked():
            formats.append("TIFF")
        if self.chk_jpeg.isChecked():
            formats.append("JPEG")
        return formats

    def _run_export(self):
        formats = self._selected_formats()
        if not formats:
            QMessageBox.warning(self, "Aucun format", "Sélectionnez au moins un format d'export.")
            return

        dest = Path(self.dest_input.text().strip())
        if not str(dest):
            QMessageBox.warning(self, "Dossier manquant", "Choisissez un dossier de destination.")
            return

        service = SheetExportService()
        produced = 0
        errors: List[str] = []

        progress = QProgressDialog("Export en cours...", "Annuler", 0, len(self.sheets), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        for i, sheet in enumerate(self.sheets):
            if progress.wasCanceled():
                break
            progress.setValue(i)
            progress.setLabelText(f"Planche {sheet.sheet_number}...")

            work_dir = config.processing_dir / f"batch_export_{sheet.id}"
            try:
                results = service.regenerate_and_export(
                    sheet, self.settings, formats, dest, work_dir, job_name=self.job_name
                )
                produced += len(results)
            except Exception as e:
                errors.append(f"Planche {sheet.sheet_number}: {e}")

        progress.setValue(len(self.sheets))

        if errors:
            QMessageBox.warning(
                self,
                "Export terminé avec erreurs",
                f"{produced} fichier(s) généré(s).\n\nErreurs :\n" + "\n".join(errors),
            )
        else:
            QMessageBox.information(
                self, "Export terminé", f"{produced} fichier(s) généré(s) dans :\n{dest}"
            )
        self.accept()
