from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from src.core.models.domain import JobSettings, ProductPreset
from src.core.presets import PresetStore
from src.ui.theme import ThemeManager

_T = ThemeManager
_MARKS = ("none", "graphtec1", "graphtec2")
_MARK_LABELS = ("Aucun", "Graphtec ARMS — type 1", "Graphtec ARMS — type 2")
_FORMATS = ("PDF/X-4", "PDF/X-1a", "PDF", "TIFF", "JPEG")


def _settings_from_config() -> JobSettings:
    """Current global settings as a starting point for a new preset (same
    mapping as MainWindow._build_job_settings, without the UI dependencies)."""
    from src.utils.config_manager import ConfigManager

    config = ConfigManager()
    return JobSettings(
        sheet_width_mm=float(config.get("imposition", "sheet_width") or 900.0),
        sheet_height_mm=float(config.get("imposition", "sheet_height") or 600.0),
        gap_mm=float(config.get("imposition", "spacing") or 3.0),
        margin_mm=float(config.get("imposition", "margin") or 0.0),
        allow_rotation=bool(config.get("imposition", "rotation_allowed")),
        export_format=str(config.get("export", "format") or "PDF/X-4"),
        export_dpi=int(config.get("export", "dpi") or 300),
        plotter_marks=str(config.get("imposition", "plotter_marks") or "none"),
        cut_contour_spot=bool(config.get("export", "cut_contour")),
    )


