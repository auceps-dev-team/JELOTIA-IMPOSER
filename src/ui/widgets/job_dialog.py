from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QListWidget, QFormLayout,
    QComboBox, QSpinBox, QDialogButtonBox, QMessageBox, QFileDialog
)
from PySide6.QtCore import Qt
from pathlib import Path
import uuid

class JobDialog(QDialog):
    def __init__(self, parent=None, files=None):
        super().__init__(parent)
        self.setWindowTitle("Création de Nouveau Job")
        self.resize(500, 400)
        self.initial_files = list(files or [])
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Form Layout for Job Info
        form_layout = QFormLayout()
        
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Ex: Commande #12345")
        # Generate default name
        short_id = str(uuid.uuid4())[:8]
        self.name_input.setText(f"JOB-{short_id.upper()}")
        
        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["Normale", "Haute", "Urgente"])
        
        form_layout.addRow("Nom du Job:", self.name_input)
        form_layout.addRow("Priorité:", self.priority_combo)
        
        layout.addLayout(form_layout)
        
        # Files List
        files_label = QLabel("Fichiers importés:")
        layout.addWidget(files_label)
        
        self.files_list = QListWidget()
        for f in self.initial_files:
            self.files_list.addItem(Path(f).name)
        layout.addWidget(self.files_list)
        
        # Buttons Box
        btn_layout = QHBoxLayout()
        
        self.btn_add_files = QPushButton("+ Ajouter Fichiers")
        self.btn_add_files.clicked.connect(self.add_files)
        
        self.btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_box.button(QDialogButtonBox.Ok).setObjectName("primary")
        self.btn_box.button(QDialogButtonBox.Ok).setText("Créer Job")
        self.btn_box.accepted.connect(self.validate_and_accept)
        self.btn_box.rejected.connect(self.reject)
        
        btn_layout.addWidget(self.btn_add_files)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_box)
        
        layout.addLayout(btn_layout)
        
    def add_files(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Sélectionner des fichiers",
            "",
            "Fichiers supportés (*.pdf *.tiff *.tif *.png *.jpg *.jpeg);;PDF (*.pdf);;Images (*.tiff *.tif *.png *.jpg *.jpeg);;Tous (*.*)"
        )
        if file_paths:
            for fp in file_paths:
                if fp not in self.initial_files:
                    self.initial_files.append(fp)
                    self.files_list.addItem(Path(fp).name)
        
    def validate_and_accept(self):
        if not self.name_input.text().strip():
            QMessageBox.warning(self, "Erreur", "Veuillez entrer un nom de job valide.")
            return
            
        if not self.initial_files:
            # Let it pass if empty, just for testing, or we can warn
            pass
            
        # Simulate Preflight check
        # Let's say if a file has "error" in its name or we just mock some errors
        has_warnings = len(self.initial_files) > 0  # for demo: always show warning if there are files
        
        if has_warnings:
            mock_errors = {}
            for f in self.initial_files:
                fname = Path(f).name
                mock_errors[fname] = [
                    {
                        "type": "Warning", 
                        "desc": "Marges blanches détectées autour du contenu.",
                        "solution": "Rogner automatiquement les marges selon le contour du contenu visuel."
                    },
                    {
                        "type": "Erreur",
                        "desc": "Résolution détectée : 72 DPI (Minimum: 300 DPI)",
                        "solution": "Avertissement critique : impression potentiellement floue."
                    }
                ]
            
            from src.ui.widgets.preflight_report import PreflightDialog
            dialog = PreflightDialog(self, mock_errors)
            if dialog.exec() == QDialog.Rejected:
                # User cancelled job creation
                return
                
        self.accept()
        
    def get_job_data(self):
        return {
            "name": self.name_input.text().strip(),
            "priority": self.priority_combo.currentText(),
            "files": self.initial_files
        }
