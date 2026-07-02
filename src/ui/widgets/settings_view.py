from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QTabWidget, QFormLayout, QLineEdit,
    QSpinBox, QComboBox, QCheckBox, QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt
from src.utils.config_manager import ConfigManager
import shutil

class SettingsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = ConfigManager()
        self.setup_ui()
        self.load_settings()
        
    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(15)
        
        # Title
        title = QLabel("Paramètres de l'Application")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #cdd6f4;")
        self.main_layout.addWidget(title)
        
        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #313244;
                background-color: #181825;
                border-radius: 4px;
            }
            QTabBar::tab {
                background-color: #1e1e2e;
                color: #a6adc8;
                padding: 8px 15px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                border: 1px solid #313244;
                border-bottom: none;
            }
            QTabBar::tab:selected {
                background-color: #181825;
                color: #cdd6f4;
                font-weight: bold;
            }
        """)
        
        self.setup_tab_paths()
        self.setup_tab_imposition()
        self.setup_tab_preflight()
        self.setup_tab_export()
        self.setup_tab_users()
        self.setup_tab_automation()
        self.setup_tab_performance()
        
        self.main_layout.addWidget(self.tabs)
        
        # Bottom Actions
        self.setup_bottom_actions()
        
    def _create_form_tab(self, name):
        tab = QWidget()
        layout = QFormLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.tabs.addTab(tab, name)
        return tab, layout
        
    def _style_input(self, widget):
        widget.setStyleSheet("""
            background-color: #11111b;
            color: #cdd6f4;
            border: 1px solid #313244;
            padding: 5px;
            border-radius: 4px;
        """)
        return widget
        
    def setup_tab_paths(self):
        tab, layout = self._create_form_tab("Chemins")
        
        self.input_path = self._style_input(QLineEdit())
        self.output_path = self._style_input(QLineEdit())
        self.archive_path = self._style_input(QLineEdit())
        self.logs_path = self._style_input(QLineEdit())
        
        layout.addRow("Dossier Input (Hot Folder):", self.input_path)
        layout.addRow("Dossier Output:", self.output_path)
        layout.addRow("Dossier Archives:", self.archive_path)
        layout.addRow("Dossier Logs:", self.logs_path)
        
    def setup_tab_imposition(self):
        tab, layout = self._create_form_tab("Imposition")
        
        self.sheet_width = self._style_input(QSpinBox())
        self.sheet_width.setMaximum(2000)
        self.sheet_height = self._style_input(QSpinBox())
        self.sheet_height.setMaximum(2000)
        
        self.spacing = self._style_input(QSpinBox())
        self.rotation_allowed = QCheckBox("Autoriser la rotation automatique")
        
        layout.addRow("Largeur Planche (mm):", self.sheet_width)
        layout.addRow("Hauteur Planche (mm):", self.sheet_height)
        layout.addRow("Espacement entre poses (mm):", self.spacing)
        layout.addRow("", self.rotation_allowed)
        
    def setup_tab_preflight(self):
        tab, layout = self._create_form_tab("Preflight")
        
        self.min_dpi = self._style_input(QSpinBox())
        self.min_dpi.setMaximum(1200)
        
        self.allowed_formats = self._style_input(QLineEdit())
        
        layout.addRow("Résolution minimale (DPI):", self.min_dpi)
        layout.addRow("Formats autorisés (séparés par virgule):", self.allowed_formats)
        
    def setup_tab_export(self):
        tab, layout = self._create_form_tab("Exportation")
        
        self.export_format = self._style_input(QComboBox())
        self.export_format.addItems(["PDF/X-4", "PDF (Standard)", "TIFF", "JDF"])
        
        self.export_dpi = self._style_input(QSpinBox())
        self.export_dpi.setRange(72, 2400)
        self.export_dpi.setValue(300)
        
        self.archive_days = self._style_input(QSpinBox())
        self.archive_days.setRange(1, 365)
        
        self.enable_notifications = QCheckBox("Activer les notifications système (Windows)")
        
        self.icc_profile = self._style_input(QLineEdit())
        
        layout.addRow("Format de sortie:", self.export_format)
        layout.addRow("Résolution (DPI):", self.export_dpi)
        layout.addRow("Archiver pendant (jours):", self.archive_days)
        layout.addRow("", self.enable_notifications)
        layout.addRow("Profil ICC:", self.icc_profile)
        
    def setup_tab_users(self):
        tab, layout = self._create_form_tab("Utilisateurs")
        
        self.user_role = self._style_input(QComboBox())
        self.user_role.addItems(["Opérateur", "Admin", "Superviseur"])
        
        layout.addRow("Rôle actif:", self.user_role)
        
    def setup_tab_automation(self):
        tab, layout = self._create_form_tab("Automatisation")
        
        self.group_delay = self._style_input(QSpinBox())
        self.group_delay.setMaximum(1440)
        
        self.max_files = self._style_input(QSpinBox())
        self.max_files.setMaximum(1000)
        
        self.enable_scheduling = QCheckBox("Activer le déclenchement planifié")
        self.scheduled_time = self._style_input(QLineEdit())
        self.scheduled_time.setPlaceholderText("ex: 20:00")
        
        layout.addRow("Délai de regroupement (min):", self.group_delay)
        layout.addRow("Limite de fichiers par Job:", self.max_files)
        layout.addRow("", self.enable_scheduling)
        layout.addRow("Heure de déclenchement:", self.scheduled_time)

    def setup_tab_performance(self):
        tab, layout = self._create_form_tab("Performance")
        
        self.workers = self._style_input(QSpinBox())
        self.workers.setMinimum(1)
        self.workers.setMaximum(64)
        
        self.memory_limit = self._style_input(QSpinBox())
        self.memory_limit.setMaximum(64000)
        
        layout.addRow("Nombre de Workers (threads):", self.workers)
        layout.addRow("Limite mémoire (Mo):", self.memory_limit)
        
    def setup_bottom_actions(self):
        layout = QHBoxLayout()
        
        self.btn_import = QPushButton("Importer config")
        self.btn_export = QPushButton("Exporter config")
        self.btn_save = QPushButton("Sauvegarder")
        self.btn_save.setObjectName("primary")
        
        for btn in [self.btn_import, self.btn_export, self.btn_save]:
            btn.setStyleSheet("""
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
            """)
            
        self.btn_import.clicked.connect(self.import_config)
        self.btn_export.clicked.connect(self.export_config)
        self.btn_save.clicked.connect(self.save_settings)
        
        layout.addWidget(self.btn_import)
        layout.addWidget(self.btn_export)
        layout.addStretch()
        layout.addWidget(self.btn_save)
        
        self.main_layout.addLayout(layout)
        
    def load_settings(self):
        # Paths
        self.input_path.setText(self.config.get("paths", "input"))
        self.output_path.setText(self.config.get("paths", "output"))
        self.archive_path.setText(self.config.get("paths", "archive"))
        self.logs_path.setText(self.config.get("paths", "logs"))
        
        # Imposition
        self.sheet_width.setValue(self.config.get("imposition", "sheet_width") or 320)
        self.sheet_height.setValue(self.config.get("imposition", "sheet_height") or 450)
        self.spacing.setValue(self.config.get("imposition", "spacing") or 5)
        self.rotation_allowed.setChecked(self.config.get("imposition", "rotation_allowed") or False)
        
        # Preflight
        self.min_dpi.setValue(self.config.get("preflight", "min_dpi") or 300)
        self.allowed_formats.setText(self.config.get("preflight", "allowed_formats") or "")
        
        # Export
        fmt = self.config.get("export", "format")
        if fmt:
            idx = self.export_format.findText(fmt)
            if idx >= 0: self.export_format.setCurrentIndex(idx)
        self.export_dpi.setValue(self.config.get("export", "dpi") or 300)
        
        # Output & Archive
        self.archive_days.setValue(self.config.get("output", "archive_days") or 15)
        self.enable_notifications.setChecked(self.config.get("output", "enable_notifications") or False)
        self.icc_profile.setText(self.config.get("export", "icc_profile") or "")
        
        # Users
        role = self.config.get("users", "role")
        if role:
            idx = self.user_role.findText(role)
            if idx >= 0: self.user_role.setCurrentIndex(idx)
            
        # Automation
        self.group_delay.setValue(self.config.get("automation", "group_delay_minutes") or 5)
        self.max_files.setValue(self.config.get("automation", "max_files_per_job") or 50)
        self.enable_scheduling.setChecked(self.config.get("automation", "enable_scheduling") or False)
        self.scheduled_time.setText(self.config.get("automation", "scheduled_time") or "")

        # Performance
        self.workers.setValue(self.config.get("performance", "workers") or 4)
        self.memory_limit.setValue(self.config.get("performance", "memory_limit_mb") or 4096)
        
    def save_settings(self):
        # Paths
        self.config.set("paths", "input", self.input_path.text())
        self.config.set("paths", "output", self.output_path.text())
        self.config.set("paths", "archive", self.archive_path.text())
        self.config.set("paths", "logs", self.logs_path.text())
        
        # Imposition
        self.config.set("imposition", "sheet_width", self.sheet_width.value())
        self.config.set("imposition", "sheet_height", self.sheet_height.value())
        self.config.set("imposition", "spacing", self.spacing.value())
        self.config.set("imposition", "rotation_allowed", self.rotation_allowed.isChecked())
        
        # Preflight
        self.config.set("preflight", "min_dpi", self.min_dpi.value())
        self.config.set("preflight", "allowed_formats", self.allowed_formats.text())
        
        # Export
        self.config.set("export", "format", self.export_format.currentText())
        self.config.set("export", "dpi", self.export_dpi.value())
        
        # Output & Archive
        self.config.set("output", "archive_days", self.archive_days.value())
        self.config.set("output", "enable_notifications", self.enable_notifications.isChecked())
        self.config.set("export", "icc_profile", self.icc_profile.text())
        
        # Users
        self.config.set("users", "role", self.user_role.currentText())
        
        # Automation
        self.config.set("automation", "group_delay_minutes", self.group_delay.value())
        self.config.set("automation", "max_files_per_job", self.max_files.value())
        self.config.set("automation", "enable_scheduling", self.enable_scheduling.isChecked())
        self.config.set("automation", "scheduled_time", self.scheduled_time.text())

        # Performance
        self.config.set("performance", "workers", self.workers.value())
        self.config.set("performance", "memory_limit_mb", self.memory_limit.value())
        
        self.config.save()
        QMessageBox.information(self, "Succès", "Configuration sauvegardée.")

    def import_config(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Importer Configuration", "", "JSON Files (*.json)")
        if file_path:
            self.config.load(file_path)
            self.load_settings()
            self.config.save() # save to default
            QMessageBox.information(self, "Succès", "Configuration importée.")
            
    def export_config(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Exporter Configuration", "config.json", "JSON Files (*.json)")
        if file_path:
            self.config.save(file_path)
            QMessageBox.information(self, "Succès", "Configuration exportée.")