class PresetManagerDialog(QDialog):
    """Create/edit the manufacturing presets ("gammes"): left, the saved
    presets; right, the full recipe (sheet, spacing, ARMS marks, CutContour,
    export). `changed` tells the caller to refresh its preset combo."""

    def __init__(self, parent=None, store: Optional[PresetStore] = None):
        super().__init__(parent)
        self.setWindowTitle("Gammes produit")
        self.resize(760, 520)
        self.store = store or PresetStore()
        self.changed = False
        self.current: Optional[ProductPreset] = None

        root = QHBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

        # -- Left: preset list ------------------------------------------- #
        left = QVBoxLayout()
        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self._on_selected)
        left.addWidget(self.list_widget, 1)
        self.btn_new = QPushButton("[+ NOUVELLE GAMME]")
        self.btn_new.clicked.connect(self._new_preset)
        left.addWidget(self.btn_new)
        self.btn_delete = QPushButton("SUPPR. LA GAMME")
        self.btn_delete.clicked.connect(self._delete_preset)
        left.addWidget(self.btn_delete)
        root.addLayout(left, 1)

        # -- Right: recipe form ------------------------------------------- #
        right = QVBoxLayout()
        form = QFormLayout()
        form.setSpacing(9)

        self.name_input = QLineEdit()
        form.addRow("Nom :", self.name_input)
        self.support_input = QLineEdit()
        self.support_input.setPlaceholderText("Ex : Vinyle blanc 80µ, Couché 350g…")
        form.addRow("Support :", self.support_input)

        self.sheet_w = QSpinBox()
        self.sheet_w.setRange(10, 5000)
        self.sheet_h = QSpinBox()
        self.sheet_h.setRange(10, 5000)
        dims = QHBoxLayout()
        dims.addWidget(self.sheet_w)
        dims.addWidget(QLabel("×"))
        dims.addWidget(self.sheet_h)
        dims.addWidget(QLabel("mm"))
        dims.addStretch()
        form.addRow("Planche :", dims)

        self.gap = QDoubleSpinBox()
        self.gap.setRange(0.0, 100.0)
        self.gap.setSuffix(" mm")
        form.addRow("Espacement :", self.gap)
        self.margin = QDoubleSpinBox()
        self.margin.setRange(0.0, 500.0)
        self.margin.setSuffix(" mm")
        form.addRow("Marge :", self.margin)
        self.rotation = QCheckBox("Rotation automatique autorisée")
        form.addRow("", self.rotation)

        self.marks = QComboBox()
        self.marks.addItems(_MARK_LABELS)
        form.addRow("Repères plotter :", self.marks)
        self.cut_contour = QCheckBox("Couche CutContour (ton direct)")
        form.addRow("", self.cut_contour)

        self.export_format = QComboBox()
        self.export_format.addItems(_FORMATS)
        form.addRow("Format d'export :", self.export_format)
        self.export_dpi = QSpinBox()
        self.export_dpi.setRange(72, 2400)
        form.addRow("Résolution :", self.export_dpi)

        right.addLayout(form)
        right.addStretch()

        actions = QHBoxLayout()
        self.btn_save = QPushButton("[ENREGISTRER LA GAMME]")
        self.btn_save.setObjectName("primary")
        self.btn_save.clicked.connect(self._save)
        btn_close = QPushButton("Fermer")
        btn_close.clicked.connect(self.accept)
        actions.addStretch()
        actions.addWidget(self.btn_save)
        actions.addWidget(btn_close)
        right.addLayout(actions)
        root.addLayout(right, 2)

        self._reload(select_first=True)

    # ------------------------------------------------------------------ #

    def _reload(self, select_id=None, select_first=False):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        self.presets = self.store.list()
        for preset in self.presets:
            support = f"  ·  {preset.support}" if preset.support else ""
            self.list_widget.addItem(
                f"{preset.name}  ·  {preset.settings.sheet_width_mm:.0f}×"
                f"{preset.settings.sheet_height_mm:.0f}{support}"
            )
        self.list_widget.blockSignals(False)

        row = 0 if (select_first and self.presets) else -1
        if select_id is not None:
            for index, preset in enumerate(self.presets):
                if str(preset.id) == str(select_id):
                    row = index
                    break
        has = bool(self.presets)
        self.btn_delete.setEnabled(has)
        if row >= 0:
            self.list_widget.setCurrentRow(row)
            self._on_selected(row)
        elif not has:
            self._new_preset()

    def _on_selected(self, row: int):
        if not (0 <= row < len(self.presets)):
            return
        self.current = self.presets[row]
        settings = self.current.settings
        self.name_input.setText(self.current.name)
        self.support_input.setText(self.current.support)
        self.sheet_w.setValue(int(settings.sheet_width_mm))
        self.sheet_h.setValue(int(settings.sheet_height_mm))
        self.gap.setValue(settings.gap_mm)
        self.margin.setValue(settings.margin_mm)
        self.rotation.setChecked(settings.allow_rotation)
        self.marks.setCurrentIndex(
            _MARKS.index(settings.plotter_marks) if settings.plotter_marks in _MARKS else 0
        )
        self.cut_contour.setChecked(settings.cut_contour_spot)
        index = self.export_format.findText(settings.export_format)
        self.export_format.setCurrentIndex(index if index >= 0 else 0)
        self.export_dpi.setValue(settings.export_dpi)

    def _new_preset(self):
        self.current = ProductPreset(settings=_settings_from_config())
        self.list_widget.clearSelection()
        self._on_fill_form_from_current()

    def _on_fill_form_from_current(self):
        preset = self.current
        self.name_input.setText(preset.name)
        self.support_input.setText(preset.support)
        settings = preset.settings
        self.sheet_w.setValue(int(settings.sheet_width_mm))
        self.sheet_h.setValue(int(settings.sheet_height_mm))
        self.gap.setValue(settings.gap_mm)
        self.margin.setValue(settings.margin_mm)
        self.rotation.setChecked(settings.allow_rotation)
        self.marks.setCurrentIndex(
            _MARKS.index(settings.plotter_marks) if settings.plotter_marks in _MARKS else 0
        )
        self.cut_contour.setChecked(settings.cut_contour_spot)
        index = self.export_format.findText(settings.export_format)
        self.export_format.setCurrentIndex(index if index >= 0 else 0)
        self.export_dpi.setValue(settings.export_dpi)

    def _save(self):
        if self.current is None:
            return
        if not self.name_input.text().strip():
            QMessageBox.warning(self, "Nom manquant", "Donnez un nom à la gamme.")
            return
        self.current.name = self.name_input.text().strip()
        self.current.support = self.support_input.text().strip()
        settings = self.current.settings
        settings.sheet_width_mm = float(self.sheet_w.value())
        settings.sheet_height_mm = float(self.sheet_h.value())
        settings.gap_mm = self.gap.value()
        settings.margin_mm = self.margin.value()
        settings.allow_rotation = self.rotation.isChecked()
        settings.plotter_marks = _MARKS[self.marks.currentIndex()]
        settings.cut_contour_spot = self.cut_contour.isChecked()
        settings.export_format = self.export_format.currentText()
        settings.export_dpi = self.export_dpi.value()

        self.store.save(self.current)
        self.changed = True
        self._reload(select_id=self.current.id)

    def _delete_preset(self):
        row = self.list_widget.currentRow()
        if not (0 <= row < len(self.presets)):
            return
        preset = self.presets[row]
        reply = QMessageBox.question(
            self, "Supprimer",
            f"Supprimer définitivement la gamme « {preset.name} » ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.store.delete(preset.id)
            self.changed = True
            self._reload(select_first=True)
