import uuid
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

_FILE_COL, _QTY_COL = 0, 1


class JobDialog(QDialog):
    def __init__(self, parent=None, files=None):
        super().__init__(parent)
        self.setWindowTitle("Création de Nouveau Job")
        self.resize(560, 460)
        self.initial_files = list(files or [])
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Ex: Commande #12345")
        self.name_input.setText(f"JOB-{str(uuid.uuid4())[:8].upper()}")

        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["Normale", "Haute", "Urgente"])

        self.quantity_spin = QSpinBox()
        self.quantity_spin.setMinimum(1)
        self.quantity_spin.setMaximum(9999)
        self.quantity_spin.setValue(1)

        # 0 = pas de surcharge, utilise le réglage global (Settings > Imposition).
        self.sheet_width_input = QDoubleSpinBox()
        self.sheet_width_input.setRange(0, 5000)
        self.sheet_width_input.setSpecialValueText("Réglage global")
        self.sheet_width_input.setSuffix(" mm")

        self.sheet_height_input = QDoubleSpinBox()
        self.sheet_height_input.setRange(0, 5000)
        self.sheet_height_input.setSpecialValueText("Réglage global")
        self.sheet_height_input.setSuffix(" mm")

        form_layout.addRow("Nom du Job:", self.name_input)
        form_layout.addRow("Priorité:", self.priority_combo)
        form_layout.addRow("Quantité par défaut:", self.quantity_spin)
        form_layout.addRow("Largeur planche (0 = global):", self.sheet_width_input)
        form_layout.addRow("Hauteur planche (0 = global):", self.sheet_height_input)
        layout.addLayout(form_layout)

        files_label = QLabel("Fichiers importés:")
        layout.addWidget(files_label)

        self.files_table = QTableWidget(0, 2)
        self.files_table.setHorizontalHeaderLabels(["Fichier", "Quantité"])
        header = self.files_table.horizontalHeader()
        header.setSectionResizeMode(_FILE_COL, QHeaderView.ResizeMode.Stretch)
        # ResizeToContents only measures QTableWidgetItems, not the cell's
        # QSpinBox widget — it would size the column to the "Quantité" header
        # text and clip the spinbox into unreadable fragments. Sized explicitly
        # in _add_file_row from the spinbox's own sizeHint instead.
        header.setSectionResizeMode(_QTY_COL, QHeaderView.ResizeMode.Fixed)
        self.files_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.files_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        for f in self.initial_files:
            self._add_file_row(f)
        layout.addWidget(self.files_table)

        btn_layout = QHBoxLayout()
        self.btn_add_files = QPushButton("+ Ajouter Fichiers")
        self.btn_add_files.clicked.connect(self.add_files)

        self.btn_remove = QPushButton("Supprimer")
        self.btn_remove.clicked.connect(self.remove_selected)

        self.btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.btn_box.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        self.btn_box.button(QDialogButtonBox.StandardButton.Ok).setText("Créer Job")
        self.btn_box.accepted.connect(self.validate_and_accept)
        self.btn_box.rejected.connect(self.reject)

        btn_layout.addWidget(self.btn_add_files)
        btn_layout.addWidget(self.btn_remove)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_box)
        layout.addLayout(btn_layout)

    def _add_file_row(self, file_path: str):
        row = self.files_table.rowCount()
        self.files_table.insertRow(row)
        self.files_table.setItem(row, _FILE_COL, QTableWidgetItem(Path(file_path).name))

        qty_spin = QSpinBox()
        qty_spin.setMinimum(1)
        qty_spin.setMaximum(9999)
        qty_spin.setValue(self.quantity_spin.value())
        self.files_table.setCellWidget(row, _QTY_COL, qty_spin)

        # Fixed column / row sized to the spinbox itself (see the Fixed resize
        # mode above), so the value and its up/down arrows are never clipped.
        hint = qty_spin.sizeHint()
        if self.files_table.columnWidth(_QTY_COL) < hint.width() + 12:
            self.files_table.setColumnWidth(_QTY_COL, hint.width() + 12)
        if self.files_table.rowHeight(row) < hint.height() + 8:
            self.files_table.setRowHeight(row, hint.height() + 8)

    def add_files(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Sélectionner des fichiers",
            "",
            "Fichiers supportés (*.pdf *.tiff *.tif *.png *.jpg *.jpeg)"
            ";;PDF (*.pdf)"
            ";;Images (*.tiff *.tif *.png *.jpg *.jpeg)"
            ";;Tous (*.*)"
        )
        for fp in file_paths:
            if fp not in self.initial_files:
                self.initial_files.append(fp)
                self._add_file_row(fp)

    def remove_selected(self):
        rows = sorted({item.row() for item in self.files_table.selectedItems()}, reverse=True)
        for row in rows:
            self.files_table.removeRow(row)
            if row < len(self.initial_files):
                self.initial_files.pop(row)

    def validate_and_accept(self):
        if not self.name_input.text().strip():
            QMessageBox.warning(self, "Erreur", "Veuillez entrer un nom de job valide.")
            return
        if not self.initial_files:
            reply = QMessageBox.question(
                self,
                "Aucun fichier",
                "Aucun fichier sélectionné. Créer quand même le job ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                return
        self.accept()

    def get_job_data(self):
        quantities = {}
        for row, file_path in enumerate(self.initial_files):
            qty_spin = self.files_table.cellWidget(row, _QTY_COL)
            quantities[file_path] = qty_spin.value() if qty_spin else self.quantity_spin.value()

        return {
            "name": self.name_input.text().strip(),
            "priority": self.priority_combo.currentText(),
            "quantity": self.quantity_spin.value(),
            "files": list(self.initial_files),
            "overrides": {
                "sheet_width_mm": self.sheet_width_input.value() or None,
                "sheet_height_mm": self.sheet_height_input.value() or None,
                "quantities": quantities,
            },
        }
