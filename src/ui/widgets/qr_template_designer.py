from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.engines.qr_engine import QREngine
from src.core.engines.qr_import import TableImportError, read_table
from src.core.engines.template_composer import (
    STANDARD_FORMATS,
    TemplateComposer,
    TemplateStore,
    substitute_placeholders,
)
from src.core.models.domain import (
    CardTemplate,
    QRCodeSettings,
    TemplateTextZone,
)
from src.ui.theme import ThemeManager

_T = ThemeManager
_MM_PER_PT = 25.4 / 72.0
_CUSTOM_LABEL = "Personnalisé…"
_NEW_LABEL = "— nouveau modèle —"


class _MovableQRItem(QGraphicsRectItem):
    """The QR zone on the work area: draggable, clamped to the page, showing
    a real QR preview so the operator sees actual density at that size."""

    def __init__(self, designer: "TemplateDesignerDialog"):
        zone = designer.template.qr_zone
        super().__init__(0, 0, zone.size_mm, zone.size_mm)
        self._designer = designer
        self.setPos(zone.x_mm, zone.y_mm)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        pen = QPen(QColor(_T.ACCENT))
        pen.setWidthF(0.4)
        pen.setStyle(Qt.PenStyle.DashLine)
        self.setPen(pen)
        self._pixmap_child = QGraphicsPixmapItem(self)
        self.refresh()

    def refresh(self):
        zone = self._designer.template.qr_zone
        self.setRect(0, 0, zone.size_mm, zone.size_mm)
        pixmap = self._designer.qr_preview_pixmap()
        self._pixmap_child.setPixmap(pixmap)
        if pixmap.width() > 0:
            scale = zone.size_mm / pixmap.width()
            self._pixmap_child.setTransform(
                self._pixmap_child.transform().fromScale(scale, scale)
            )
        self._clamp()

    def _clamp(self):
        t = self._designer.template
        zone = t.qr_zone
        x = min(max(0.0, self.pos().x()), max(0.0, t.width_mm - zone.size_mm))
        y = min(max(0.0, self.pos().y()), max(0.0, t.height_mm - zone.size_mm))
        self.setPos(x, y)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            t = self._designer.template
            zone = t.qr_zone
            x = min(max(0.0, value.x()), max(0.0, t.width_mm - zone.size_mm))
            y = min(max(0.0, value.y()), max(0.0, t.height_mm - zone.size_mm))
            return type(value)(x, y)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            zone = self._designer.template.qr_zone
            zone.x_mm, zone.y_mm = self.pos().x(), self.pos().y()
        return super().itemChange(change, value)


class _MovableTextItem(QGraphicsSimpleTextItem):
    """A text zone on the work area, at true physical size (pt → mm)."""

    def __init__(self, zone: TemplateTextZone, designer: "TemplateDesignerDialog"):
        super().__init__()
        self.zone = zone
        self._designer = designer
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setScale(_MM_PER_PT)  # font pixel size in pt -> physical mm
        self.setPos(zone.x_mm, zone.y_mm)
        self.refresh()

    def refresh(self):
        font = QFont("Helvetica")
        font.setPixelSize(max(1, round(self.zone.font_size_pt)))
        font.setBold(self.zone.bold)
        self.setFont(font)
        # The zone keeps the raw template ({Colonne}); the canvas previews it
        # with the sample row's real values when one has been loaded.
        raw = self.zone.text or " "
        sample = getattr(self._designer, "sample_row", None)
        self.setText(substitute_placeholders(raw, sample) if sample else raw)
        self.setBrush(QBrush(QColor(self.zone.color)))

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            t = self._designer.template
            x = min(max(0.0, value.x()), max(0.0, t.width_mm - 2.0))
            y = min(max(0.0, value.y()), max(0.0, t.height_mm - 2.0))
            return type(value)(x, y)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.zone.x_mm, self.zone.y_mm = self.pos().x(), self.pos().y()
        return super().itemChange(change, value)


