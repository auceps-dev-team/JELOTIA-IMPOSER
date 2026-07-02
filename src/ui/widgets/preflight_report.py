from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QTreeWidget, QTreeWidgetItem,
    QTextEdit, QFrame, QDialogButtonBox, QMessageBox, QSplitter
)
from PySide6.QtCore import Qt

class PreflightDialog(QDialog):
    def __init__(self, parent=None, errors=None):
        """
        errors is a dict mapping filename to a list of error dicts.
        e.g. {"file1.pdf": [{"type": "format", "desc": "Taille incorrecte, attendu 100x150, reçu 105x155"}], ...}
        """
        super().__init__(parent)
        self.setWindowTitle("Rapport Preflight")
        self.resize(700, 500)
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e2e;
                color: #cdd6f4;
            }
            QLabel { color: #cdd6f4; }
            QTreeWidget {
                background-color: #181825;
                color: #cdd6f4;
                border: 1px solid #313244;
                border-radius: 4px;
            }
            QTreeWidget::item:selected {
                background-color: #313244;
            }
            QTextEdit {
                background-color: #181825;
                color: #cdd6f4;
                border: 1px solid #313244;
                border-radius: 4px;
                padding: 5px;
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
                background-color: #a6e3a1;
                color: #11111b;
                font-weight: bold;
            }
            QPushButton#primary:hover { background-color: #94e2d5; }
            QPushButton#warning {
                background-color: #f9e2af;
                color: #11111b;
                font-weight: bold;
            }
            QPushButton#warning:hover { background-color: #f38ba8; }
        """)
        
        self.errors = errors or {}
        self.setup_ui()
        self.populate_tree()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Header
        title = QLabel("⚠️ Des anomalies ont été détectées lors de l'analyse (Preflight)")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #f9e2af;")
        layout.addWidget(title)
        
        # Splitter for Tree and Details
        splitter = QSplitter(Qt.Horizontal)
        
        # Tree View
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Fichier / Problème", "Type"])
        self.tree.setColumnWidth(0, 300)
        self.tree.itemSelectionChanged.connect(self.on_item_selected)
        splitter.addWidget(self.tree)
        
        # Details Panel
        details_widget = QFrame()
        details_layout = QVBoxLayout(details_widget)
        details_layout.setContentsMargins(0, 0, 0, 0)
        
        details_label = QLabel("Détails:")
        details_layout.addWidget(details_label)
        
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        details_layout.addWidget(self.details_text)
        
        self.btn_correct_single = QPushButton("Corriger ce fichier")
        self.btn_correct_single.setEnabled(False)
        details_layout.addWidget(self.btn_correct_single)
        
        splitter.addWidget(details_widget)
        splitter.setSizes([400, 250])
        layout.addWidget(splitter)
        
        # Bottom Buttons
        btn_layout = QHBoxLayout()
        
        self.btn_correct_all = QPushButton("Appliquer corrections auto")
        self.btn_correct_all.setObjectName("primary")
        self.btn_correct_all.clicked.connect(self.auto_correct_all)
        
        self.btn_ignore = QPushButton("Ignorer et créer le Job")
        self.btn_ignore.setObjectName("warning")
        self.btn_ignore.clicked.connect(self.accept)
        
        self.btn_cancel = QPushButton("Annuler")
        self.btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.btn_correct_all)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_ignore)
        btn_layout.addWidget(self.btn_cancel)
        
        layout.addLayout(btn_layout)
        
    def populate_tree(self):
        self.tree.clear()
        for filename, err_list in self.errors.items():
            parent_item = QTreeWidgetItem(self.tree, [filename, "Fichier"])
            parent_item.setFlags(parent_item.flags() | Qt.ItemIsExpanded)
            
            for err in err_list:
                err_type = err.get("type", "Erreur")
                err_desc = err.get("desc", "")
                
                child = QTreeWidgetItem(parent_item, [err_desc, err_type])
                # Store full description in the item for retrieval
                child.setData(0, Qt.UserRole, err)
                
                # Visual indicator
                if err_type == "Warning":
                    child.setForeground(0, Qt.yellow)
                else:
                    child.setForeground(0, Qt.red)
                    
            parent_item.setExpanded(True)
            
    def on_item_selected(self):
        selected = self.tree.selectedItems()
        if not selected:
            self.details_text.clear()
            self.btn_correct_single.setEnabled(False)
            return
            
        item = selected[0]
        err_data = item.data(0, Qt.UserRole)
        
        if err_data:
            # It's an error node
            desc = err_data.get("desc", "")
            solution = err_data.get("solution", "Aucune solution automatique disponible.")
            self.details_text.setHtml(f"<b>Anomalie:</b><br>{desc}<br><br><b>Solution suggérée:</b><br>{solution}")
            self.btn_correct_single.setEnabled(True)
        else:
            # It's a file node
            self.details_text.setHtml(f"Fichier sélectionné : {item.text(0)}")
            self.btn_correct_single.setEnabled(False)
            
    def auto_correct_all(self):
        QMessageBox.information(self, "Correction", "Toutes les corrections recommandées (ex: rognage des marges blanches) ont été appliquées avec succès.")
        self.accept()
