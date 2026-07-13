from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from src.core.engines.qr_batch import (
    BatchResult,
    ColumnMapping,
    build_plan,
    generate_batch,
    imposition_payload,
    zip_outputs,
)
from src.core.engines.qr_engine import QREngine
from src.core.engines.qr_import import TableImportError, read_table
from src.core.models.domain import QRCodeSettings
from src.ui.theme import ThemeManager

_T = ThemeManager
_NONE_LABEL = "— aucune —"


class _BatchWorker(QThread):
    """Runs generate_batch off the UI thread, relaying progress and the final
    result via signals (Qt queues them back to the UI thread)."""

    progress = Signal(int, int)
    done = Signal(object)  # BatchResult

    def __init__(self, engine, items, settings, out_dir, formats, template=None, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._items = items
        self._settings = settings
        self._out_dir = out_dir
        self._formats = formats
        self._template = template
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        result = generate_batch(
            self._engine, self._items, self._settings, self._out_dir, self._formats,
            progress_cb=lambda done, total: self.progress.emit(done, total),
            should_cancel=lambda: self._cancel,
            template=self._template,
        )
        self.done.emit(result)


class QRBatchDialog(QDialog):
    """Import Excel/CSV → map columns → generate one QR per row (in the style
    configured in the F5·QR module), with a background run and ZIP export.
    A finished batch can be handed straight to the imposition pipeline via
    `imposition_requested` (job name, file paths, overrides)."""

    imposition_requested = Signal(str, list, dict)

    def __init__(self, settings: QRCodeSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Génération par lot")
        self.resize(620, 560)
        self.engine = QREngine()
        self.settings = settings

        self.headers: List[str] = []
        self.rows: list[dict] = []
        self._import_stem = "LOT"
        self.out_dir: Optional[Path] = self._default_out_dir()
        self.worker: Optional[_BatchWorker] = None
        self.result: Optional[BatchResult] = None

        self.setup_ui()
        self._update_summary()

    # ------------------------------------------------------------------ #
    #  Layout                                                              #
    # ------------------------------------------------------------------ #

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Import
        layout.addWidget(self._title("1 · IMPORTER LES DONNÉES"))
        import_row = QHBoxLayout()
        self.btn_import = QPushButton("Importer Excel/CSV…")
        self.btn_import.clicked.connect(self._import_file)
        self.file_label = QLabel("Aucun fichier importé")
        self.file_label.setStyleSheet(f"color:{_T.TEXT_MUTE}; border:none;")
        import_row.addWidget(self.btn_import)
        import_row.addWidget(self.file_label, 1)
        layout.addLayout(import_row)

        # Mapping
        layout.addWidget(self._title("2 · CORRESPONDANCE DES COLONNES"))
        form = QFormLayout()
        form.setSpacing(10)
        self.combo_url = QComboBox()
        self.combo_name = QComboBox()
        self.combo_qty = QComboBox()
        for combo in (self.combo_url, self.combo_name, self.combo_qty):
            combo.currentIndexChanged.connect(self._update_summary)
        form.addRow("Colonne du lien * :", self.combo_url)
        form.addRow("Colonne du nom de fichier :", self.combo_name)
        form.addRow("Colonne de la quantité :", self.combo_qty)
        layout.addLayout(form)

        # Options
        layout.addWidget(self._title("3 · OPTIONS"))
        self.chk_dedup = QCheckBox("Rejeter les liens en doublon")
        self.chk_dedup.toggled.connect(self._update_summary)
        layout.addWidget(self.chk_dedup)

        tpl_row = QHBoxLayout()
        tpl_row.addWidget(QLabel("Modèle :"))
        self.combo_template = QComboBox()
        self.combo_template.currentIndexChanged.connect(self._on_template_changed)
        tpl_row.addWidget(self.combo_template, 1)
        layout.addLayout(tpl_row)
        self._populate_templates()

        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("Formats :"))
        self.chk_png = QCheckBox("PNG")
        self.chk_svg = QCheckBox("SVG")
        self.chk_pdf = QCheckBox("PDF")
        self.chk_pdf.setChecked(True)
        for c in (self.chk_png, self.chk_svg, self.chk_pdf):
            fmt_row.addWidget(c)
        fmt_row.addStretch()
        layout.addLayout(fmt_row)

        out_row = QHBoxLayout()
        self.btn_out = QPushButton("Dossier de sortie…")
        self.btn_out.clicked.connect(self._pick_out_dir)
        self.out_label = QLabel(str(self.out_dir) if self.out_dir else "(non défini)")
        self.out_label.setStyleSheet(f"color:{_T.TEXT_MUTE}; border:none;")
        out_row.addWidget(self.btn_out)
        out_row.addWidget(self.out_label, 1)
        layout.addLayout(out_row)

        # Summary + progress
        layout.addStretch()
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet(f"color:{_T.TEXT_2}; border:none; font-size:12px;")
        layout.addWidget(self.summary_label)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color:{_T.TEXT_MUTE}; border:none; font-size:11px;")
        layout.addWidget(self.status_label)

        # Actions
        actions = QHBoxLayout()
        self.btn_zip = QPushButton("Exporter en ZIP")
        self.btn_zip.setEnabled(False)
        self.btn_zip.clicked.connect(self._export_zip)
        self.btn_impose = QPushButton("[IMPOSER LE LOT →]")
        self.btn_impose.setEnabled(False)
        self.btn_impose.setToolTip(
            "Crée un job d'imposition à partir des fichiers générés : "
            "nesting sur planche puis export RIP, quantités du fichier importé respectées."
        )
        self.btn_impose.clicked.connect(self._request_imposition)
        self.btn_generate = QPushButton("[GÉNÉRER LE LOT]")
        self.btn_generate.setObjectName("primary")
        self.btn_generate.clicked.connect(self._start_or_cancel)
        self.btn_close = QPushButton("Fermer")
        self.btn_close.clicked.connect(self.reject)
        actions.addWidget(self.btn_zip)
        actions.addWidget(self.btn_impose)
        actions.addStretch()
        actions.addWidget(self.btn_generate)
        actions.addWidget(self.btn_close)
        layout.addLayout(actions)

    def _title(self, text: str) -> QLabel:
        lbl = QLabel(f"┌─[ {text} ]──")
        lbl.setStyleSheet(
            f"color:{_T.ACCENT_TEXT}; font-weight:600; font-size:12px; "
            f"letter-spacing:1.5px; border:none;"
        )
        return lbl

    # ------------------------------------------------------------------ #
    #  Import & mapping                                                    #
    # ------------------------------------------------------------------ #

    def _populate_templates(self):
        """Card templates saved from the designer; with one selected, each row
        becomes a composed card PDF (fond + QR + textes variables) instead of
        a bare QR file."""
        from src.core.engines.template_composer import TemplateStore

        self.combo_template.blockSignals(True)
        self.combo_template.clear()
        self.combo_template.addItem("— aucun (QR seul) —", None)
        try:
            for tpl in TemplateStore().list():
                self.combo_template.addItem(tpl.name, str(tpl.id))
        except Exception:
            pass
        self.combo_template.blockSignals(False)

    def _on_template_changed(self):
        # Template output is always a composed vector PDF.
        use_template = self.combo_template.currentData() is not None
        for chk in (self.chk_png, self.chk_svg, self.chk_pdf):
            chk.setEnabled(not use_template)

    def _current_template(self):
        template_id = self.combo_template.currentData()
        if template_id is None:
            return None
        from src.core.engines.template_composer import TemplateStore

        try:
            return TemplateStore().load(template_id)
        except Exception as e:
            QMessageBox.warning(self, "Modèle illisible", str(e))
            return None

    def _default_out_dir(self) -> Optional[Path]:
        try:
            from src.utils.config import config

            return Path(config.output_dir) / "QR_lot"
        except Exception:
            return None

    def _import_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Importer un fichier", "",
            "Tableurs (*.xlsx *.xlsm *.csv *.tsv);;Tous (*.*)",
        )
        if not path:
            return
        try:
            self.headers, self.rows = read_table(Path(path))
        except TableImportError as e:
            QMessageBox.warning(self, "Import impossible", str(e))
            return

        if not self.headers:
            QMessageBox.warning(self, "Fichier vide", "Aucune colonne détectée.")
            return

        self._import_stem = Path(path).stem
        self.file_label.setText(f"{Path(path).name} — {len(self.rows)} ligne(s)")
        self._populate_mapping()
        self._update_summary()

    def _populate_mapping(self):
        self.combo_url.clear()
        self.combo_name.clear()
        self.combo_qty.clear()
        self.combo_url.addItems(self.headers)
        self.combo_name.addItems([_NONE_LABEL] + self.headers)
        self.combo_qty.addItems([_NONE_LABEL] + self.headers)

        # Best-effort auto-detection from common header names.
        self._auto_select(self.combo_url, ("lien", "url", "link", "adresse"))
        self._auto_select(
            self.combo_name, ("nom", "name", "fichier", "file", "id"), offset=True
        )
        self._auto_select(
            self.combo_qty, ("qte", "quantit", "quantity", "qty", "nombre"), offset=True
        )

    def _auto_select(self, combo: QComboBox, keywords, offset: bool = False):
        for i, header in enumerate(self.headers):
            if any(k in header.lower() for k in keywords):
                combo.setCurrentIndex(i + 1 if offset else i)
                return

    def _mapping(self) -> Optional[ColumnMapping]:
        if not self.headers or self.combo_url.currentIndex() < 0:
            return None
        name = self.combo_name.currentText()
        qty = self.combo_qty.currentText()
        return ColumnMapping(
            url_col=self.combo_url.currentText(),
            filename_col=None if name == _NONE_LABEL else name,
            quantity_col=None if qty == _NONE_LABEL else qty,
        )

    def _current_plan(self):
        mapping = self._mapping()
        if mapping is None:
            return None
        return build_plan(self.rows, mapping, allow_duplicates=not self.chk_dedup.isChecked())

    def _selected_formats(self) -> List[str]:
        formats = []
        if self.chk_png.isChecked():
            formats.append("PNG")
        if self.chk_svg.isChecked():
            formats.append("SVG")
        if self.chk_pdf.isChecked():
            formats.append("PDF")
        return formats

    def _update_summary(self):
        plan = self._current_plan()
        if plan is None:
            self.summary_label.setText("Importez un fichier et choisissez la colonne du lien.")
            return
        self.summary_label.setText(
            f"{len(self.rows)} ligne(s) → {plan.total} QR à générer  ·  "
            f"{plan.duplicates_skipped} doublon(s)  ·  {plan.empty_skipped} vide(s)"
        )

    def _pick_out_dir(self):
        start = str(self.out_dir) if self.out_dir else ""
        path = QFileDialog.getExistingDirectory(self, "Dossier de sortie", start)
        if path:
            self.out_dir = Path(path)
            self.out_label.setText(str(self.out_dir))

    # ------------------------------------------------------------------ #
    #  Generation                                                          #
    # ------------------------------------------------------------------ #

    def _start_or_cancel(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.btn_generate.setEnabled(False)
            self.status_label.setText("Annulation…")
            return

        plan = self._current_plan()
        if plan is None or plan.total == 0:
            QMessageBox.information(self, "Rien à générer", "Aucun QR code à produire.")
            return
        template = self._current_template()
        formats = self._selected_formats()
        if template is None and not formats:
            QMessageBox.information(self, "Format manquant", "Sélectionnez au moins un format.")
            return
        if self.out_dir is None:
            QMessageBox.information(self, "Dossier manquant", "Choisissez un dossier de sortie.")
            return

        self._set_running(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, plan.total)
        self.progress.setValue(0)
        self.status_label.setText("Génération en cours…")

        self.worker = _BatchWorker(
            self.engine, plan.items, self.settings, self.out_dir, formats,
            template=template, parent=self,
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_done)
        self.worker.start()

    def _on_progress(self, done: int, total: int):
        self.progress.setValue(done)
        self.status_label.setText(f"Génération… {done}/{total}")

    def _on_done(self, result: BatchResult):
        self.result = result
        self._set_running(False)
        self.btn_generate.setEnabled(True)
        self.btn_zip.setEnabled(result.succeeded > 0)
        self.btn_impose.setEnabled(result.succeeded > 0)

        parts = [f"{result.succeeded} généré(s)"]
        if result.failed:
            parts.append(f"{result.failed} échec(s)")
        if result.cancelled:
            parts.append("annulé")
        self.status_label.setText(
            "Terminé : " + ", ".join(parts) + f"  →  {result.out_dir}"
        )

    def _set_running(self, running: bool):
        self.btn_generate.setText("[ANNULER]" if running else "[GÉNÉRER LE LOT]")
        for w in (self.btn_import, self.btn_out, self.chk_dedup, self.chk_png,
                  self.chk_svg, self.chk_pdf, self.combo_url, self.combo_name,
                  self.combo_qty, self.combo_template):
            w.setEnabled(not running)
        if not running:
            # Re-apply the template rule (formats stay locked with a template).
            self._on_template_changed()

    def _request_imposition(self):
        """Hands the generated files to the imposition pipeline: one job whose
        per-file quantities come from the imported quantity column, so the
        sheets carry exactly the ordered number of each card."""
        if not self.result or self.result.succeeded == 0:
            return
        paths, quantities = imposition_payload(self.result)
        if not paths:
            return
        import datetime

        job_name = f"QR-{self._import_stem}-{datetime.datetime.now():%H%M%S}"
        self.imposition_requested.emit(job_name, paths, {"quantities": quantities})
        self.accept()

    def _export_zip(self):
        if not self.result or self.result.succeeded == 0:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter en ZIP", "qr_lot.zip", "Archive ZIP (*.zip)"
        )
        if not path:
            return
        try:
            zip_outputs(self.result.out_dir, Path(path))
        except OSError as e:
            QMessageBox.warning(self, "Erreur", f"Échec de l'export ZIP : {e}")
            return
        QMessageBox.information(self, "Succès", f"Archive créée :\n{path}")

    def reject(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        super().reject()
