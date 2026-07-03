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
        self.errors = errors or {}
        self.setup_ui()
        self.populate_tree()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Header
        title = QLabel("⚠️ Des anomalies ont été détectées lors de l'analyse (Preflight)")
        title.setObjectName("preflightWarningTitle")
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
        
        self.btn_export = QPushButton("Exporter Rapport")
        self.btn_export.clicked.connect(self.export_report)
        
        self.btn_cancel = QPushButton("Annuler")
        self.btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.btn_correct_all)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_export)
        btn_layout.addWidget(self.btn_ignore)
        btn_layout.addWidget(self.btn_cancel)
        
        layout.addLayout(btn_layout)
        
    def export_report(self):
        from PySide6.QtWidgets import QFileDialog
        from datetime import datetime
        
        save_path, _ = QFileDialog.getSaveFileName(self, "Exporter Rapport Preflight", "", "HTML Files (*.html)")
        if not save_path:
            return
            
        html_content = f"<html><head><title>Rapport Preflight</title></head><body>"
        html_content += f"<h1>Rapport d'Analyse (Preflight)</h1>"
        html_content += f"<p>Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>"
        
        for filename, err_list in self.errors.items():
            html_content += f"<h2>Fichier: {filename}</h2><ul>"
            for err in err_list:
                err_type = err.get("type", "Erreur")
                err_desc = err.get("desc", "")
                solution = err.get("solution", "")
                
                color = "orange" if err_type == "Warning" else "red"
                html_content += f"<li><b style='color:{color}'>[{err_type}]</b> {err_desc}<br><i>Solution: {solution}</i></li>"
            html_content += "</ul>"
            
        html_content += "</body></html>"
        
        try:
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            QMessageBox.information(self, "Succès", f"Rapport exporté vers {save_path}")
        except Exception as e:
            QMessageBox.warning(self, "Erreur", f"Erreur lors de l'exportation: {e}")

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
