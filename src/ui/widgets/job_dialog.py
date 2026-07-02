from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QListWidget, QFormLayout,
    QComboBox, QSpinBox, QDialogButtonBox, QMessageBox
)
from PySide6.QtCore import Qt
from pathlib import Path
import uuid

class JobDialog(QDialog):
    def __init__(self, parent=None, files=None):
        super().__init__(parent)
        self.setWindowTitle("Création de Nouveau Job")
        self.resize(500, 400)
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e2e;
                color: #cdd6f4;
            }
            QLabel { color: #cdd6f4; }
            QLineEdit, QComboBox, QSpinBox, QListWidget {
                background-color: #181825;
                color: #cdd6f4;
                border: 1px solid #313244;
                padding: 5px;
                border-radius: 4px;
            }
            QPushButton {
                background-color: #313244;
                color: #cdd6f4;
                padding: 8px 15px;
                border-radius: 4px;
                border: none;
            }
            QPushButton:hover { background-color: #45475a; }
            QPushButton#primary {
                background-color: #89b4fa;
                color: #11111b;
                font-weight: bold;
            }
            QPushButton#primary:hover { background-color: #b4befe; }
        """)
        
        self.initial_files = files or []
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
        # In a real scenario, open QFileDialog
        QMessageBox.information(self, "Info", "Sélection de fichiers (Simulation)")
        
    def validate_and_accept(self):
        if not self.name_input.text().strip():
            QMessageBox.warning(self, "Erreur", "Veuillez entrer un nom de job valide.")
            return
        self.accept()
        
    def get_job_data(self):
        return {
            "name": self.name_input.text().strip(),
            "priority": self.priority_combo.currentText(),
            "files": self.initial_files
        }
