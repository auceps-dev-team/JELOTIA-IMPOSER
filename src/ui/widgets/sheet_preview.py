
from pathlib import Path
from typing import List, Optional

import fitz  # PyMuPDF
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.models.domain import (
    ColorMode,
    FileFormat,
    FileItem,
    JobSettings,
    PreflightError,
    PreflightStatus,
    Sheet,
)
from src.database.repository import DatabaseRepository
from src.ui.theme import ThemeManager

_T = ThemeManager


def _file_item_from_model(model) -> FileItem:
    """Reconstructs a domain FileItem from a persisted FileItemModel row —
    needed because update_job_files() takes full domain objects (with real
    enums and PreflightError instances), while get_job() returns raw ORM rows
    (plain strings/dicts)."""
    return FileItem(
        id=model.id,
        job_id=model.job_id,
        path=Path(model.path),
        format=FileFormat(model.format),
        width_mm=model.width_mm,
        height_mm=model.height_mm,
        dpi=model.dpi,
        color_mode=ColorMode(model.color_mode),
        quantity=model.quantity,
        preflight_status=PreflightStatus(model.preflight_status),
        preflight_errors=[PreflightError(**e) for e in (model.preflight_errors or [])],
    )


class ZoomableView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QColor(_T.BG_APP))
        self.setFrameShape(QFrame.Shape.NoFrame)

        self._zoom = 0

    def wheelEvent(self, event: QWheelEvent):
        if event.angleDelta().y() > 0:
            factor = 1.25
            self._zoom += 1
        else:
            factor = 0.8
            self._zoom -= 1

        # Prevent zooming out too much
        if self._zoom < -10:
            self._zoom = -10
            return

        self.scale(factor, factor)

    def fit_in_view(self):
        self._zoom = 0
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

class SheetPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Multi-sheet job state (see load_job())
        self.job_name: Optional[str] = None
        self.sheets: List[Sheet] = []
        self.settings: Optional[JobSettings] = None
        self.current_index = 0

        self.editor_widget = None  # lazily-created SheetEditorWidget for the current sheet
        self.db = DatabaseRepository()

        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # View area (must be created before toolbar so buttons can reference self.view)
        self.scene = QGraphicsScene(self)
        self.view = ZoomableView(self.scene)
        self.pixmap_item = QGraphicsPixmapItem()
        self.scene.addItem(self.pixmap_item)

        # Toolbar
        self.setup_toolbar()

        # Body: content stack (raster preview vs interactive editor) + the
        # TÉLÉMÉTRIE.PLANCHE side panel.
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self.view)
        body.addWidget(self.content_stack, 1)

        self.telemetry_panel = self._build_telemetry_panel()
        body.addWidget(self.telemetry_panel)

        self.main_layout.addLayout(body, 1)

    def setup_toolbar(self):
        self.toolbar_layout = QHBoxLayout()
        self.toolbar_layout.setContentsMargins(16, 10, 16, 10)
        self.toolbar_layout.setSpacing(8)

        self.info_label = QLabel("Aucun aperçu")
        # Informational only: an explicit minimum lets the toolbar compress it
        # instead of forcing the whole window wider than small/scaled screens.
        self.info_label.setMinimumWidth(120)

        self.btn_prev = QPushButton("◀ PREC")
        self.sheet_counter_label = QLabel("")
        self.sheet_counter_label.setStyleSheet(f"color:{_T.ACCENT_TEXT}; font-weight:600; padding:0 8px;")
        self.btn_next = QPushButton("SUIV ▶")
        self.btn_prev.clicked.connect(self._show_previous_sheet)
        self.btn_next.clicked.connect(self._show_next_sheet)

        self.btn_zoom_in = QPushButton("＋")
        self.btn_zoom_out = QPushButton("−")
        self.btn_fit = QPushButton("AJUSTER")
        self.btn_edit = QPushButton("ÉDITER.DISPO")
        self.btn_edit.setCheckable(True)
        self.btn_export = QPushButton("[EXPORT PLANCHE]")
        self.btn_export_all = QPushButton("[EXPORT TOUT]")
        self.btn_export_all.setObjectName("primary")

        self.btn_zoom_in.clicked.connect(lambda: self.view.scale(1.25, 1.25))
        self.btn_zoom_out.clicked.connect(lambda: self.view.scale(0.8, 0.8))
        self.btn_fit.clicked.connect(self.view.fit_in_view)
        self.btn_edit.toggled.connect(self._toggle_edit_mode)
        self.btn_export.clicked.connect(self.export_pdf)
        self.btn_export_all.clicked.connect(self.open_batch_export)

        self.toolbar_layout.addWidget(self.info_label)
        self.toolbar_layout.addStretch()
        self.toolbar_layout.addWidget(self.btn_prev)
        self.toolbar_layout.addWidget(self.sheet_counter_label)
        self.toolbar_layout.addWidget(self.btn_next)
        self.toolbar_layout.addStretch()
        self.toolbar_layout.addWidget(self.btn_zoom_out)
        self.toolbar_layout.addWidget(self.btn_fit)
        self.toolbar_layout.addWidget(self.btn_zoom_in)
        self.toolbar_layout.addWidget(self.btn_edit)
        self.toolbar_layout.addWidget(self.btn_export)
        self.toolbar_layout.addWidget(self.btn_export_all)

        # Overlay wrapper
        self.toolbar_widget = QWidget()
        self.toolbar_widget.setLayout(self.toolbar_layout)
        self.toolbar_widget.setStyleSheet(
            f"background-color:{_T.BG_PANEL}; border-bottom:1px solid {_T.BORDER};"
        )
        self.main_layout.addWidget(self.toolbar_widget)

    def _build_telemetry_panel(self) -> QFrame:
        panel = QFrame()
        panel.setFixedWidth(300)
        panel.setStyleSheet(
            f"QFrame {{ background-color:{_T.BG_PANEL}; border-left:1px solid {_T.BORDER}; }}"
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(6)

        title = QLabel("┌ TÉLÉMÉTRIE.PLANCHE")
        title.setStyleSheet(
            f"color:{_T.TEXT_2}; font-weight:600; font-size:12px; letter-spacing:1.5px; "
            f"border:none; margin-bottom:6px;"
        )
        layout.addWidget(title)

        self._telemetry_rows: dict[str, QLabel] = {}
        for key, label in (
            ("format", "FORMAT"),
            ("poses", "POSES"),
            ("rotation", "ROTATION"),
            ("espacement", "ESPACEMENT"),
            ("remplissage", "REMPLISSAGE"),
            ("chutes", "CHUTES"),
            ("sortie", "SORTIE"),
            ("profil", "PROFIL"),
        ):
            row = QLabel("—")
            row.setStyleSheet("border:none; font-size:12px;")
            layout.addWidget(row)
            self._telemetry_rows[key] = row
            if key == "remplissage":
                self._telemetry_bar = QProgressBar()
                self._telemetry_bar.setFixedHeight(8)
                self._telemetry_bar.setTextVisible(False)
                self._telemetry_bar.setRange(0, 100)
                layout.addWidget(self._telemetry_bar)

        layout.addStretch()
        return panel

    def _telemetry_line(self, label: str, value: str, value_color: str = None) -> str:
        pad = "." * max(1, 14 - len(label))
        value_color = value_color or _T.TEXT_1
        return (
            f'<span style="color:{_T.TEXT_MUTE}">{label}{pad}</span> '
            f'<span style="color:{value_color}">{value}</span>'
        )

    def _update_telemetry(self) -> None:
        sheet = self.current_sheet
        if sheet is None or self.settings is None:
            for row in self._telemetry_rows.values():
                row.setText("—")
            self._telemetry_bar.setValue(0)
            return

        from src.utils.config_manager import ConfigManager

        poses = len(sheet.items)
        rotated = sum(1 for it in sheet.items if it.rotated)
        fill = sheet.fill_rate
        icc = ConfigManager().get("export", "icc_profile") or "—"

        rows = self._telemetry_rows
        rows["format"].setText(self._telemetry_line("FORMAT", f"{sheet.width_mm:.0f}×{sheet.height_mm:.0f}"))
        rows["poses"].setText(self._telemetry_line("POSES", str(poses)))
        rows["rotation"].setText(self._telemetry_line("ROTATION", f"{rotated} AUTO", _T.STATE_OK))
        rows["espacement"].setText(self._telemetry_line("ESPACEMENT", f"{self.settings.gap_mm:.0f} MM"))
        rows["remplissage"].setText(self._telemetry_line("REMPLISSAGE", f"{fill:.1f}%", _T.ACCENT_TEXT))
        rows["chutes"].setText(self._telemetry_line("CHUTES", f"{100 - fill:.1f}%"))
        rows["sortie"].setText(
            self._telemetry_line("SORTIE", f"{self.settings.export_format}/{self.settings.export_dpi}DPI")
        )
        rows["profil"].setText(self._telemetry_line("PROFIL", icc))
        self._telemetry_bar.setValue(round(max(0.0, min(100.0, fill))))

    # ------------------------------------------------------------------ #
    #  Multi-sheet job loading / navigation                                #
    # ------------------------------------------------------------------ #

    def load_job(self, job_name: str, sheets: List[Sheet], settings: Optional[JobSettings]):
        """Loads all sheets generated for a job and shows the first one, with
        Previous/Next navigation across the rest."""
        self.job_name = job_name
        self.sheets = sheets
        self.settings = settings
        self.current_index = 0
        self._teardown_editor(revert=True)
        self._show_current_sheet()

    def _show_current_sheet(self):
        if not self.sheets:
            self.info_label.setText("Aucun aperçu")
            self.sheet_counter_label.setText("")
            self._update_telemetry()
            return

        total = len(self.sheets)
        self.sheet_counter_label.setText(f"PLANCHE {self.current_index + 1:02d}/{total:02d}")
        self.btn_prev.setEnabled(self.current_index > 0)
        self.btn_next.setEnabled(self.current_index < total - 1)

        sheet = self.sheets[self.current_index]
        if sheet.export_path and sheet.export_path.exists():
            self.load_pdf(str(sheet.export_path), fill_rate=sheet.fill_rate)
        else:
            self.info_label.setText(f"Planche {sheet.sheet_number} — fichier introuvable")
        self._update_telemetry()

    def _show_previous_sheet(self):
        if self.current_index > 0:
            self.current_index -= 1
            self._teardown_editor(revert=True)
            self._show_current_sheet()

    def _show_next_sheet(self):
        if self.current_index < len(self.sheets) - 1:
            self.current_index += 1
            self._teardown_editor(revert=True)
            self._show_current_sheet()

    @property
    def current_sheet(self) -> Optional[Sheet]:
        if 0 <= self.current_index < len(self.sheets):
            return self.sheets[self.current_index]
        return None

    # ------------------------------------------------------------------ #
    #  Raster preview                                                      #
    # ------------------------------------------------------------------ #

    def load_pdf(self, pdf_path: str, fill_rate: float = 0.0):
        """Loads a PDF page into the view using PyMuPDF."""
        try:
            doc = fitz.open(pdf_path)
            page = doc[0] # Preview first page
            # Render at 150 DPI for good preview quality
            zoom_matrix = fitz.Matrix(150 / 72, 150 / 72)
            pix = page.get_pixmap(matrix=zoom_matrix, alpha=False)

            # Convert PyMuPDF Pixmap to QImage
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
            qpixmap = QPixmap.fromImage(img)

            self.pixmap_item.setPixmap(qpixmap)
            self.scene.setSceneRect(self.pixmap_item.boundingRect())
            self.view.fit_in_view()

            fill_txt = f" — Taux de remplissage : {fill_rate:.1f}%" if fill_rate is not None else ""
            self.info_label.setText(f"Aperçu{fill_txt}")

        except Exception as e:
            self.info_label.setText(f"Erreur de chargement: {e}")

    # Lets the user pick a target format at export time instead of having to go
    # change it in Settings first: label -> (export_format for ExportEngine, extension, file filter).
    _FORMAT_CHOICES = {
        "PDF": ("PDF", ".pdf", "PDF Files (*.pdf)"),
        "TIFF": ("TIFF", ".tif", "TIFF Files (*.tif *.tiff)"),
        "JPEG": ("JPEG", ".jpg", "JPEG Files (*.jpg)"),
    }

    def _default_format_label(self, sheet: Sheet) -> str:
        ext = Path(sheet.export_path).suffix.lower() if sheet.export_path else ".pdf"
        return {".pdf": "PDF", ".tiff": "TIFF", ".tif": "TIFF", ".jpg": "JPEG", ".jpeg": "JPEG"}.get(ext, "PDF")

    def export_pdf(self):
        sheet = self.current_sheet
        if sheet is None or self.settings is None:
            return

        labels = list(self._FORMAT_CHOICES.keys())
        default_index = labels.index(self._default_format_label(sheet))
        choice, ok = QInputDialog.getItem(
            self, "Exporter la planche", "Format d'export :", labels, default_index, False
        )
        if not ok:
            return

        fmt, ext, file_filter = self._FORMAT_CHOICES[choice]
        if fmt == "PDF":
            # Keep the job's existing PDF flavor (PDF/X-1a, PDF/X-4, ...) if it
            # already is one, instead of downgrading to a plain "PDF" export.
            current = self.settings.export_format.upper()
            fmt = self.settings.export_format if "PDF" in current else "PDF/X-4"

        from src.core.engines.export_engine import _slugify

        base_name = _slugify(self.job_name) if self.job_name else str(sheet.job_id)[:8]
        default_name = f"{base_name}_planche_{sheet.sheet_number:02d}{ext}"

        save_path, _ = QFileDialog.getSaveFileName(self, "Exporter la planche", default_name, file_filter)
        if not save_path:
            return
        if Path(save_path).suffix.lower() != ext:
            save_path = str(Path(save_path).with_suffix(ext))

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        staging_dir = None
        try:
            from src.core.sheet_export_service import SheetExportService
            from src.utils.config import config

            staging_dir = config.processing_dir / f"quick_export_{sheet.id}"

            service = SheetExportService()
            results = service.convert_and_export(
                sheet, self.settings, [fmt], staging_dir, job_name=self.job_name
            )
            generated_path = results[fmt]

            import shutil
            shutil.copy2(generated_path, save_path)
            QMessageBox.information(self, "Succès", f"Planche exportée vers {save_path}")
        except Exception as e:
            QMessageBox.warning(self, "Erreur", f"Erreur lors de l'exportation : {e}")
        finally:
            QApplication.restoreOverrideCursor()
            if staging_dir is not None:
                import shutil
                shutil.rmtree(staging_dir, ignore_errors=True)

    # ------------------------------------------------------------------ #
    #  Grouped multi-format export                                        #
    # ------------------------------------------------------------------ #

    def open_batch_export(self):
        if not self.sheets or not self.settings:
            QMessageBox.information(
                self, "Export groupé", "Aucune planche disponible pour ce job."
            )
            return
        from src.ui.widgets.batch_export_dialog import BatchExportDialog

        dialog = BatchExportDialog(self.job_name, self.sheets, self.settings, self)
        dialog.exec()

    # ------------------------------------------------------------------ #
    #  Manual repositioning                                               #
    # ------------------------------------------------------------------ #

    def _toggle_edit_mode(self, checked: bool):
        if checked:
            self._enter_edit_mode()
        else:
            # Button unchecked directly (not via the editor's own Annuler/Appliquer) — treat as cancel.
            self._teardown_editor(revert=True)

    def _enter_edit_mode(self):
        sheet = self.current_sheet
        if sheet is None or self.settings is None:
            self._set_edit_checked(False)
            return

        from src.ui.widgets.sheet_editor import SheetEditorWidget

        self.editor_widget = SheetEditorWidget(sheet, self.settings, self)
        self.editor_widget.applied.connect(self._apply_edit)
        self.editor_widget.cancelled.connect(lambda: self._teardown_editor(revert=False))

        self.content_stack.addWidget(self.editor_widget)
        self.content_stack.setCurrentWidget(self.editor_widget)
        # The editor's tool bars are the widest row of the window; keeping the
        # 300px telemetry panel beside them can push the window's minimum
        # beyond the screen (Qt then grows the window off-screen and never
        # shrinks it back). Its values are stale during editing anyway.
        self.telemetry_panel.hide()

    def _teardown_editor(self, revert: bool):
        """Removes the editor widget and returns to the raster preview.

        `revert` reverts unsaved position changes; pass False when the editor
        already reverted them itself (Annuler) or the changes were just applied
        (Appliquer) and should be kept.
        """
        if self.editor_widget is None:
            self._set_edit_checked(False)
            return
        if revert:
            self.editor_widget.revert()
        self.content_stack.setCurrentWidget(self.view)
        self.content_stack.removeWidget(self.editor_widget)
        self.editor_widget.deleteLater()
        self.editor_widget = None
        self.telemetry_panel.show()
        self._set_edit_checked(False)

    def _set_edit_checked(self, value: bool):
        self.btn_edit.blockSignals(True)
        self.btn_edit.setChecked(value)
        self.btn_edit.blockSignals(False)

    def _apply_edit(self):
        sheet = self.current_sheet
        if sheet is None or self.settings is None:
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            from src.core.sheet_export_service import SheetExportService
            from src.utils.config import config

            placed_area = sum(it.width_mm * it.height_mm for it in sheet.items)
            sheet_area = sheet.width_mm * sheet.height_mm
            sheet.fill_rate = (placed_area / sheet_area) * 100.0 if sheet_area > 0 else 0.0

            service = SheetExportService()
            output_dir = sheet.export_path.parent if sheet.export_path else config.output_dir
            work_dir = config.processing_dir / f"manual_edit_{sheet.id}"

            results = service.regenerate_and_export(
                sheet, self.settings, [self.settings.export_format], output_dir, work_dir,
                job_name=self.job_name,
            )
            sheet.export_path = next(iter(results.values()))

            # Persist the edit (repositioning, rotation, resize, added items)
            # so it survives an app restart — regenerating the exported PDF
            # alone previously left the DB with the pre-edit layout.
            self.db.update_job_sheets(str(sheet.job_id), self.sheets)

            new_file_items = self.editor_widget.added_file_items if self.editor_widget else []
            if new_file_items:
                job_model = self.db.get_job(str(sheet.job_id))
                existing = [_file_item_from_model(f) for f in job_model.files] if job_model else []
                self.db.update_job_files(str(sheet.job_id), existing + new_file_items)
        except Exception as e:
            QMessageBox.warning(self, "Erreur", f"Échec de la régénération de la planche : {e}")
        finally:
            QApplication.restoreOverrideCursor()

        self._teardown_editor(revert=False)  # keep the applied positions
        self._show_current_sheet()  # also refreshes the telemetry panel