class TemplateDesignerDialog(QDialog):
    """Zone de travail des modèles : page à l'échelle (mm), fond PDF importé,
    QR et textes déplaçables à la souris, propriétés à droite, persistance via
    TemplateStore et export d'un PDF de test."""

    def __init__(
        self,
        settings: QRCodeSettings,
        sample_data: str = "https://jelotia.com/exemple",
        parent=None,
        store: Optional[TemplateStore] = None,
        initial_template_id=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Modèles — zone de travail")
        self.resize(1180, 680)

        self.engine = QREngine()
        self.settings = settings
        self.sample_data = sample_data or "https://jelotia.com/exemple"
        self.store = store or TemplateStore()

        self.template = CardTemplate()
        self.qr_item: Optional[_MovableQRItem] = None
        self.text_items: list[_MovableTextItem] = []
        self._loading = False
        self.columns: list[str] = []
        self.sample_row: dict = {}

        self.setup_ui()
        self._refresh_template_combo(select_id=initial_template_id)
        if initial_template_id is not None:
            self._on_template_selected()
        else:
            self._rebuild_scene()

    # ------------------------------------------------------------------ #
    #  Layout                                                              #
    # ------------------------------------------------------------------ #

    def setup_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Work area
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setBackgroundBrush(QColor(_T.BG_APP))
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self.view, 1)
        self.scene.selectionChanged.connect(self._on_selection_changed)

        # Properties panel — scrollable so its growing content can never be
        # vertically crushed on short/scaled screens.
        from PySide6.QtWidgets import QScrollArea

        container = QFrame()
        container.setFixedWidth(340)
        container.setStyleSheet(
            f"QFrame {{ background-color:{_T.BG_PANEL}; border-left:1px solid {_T.BORDER}; }}"
        )
        wrap = QVBoxLayout(container)
        wrap.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        panel = QWidget()
        panel.setStyleSheet(f"background-color:{_T.BG_PANEL};")
        side = QVBoxLayout(panel)
        side.setContentsMargins(18, 16, 18, 16)
        side.setSpacing(12)

        # -- Template management ---------------------------------------- #
        side.addWidget(self._title("MODÈLE"))
        self.combo_templates = QComboBox()
        self.combo_templates.currentIndexChanged.connect(self._on_template_selected)
        side.addWidget(self.combo_templates)

        form = QFormLayout()
        form.setSpacing(8)
        self.name_input = QLineEdit(self.template.name)
        self.name_input.textChanged.connect(self._on_name_changed)
        form.addRow("Nom :", self.name_input)

        self.combo_format = QComboBox()
        self.combo_format.addItems(list(STANDARD_FORMATS) + [_CUSTOM_LABEL])
        self.combo_format.currentTextChanged.connect(self._on_format_changed)
        form.addRow("Format :", self.combo_format)

        dims = QHBoxLayout()
        self.spin_w = QDoubleSpinBox()
        self.spin_h = QDoubleSpinBox()
        for spin in (self.spin_w, self.spin_h):
            spin.setRange(10.0, 2000.0)
            spin.setSuffix(" mm")
            spin.setFixedWidth(105)
            spin.valueChanged.connect(self._on_dims_changed)
        dims.addWidget(self.spin_w)
        dims.addWidget(QLabel("×"))
        dims.addWidget(self.spin_h)
        dims.addStretch()
        form.addRow("Dimensions :", dims)
        side.addLayout(form)

        fond_row = QHBoxLayout()
        self.btn_fond = QPushButton("Fond PDF…")
        self.btn_fond.clicked.connect(self._pick_base_pdf)
        self.btn_fond_clear = QPushButton("Retirer")
        self.btn_fond_clear.clicked.connect(self._clear_base_pdf)
        fond_row.addWidget(self.btn_fond)
        fond_row.addWidget(self.btn_fond_clear)
        side.addLayout(fond_row)
        self.fond_label = QLabel("Aucun fond")
        self.fond_label.setStyleSheet(f"color:{_T.TEXT_MUTE}; font-size:11px; border:none;")
        side.addWidget(self.fond_label)

        # -- QR zone ------------------------------------------------------ #
        side.addWidget(self._title("CODE QR"))
        qr_form = QFormLayout()
        self.spin_qr = QDoubleSpinBox()
        self.spin_qr.setRange(5.0, 500.0)
        self.spin_qr.setSuffix(" mm")
        self.spin_qr.valueChanged.connect(self._on_qr_size_changed)
        qr_form.addRow("Taille :", self.spin_qr)
        side.addLayout(qr_form)

        # -- Texts --------------------------------------------------------- #
        side.addWidget(self._title("TEXTES"))
        self.btn_add_text = QPushButton("[+ AJOUTER UN TEXTE]")
        self.btn_add_text.clicked.connect(self._add_text)
        side.addWidget(self.btn_add_text)

        self.text_props = QWidget()
        tp = QFormLayout(self.text_props)
        tp.setContentsMargins(0, 4, 0, 0)
        tp.setSpacing(8)
        self.text_input = QLineEdit()
        self.text_input.textChanged.connect(self._on_text_changed)
        tp.addRow("Contenu :", self.text_input)
        self.spin_font = QDoubleSpinBox()
        self.spin_font.setRange(4.0, 96.0)
        self.spin_font.setSuffix(" pt")
        self.spin_font.valueChanged.connect(self._on_font_changed)
        tp.addRow("Taille :", self.spin_font)
        self.chk_bold = QCheckBox("Gras")
        self.chk_bold.toggled.connect(self._on_bold_changed)
        tp.addRow("", self.chk_bold)
        self.btn_text_color = QPushButton("#000000")
        self.btn_text_color.clicked.connect(self._pick_text_color)
        tp.addRow("Couleur :", self.btn_text_color)
        self.btn_del_text = QPushButton("Supprimer ce texte")
        self.btn_del_text.clicked.connect(self._delete_selected_text)
        tp.addRow("", self.btn_del_text)
        side.addWidget(self.text_props)
        self.text_props.setVisible(False)

        # -- Variables (colonnes Excel/CSV) -------------------------------- #
        side.addWidget(self._title("VARIABLES"))
        vars_row = QHBoxLayout()
        self.btn_load_columns = QPushButton("Colonnes Excel/CSV…")
        self.btn_load_columns.clicked.connect(self._load_columns)
        vars_row.addWidget(self.btn_load_columns)
        self.combo_vars = QComboBox()
        self.combo_vars.setEnabled(False)
        vars_row.addWidget(self.combo_vars, 1)
        side.addLayout(vars_row)
        self.btn_insert_var = QPushButton("[+ INSÉRER LA VARIABLE]")
        self.btn_insert_var.setEnabled(False)
        self.btn_insert_var.clicked.connect(self._insert_variable)
        side.addWidget(self.btn_insert_var)
        self.vars_hint = QLabel(
            "Chargez votre fichier : chaque {Colonne} insérée sera remplacée par "
            "la valeur de la ligne (ID, nom, téléphone…) lors de la génération du lot."
        )
        self.vars_hint.setWordWrap(True)
        self.vars_hint.setStyleSheet(f"color:{_T.TEXT_MUTE}; font-size:11px; border:none;")
        side.addWidget(self.vars_hint)

        side.addStretch()

        # -- Actions -------------------------------------------------------- #
        self.btn_delete_template = QPushButton("Supprimer le modèle")
        self.btn_delete_template.clicked.connect(self._delete_template)
        side.addWidget(self.btn_delete_template)
        self.btn_export_test = QPushButton("[EXPORT PDF TEST]")
        self.btn_export_test.clicked.connect(self._export_test)
        side.addWidget(self.btn_export_test)
        self.btn_save = QPushButton("[ENREGISTRER LE MODÈLE]")
        self.btn_save.setObjectName("primary")
        self.btn_save.clicked.connect(self._save_template)
        side.addWidget(self.btn_save)

        scroll.setWidget(panel)
        wrap.addWidget(scroll)
        root.addWidget(container)

    def _title(self, text: str) -> QLabel:
        lbl = QLabel(f"┌─[ {text} ]──")
        lbl.setStyleSheet(
            f"color:{_T.ACCENT_TEXT}; font-weight:600; font-size:12px; "
            f"letter-spacing:1.5px; border:none;"
        )
        return lbl

    # ------------------------------------------------------------------ #
    #  Scene                                                               #
    # ------------------------------------------------------------------ #

    def qr_preview_pixmap(self) -> QPixmap:
        """A real QR raster (sample data, current style) for the work area."""
        try:
            img = self.engine.generate_image(self.sample_data, self.settings).convert("RGB")
        except Exception:
            return QPixmap()
        qimg = QImage(
            img.tobytes("raw", "RGB"), img.width, img.height,
            img.width * 3, QImage.Format.Format_RGB888,
        ).copy()
        return QPixmap.fromImage(qimg)

    def _rebuild_scene(self):
        self._loading = True
        t = self.template
        self.scene.clear()
        self.qr_item = None
        self.text_items = []
        self.scene.setSceneRect(-10, -10, t.width_mm + 20, t.height_mm + 20)

        page = self.scene.addRect(
            0, 0, t.width_mm, t.height_mm,
            QPen(QColor(_T.ACCENT)), QBrush(QColor("#FFFFFF")),
        )
        page.setZValue(-10)

        if t.base_pdf and Path(t.base_pdf).exists():
            bg = self._render_base_pixmap(Path(t.base_pdf))
            if bg is not None and bg.width() > 0:
                item = QGraphicsPixmapItem(bg)
                item.setScale(t.width_mm / bg.width())
                item.setZValue(-5)
                self.scene.addItem(item)

        self.qr_item = _MovableQRItem(self)
        self.scene.addItem(self.qr_item)

        for zone in t.texts:
            text_item = _MovableTextItem(zone, self)
            self.scene.addItem(text_item)
            self.text_items.append(text_item)

        # Sync the panel controls with the template.
        self.name_input.setText(t.name)
        self.spin_w.setValue(t.width_mm)
        self.spin_h.setValue(t.height_mm)
        self.spin_qr.setValue(t.qr_zone.size_mm)
        self.fond_label.setText(Path(t.base_pdf).name if t.base_pdf else "Aucun fond")
        self._select_format_label(t.width_mm, t.height_mm)
        self.text_props.setVisible(False)

        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._loading = False

    def _render_base_pixmap(self, base: Path) -> Optional[QPixmap]:
        try:
            doc = fitz.open(str(base))
            pix = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            qimg = QImage(
                pix.samples, pix.width, pix.height, pix.stride,
                QImage.Format.Format_RGB888,
            ).copy()
            doc.close()
            return QPixmap.fromImage(qimg)
        except Exception:
            return None

    def _select_format_label(self, w: float, h: float):
        for label, (fw, fh) in STANDARD_FORMATS.items():
            if abs(fw - w) < 0.01 and abs(fh - h) < 0.01:
                self.combo_format.blockSignals(True)
                self.combo_format.setCurrentText(label)
                self.combo_format.blockSignals(False)
                return
        self.combo_format.blockSignals(True)
        self.combo_format.setCurrentText(_CUSTOM_LABEL)
        self.combo_format.blockSignals(False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def showEvent(self, event):
        super().showEvent(event)
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    # ------------------------------------------------------------------ #
    #  Template management                                                 #
    # ------------------------------------------------------------------ #

    def _refresh_template_combo(self, select_id=None):
        self.combo_templates.blockSignals(True)
        self.combo_templates.clear()
        self.combo_templates.addItem(_NEW_LABEL, None)
        for tpl in self.store.list():
            self.combo_templates.addItem(tpl.name, str(tpl.id))
        if select_id is not None:
            index = self.combo_templates.findData(str(select_id))
            if index >= 0:
                self.combo_templates.setCurrentIndex(index)
        self.combo_templates.blockSignals(False)
        self.btn_delete_template.setEnabled(self.combo_templates.currentData() is not None)

    def _on_template_selected(self):
        template_id = self.combo_templates.currentData()
        if template_id is None:
            self.template = CardTemplate()
        else:
            try:
                self.template = self.store.load(template_id)
            except Exception as e:
                QMessageBox.warning(self, "Erreur", f"Modèle illisible : {e}")
                return
        self.btn_delete_template.setEnabled(template_id is not None)
        self._rebuild_scene()

    def _save_template(self):
        if not self.template.name.strip():
            QMessageBox.warning(self, "Nom manquant", "Donnez un nom au modèle.")
            return
        try:
            self.store.save(self.template)
        except Exception as e:
            QMessageBox.warning(self, "Erreur", f"Enregistrement impossible : {e}")
            return
        self._refresh_template_combo(select_id=self.template.id)
        self.fond_label.setText(
            Path(self.template.base_pdf).name if self.template.base_pdf else "Aucun fond"
        )
        QMessageBox.information(self, "Succès", f"Modèle « {self.template.name} » enregistré.")

    def _delete_template(self):
        template_id = self.combo_templates.currentData()
        if template_id is None:
            return
        reply = QMessageBox.question(
            self, "Supprimer",
            f"Supprimer le modèle « {self.template.name} » ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.store.delete(template_id)
        self.template = CardTemplate()
        self._refresh_template_combo()
        self._rebuild_scene()

    # ------------------------------------------------------------------ #
    #  Property handlers                                                   #
    # ------------------------------------------------------------------ #

    def _on_name_changed(self, text: str):
        if not self._loading:
            self.template.name = text

    def _on_format_changed(self, label: str):
        if self._loading or label == _CUSTOM_LABEL:
            return
        w, h = STANDARD_FORMATS[label]
        self.template.width_mm, self.template.height_mm = w, h
        self._rebuild_scene()

    def _on_dims_changed(self):
        if self._loading:
            return
        self.template.width_mm = self.spin_w.value()
        self.template.height_mm = self.spin_h.value()
        self._select_format_label(self.template.width_mm, self.template.height_mm)
        self._rebuild_scene()

    def _on_qr_size_changed(self, value: float):
        if self._loading:
            return
        self.template.qr_zone.size_mm = value
        if self.qr_item is not None:
            self.qr_item.refresh()

    def _pick_base_pdf(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choisir le PDF de fond", "", "PDF (*.pdf)"
        )
        if not path:
            return
        self.template.base_pdf = Path(path)
        self._rebuild_scene()

    def _clear_base_pdf(self):
        self.template.base_pdf = None
        self._rebuild_scene()

    # ------------------------------------------------------------------ #
    #  Texts                                                               #
    # ------------------------------------------------------------------ #

    def _add_text(self):
        zone = TemplateTextZone(text="Nouveau texte", x_mm=5.0, y_mm=5.0)
        self.template.texts.append(zone)
        item = _MovableTextItem(zone, self)
        self.scene.addItem(item)
        self.text_items.append(item)
        self.scene.clearSelection()
        item.setSelected(True)

    def _selected_text_item(self) -> Optional[_MovableTextItem]:
        for item in self.text_items:
            if item.isSelected():
                return item
        return None

    def _on_selection_changed(self):
        item = self._selected_text_item()
        if item is None:
            self.text_props.setVisible(False)
            return
        self._loading = True
        self.text_input.setText(item.zone.text)
        self.spin_font.setValue(item.zone.font_size_pt)
        self.chk_bold.setChecked(item.zone.bold)
        self.btn_text_color.setText(item.zone.color.upper())
        self._loading = False
        self.text_props.setVisible(True)

    def _on_text_changed(self, text: str):
        item = self._selected_text_item()
        if item is not None and not self._loading:
            item.zone.text = text
            item.refresh()

    def _on_font_changed(self, value: float):
        item = self._selected_text_item()
        if item is not None and not self._loading:
            item.zone.font_size_pt = value
            item.refresh()

    def _on_bold_changed(self, checked: bool):
        item = self._selected_text_item()
        if item is not None and not self._loading:
            item.zone.bold = checked
            item.refresh()

    def _pick_text_color(self):
        item = self._selected_text_item()
        if item is None:
            return
        color = QColorDialog.getColor(QColor(item.zone.color), self, "Couleur du texte")
        if color.isValid():
            item.zone.color = color.name()
            self.btn_text_color.setText(color.name().upper())
            item.refresh()

    def _load_columns(self):
        """Loads the batch file's headers (and its first row as sample values)
        so text zones can be built from real columns and previewed with real
        data — dynamic IDs, names, phone numbers…"""
        path, _ = QFileDialog.getOpenFileName(
            self, "Colonnes depuis un fichier", "",
            "Tableurs (*.xlsx *.xlsm *.csv *.tsv);;Tous (*.*)",
        )
        if not path:
            return
        try:
            headers, rows = read_table(Path(path))
        except TableImportError as e:
            QMessageBox.warning(self, "Import impossible", str(e))
            return
        if not headers:
            QMessageBox.warning(self, "Fichier vide", "Aucune colonne détectée.")
            return
        self.columns = headers
        self.sample_row = rows[0] if rows else {}
        self.combo_vars.clear()
        self.combo_vars.addItems(headers)
        self.combo_vars.setEnabled(True)
        self.btn_insert_var.setEnabled(True)
        self.vars_hint.setText(
            f"{len(headers)} colonne(s) chargée(s) — l'aperçu montre les valeurs "
            f"de la première ligne ({Path(path).name})."
        )
        for item in self.text_items:
            item.refresh()

    def _insert_variable(self):
        """Appends {Colonne} to the selected text zone, or creates a new text
        zone carrying just the variable when none is selected."""
        column = self.combo_vars.currentText()
        if not column:
            return
        placeholder = "{" + column + "}"
        item = self._selected_text_item()
        if item is None:
            zone = TemplateTextZone(text=placeholder, x_mm=5.0, y_mm=5.0)
            self.template.texts.append(zone)
            new_item = _MovableTextItem(zone, self)
            self.scene.addItem(new_item)
            self.text_items.append(new_item)
            self.scene.clearSelection()
            new_item.setSelected(True)
            return
        item.zone.text = (item.zone.text or "") + placeholder
        self._loading = True
        self.text_input.setText(item.zone.text)
        self._loading = False
        item.refresh()

    def _delete_selected_text(self):
        item = self._selected_text_item()
        if item is None:
            return
        self.template.texts = [z for z in self.template.texts if z.id != item.zone.id]
        self.text_items.remove(item)
        self.scene.removeItem(item)
        self.text_props.setVisible(False)

    # ------------------------------------------------------------------ #
    #  Test export                                                         #
    # ------------------------------------------------------------------ #

    def _export_test(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export PDF de test", f"{self.template.name or 'modele'}_test.pdf",
            "PDF (*.pdf)",
        )
        if not path:
            return
        try:
            TemplateComposer().compose(
                self.template, self.sample_data, self.settings, Path(path)
            )
        except Exception as e:
            QMessageBox.warning(self, "Erreur", f"Export impossible : {e}")
            return
        QMessageBox.information(self, "Succès", f"PDF de test exporté :\n{path}")
