from pathlib import Path
from typing import List

from PySide6.QtCore import Qt, QThread, Signal
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


class _ExportWorker(QThread):
    """Exporte les planches hors du thread d'interface.

    L'export était synchrone : sur un lot volumineux Windows signalait la
    fenêtre « Ne répond pas », et l'opérateur — ne sachant pas si le programme
    travaillait ou avait planté — était incité à le tuer, ce qui pouvait laisser
    des fichiers à mi-chemin. Même patron que _BatchWorker (qr_batch_dialog).
    """

    progress = Signal(int, int, str)   # fait, total, libellé
    done = Signal(int, list)           # fichiers produits, erreurs

    def __init__(self, sheets, settings, formats, dest, job_name, parent=None):
        super().__init__(parent)
        self._sheets = list(sheets)
        self._settings = settings
        self._formats = formats
        self._dest = dest
        self._job_name = job_name
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        service = SheetExportService()
        produced = 0
        errors: List[str] = []
        total = len(self._sheets)
        for index, sheet in enumerate(self._sheets):
            if self._cancel:
                break
            self.progress.emit(index, total, f"Planche {sheet.sheet_number}...")
            try:
                results = service.convert_and_export(
                    sheet, self._settings, self._formats, self._dest,
                    job_name=self._job_name,
                )
                produced += len(results)
            except Exception as e:
                errors.append(f"Planche {sheet.sheet_number}: {e}")
        self.progress.emit(total, total, "")
        self.done.emit(produced, errors)


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

        self._progress = QProgressDialog("Export en cours...", "Annuler", 0, len(self.sheets), self)
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(0)

        self._worker = _ExportWorker(
            self.sheets, self.settings, formats, dest, self.job_name, parent=self
        )
        self._progress.canceled.connect(self._worker.cancel)
        self._worker.progress.connect(self._on_export_progress)
        self._worker.done.connect(lambda produced, errors: self._on_export_done(produced, errors, dest))
        self._worker.start()

    def _on_export_progress(self, done: int, total: int, label: str):
        self._progress.setValue(done)
        if label:
            self._progress.setLabelText(label)

    def _on_export_done(self, produced: int, errors: list, dest: Path):
        self._progress.close()
        if errors:
            QMessageBox.warning(
                self,
                "Export terminé avec erreurs",
                f"{produced} fichier(s) généré(s).\n\nErreurs :\n"
                + "\n".join(errors),
            )
        else:
            QMessageBox.information(
                self, "Export terminé",
                f"{produced} fichier(s) généré(s) dans :\n{dest}",
            )
        self.accept()
