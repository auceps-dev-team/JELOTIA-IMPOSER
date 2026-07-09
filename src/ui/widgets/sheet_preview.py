
from typing import List, Optional

import fitz  # PyMuPDF
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.models.domain import JobSettings, Sheet


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
        self.setBackgroundBrush(Qt.GlobalColor.darkGray)
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
        self.current_pdf_path = None

        # Multi-sheet job state (see load_job())
        self.job_name: Optional[str] = None
        self.sheets: List[Sheet] = []
        self.settings: Optional[JobSettings] = None
        self.current_index = 0

        self.editor_widget = None  # lazily-created SheetEditorWidget for the current sheet

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

        # Content stack: raster preview (index 0) vs interactive editor (index 1)
        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self.view)
        self.main_layout.addWidget(self.content_stack)

    def setup_toolbar(self):
        self.toolbar_layout = QHBoxLayout()
        self.toolbar_layout.setContentsMargins(10, 10, 10, 10)

        self.info_label = QLabel("Aucun aperçu")
        self.info_label.setStyleSheet("font-weight: bold;")

        self.btn_prev = QPushButton("◀ Précédent")
        self.sheet_counter_label = QLabel("")
        self.btn_next = QPushButton("Suivant ▶")
        self.btn_prev.clicked.connect(self._show_previous_sheet)
        self.btn_next.clicked.connect(self._show_next_sheet)

        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_out = QPushButton("-")
        self.btn_fit = QPushButton("Ajuster")
        self.btn_edit = QPushButton("Éditer la disposition")
        self.btn_edit.setCheckable(True)
        self.btn_export = QPushButton("Exporter la planche")
        self.btn_export_all = QPushButton("Exporter tout")

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
        self.toolbar_layout.addWidget(self.btn_zoom_in)
        self.toolbar_layout.addWidget(self.btn_zoom_out)
        self.toolbar_layout.addWidget(self.btn_fit)
        self.toolbar_layout.addWidget(self.btn_edit)
        self.toolbar_layout.addWidget(self.btn_export)
        self.toolbar_layout.addWidget(self.btn_export_all)

        # Overlay wrapper
        self.toolbar_widget = QWidget()
        self.toolbar_widget.setLayout(self.toolbar_layout)
        self.main_layout.addWidget(self.toolbar_widget)

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
            return

        total = len(self.sheets)
        self.sheet_counter_label.setText(f"Planche {self.current_index + 1}/{total}")
        self.btn_prev.setEnabled(self.current_index > 0)
        self.btn_next.setEnabled(self.current_index < total - 1)

        sheet = self.sheets[self.current_index]
        if sheet.export_path and sheet.export_path.exists():
            self.load_pdf(str(sheet.export_path), fill_rate=sheet.fill_rate)
        else:
            self.info_label.setText(f"Planche {sheet.sheet_number} — fichier introuvable")

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
        self.current_pdf_path = pdf_path
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

    def export_pdf(self):
        if not self.current_pdf_path:
            return
        save_path, _ = QFileDialog.getSaveFileName(self, "Exporter PDF", "", "PDF Files (*.pdf)")
        if save_path:
            import shutil
            try:
                shutil.copy2(self.current_pdf_path, save_path)
                QMessageBox.information(self, "Succès", f"PDF exporté vers {save_path}")
            except Exception as e:
                QMessageBox.warning(self, "Erreur", f"Erreur lors de l'exportation: {e}")

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

        self.editor_widget = SheetEditorWidget(sheet, self)
        self.editor_widget.applied.connect(self._apply_edit)
        self.editor_widget.cancelled.connect(lambda: self._teardown_editor(revert=False))

        self.content_stack.addWidget(self.editor_widget)
        self.content_stack.setCurrentWidget(self.editor_widget)

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
        except Exception as e:
            QMessageBox.warning(self, "Erreur", f"Échec de la régénération de la planche : {e}")
        finally:
            QApplication.restoreOverrideCursor()

        self._teardown_editor(revert=False)  # keep the applied positions
        self._show_current_sheet()
