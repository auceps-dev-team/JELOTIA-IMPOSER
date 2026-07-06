import uuid
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
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


class JobDialog(QDialog):
    def __init__(self, parent=None, files=None):
        super().__init__(parent)
        self.setWindowTitle("Création de Nouveau Job")
        self.resize(500, 420)
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

        form_layout.addRow("Nom du Job:", self.name_input)
        form_layout.addRow("Priorité:", self.priority_combo)
        form_layout.addRow("Quantité par défaut:", self.quantity_spin)
        layout.addLayout(form_layout)

        files_label = QLabel("Fichiers importés:")
        layout.addWidget(files_label)

        self.files_list = QListWidget()
        for f in self.initial_files:
            self.files_list.addItem(Path(f).name)
        layout.addWidget(self.files_list)

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
                self.files_list.addItem(Path(fp).name)

    def remove_selected(self):
        for item in self.files_list.selectedItems():
            row = self.files_list.row(item)
            self.files_list.takeItem(row)
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
        return {
            "name": self.name_input.text().strip(),
            "priority": self.priority_combo.currentText(),
            "quantity": self.quantity_spin.value(),
            "files": list(self.initial_files),
        }
