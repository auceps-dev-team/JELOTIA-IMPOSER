import fitz  # PyMuPDF
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QLabel, QFrame, QSizePolicy, QFileDialog, QMessageBox
)
from PySide6.QtGui import QPixmap, QImage, QPainter, QWheelEvent, QMouseEvent
from PySide6.QtCore import Qt, QPointF
from pathlib import Path

class ZoomableView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setBackgroundBrush(Qt.darkGray)
        self.setFrameShape(QFrame.NoFrame)
        
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
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

class SheetPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_pdf_path = None
        self.setup_ui()
        
    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # Toolbar
        self.setup_toolbar()
        
        # View area
        self.scene = QGraphicsScene(self)
        self.view = ZoomableView(self.scene)
        self.pixmap_item = QGraphicsPixmapItem()
        self.scene.addItem(self.pixmap_item)
        
        self.main_layout.addWidget(self.view)
        
    def setup_toolbar(self):
        self.toolbar_layout = QHBoxLayout()
        self.toolbar_layout.setContentsMargins(10, 10, 10, 10)
        
        self.info_label = QLabel("Aucun aperçu")
        self.info_label.setStyleSheet("color: #cdd6f4; font-weight: bold;")
        
        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_out = QPushButton("-")
        self.btn_fit = QPushButton("Ajuster")
        self.btn_export = QPushButton("Exporter PDF")
        
        for btn in [self.btn_zoom_in, self.btn_zoom_out, self.btn_fit, self.btn_export]:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #313244;
                    color: #cdd6f4;
                    padding: 5px 10px;
                    border-radius: 4px;
                }
                QPushButton:hover { background-color: #45475a; }
            """)
            
        self.btn_zoom_in.clicked.connect(lambda: self.view.scale(1.25, 1.25))
        self.btn_zoom_out.clicked.connect(lambda: self.view.scale(0.8, 0.8))
        self.btn_fit.clicked.connect(self.view.fit_in_view)
        self.btn_export.clicked.connect(self.export_pdf)
        
        self.toolbar_layout.addWidget(self.info_label)
        self.toolbar_layout.addStretch()
        self.toolbar_layout.addWidget(self.btn_zoom_in)
        self.toolbar_layout.addWidget(self.btn_zoom_out)
        self.toolbar_layout.addWidget(self.btn_fit)
        self.toolbar_layout.addWidget(self.btn_export)
        
        # Overlay wrapper
        self.toolbar_widget = QWidget()
        self.toolbar_widget.setLayout(self.toolbar_layout)
        self.toolbar_widget.setStyleSheet("background-color: #181825;")
        self.main_layout.addWidget(self.toolbar_widget)
        
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
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
            qpixmap = QPixmap.fromImage(img)
            
            self.pixmap_item.setPixmap(qpixmap)
            self.scene.setSceneRect(self.pixmap_item.boundingRect())
            self.view.fit_in_view()
            
            self.info_label.setText(f"Aperçu - Taux de remplissage : {fill_rate:.1f}%")
            
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
