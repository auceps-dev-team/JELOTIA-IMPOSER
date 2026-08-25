from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.ui.theme import ThemeManager
from src.utils.config_manager import ConfigManager

_T = ThemeManager


class SettingsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = ConfigManager()
        self._category_buttons: list[QPushButton] = []
        self.setup_ui()
        self.load_settings()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(15)

        # Title
        title = QLabel("Paramètres de l'Application")
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        self.main_layout.addWidget(title)

        body = QHBoxLayout()
        body.setSpacing(14)

        self.category_sidebar = QFrame()
        self.category_sidebar.setFixedWidth(230)
        self.category_sidebar.setStyleSheet(
            f"QFrame {{ background-color:{_T.BG_PANEL}; border:1px solid {_T.BORDER}; }}"
        )
        self.category_layout = QVBoxLayout(self.category_sidebar)
        self.category_layout.setContentsMargins(0, 14, 0, 14)
        self.category_layout.setSpacing(0)

        self.stack = QStackedWidget()

        body.addWidget(self.category_sidebar)
        body.addWidget(self.stack, 1)

        self.setup_tab_paths()
        self.setup_tab_imposition()
        self.setup_tab_preflight()
        self.setup_tab_export()
        self.setup_tab_users()
        self.setup_tab_automation()
        self.setup_tab_performance()
        self.category_layout.addStretch()

        self.main_layout.addLayout(body, 1)

        # Bottom Actions
        self.setup_bottom_actions()

    def _create_form_tab(self, name):
        """Builds one settings category page: a titled panel containing a
        2-column form, added to self.stack, with a matching entry in the
        left category sidebar."""
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(26, 22, 26, 22)

        title = QLabel(f"┌─[ {name.upper()} ]──")
        title.setStyleSheet(
            f"color:{_T.ACCENT_TEXT}; font-weight:600; font-size:13px; letter-spacing:2px; border:none;"
        )
        outer.addWidget(title)

        form_container = QWidget()
        layout = QFormLayout(form_container)
        layout.setContentsMargins(0, 22, 0, 0)
        layout.setSpacing(15)
        layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        outer.addWidget(form_container)
        outer.addStretch()

        self.stack.addWidget(tab)
        self._add_category_entry(name)
        return tab, layout

    def _add_category_entry(self, name: str) -> None:
        index = self.stack.count() - 1
        btn = QPushButton(name.upper())
        btn.setCheckable(True)
        btn.setFlat(True)
        btn.clicked.connect(lambda: self._select_category(index))
        self.category_layout.addWidget(btn)
        self._category_buttons.append(btn)
        self._style_category_button(btn, active=(index == 0))
        if index == 0:
            btn.setChecked(True)

    def _style_category_button(self, btn: QPushButton, active: bool) -> None:
        if active:
            btn.setStyleSheet(
                f"text-align:left; padding:10px 18px; border:none; "
                f"border-left:2px solid {_T.ACCENT}; background-color:{_T.BG_ACTIVE}; "
                f"color:{_T.ACCENT_TEXT}; letter-spacing:1px;"
            )
        else:
            btn.setStyleSheet(
                f"text-align:left; padding:10px 18px; border:none; "
                f"border-left:2px solid transparent; background-color:transparent; "
                f"color:{_T.TEXT_MUTE}; letter-spacing:1px;"
            )

    def _select_category(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self._category_buttons):
            btn.setChecked(i == index)
            self._style_category_button(btn, active=(i == index))

    def _style_input(self, widget):
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
        self.margin = self._style_input(QSpinBox())
        self.margin.setMaximum(500)
        self.rotation_allowed = QCheckBox("Autoriser la rotation automatique")

        # Graphtec ARMS registration marks: the type must match the plotter's
        # ARMS menu; the nesting automatically reserves the marks' margin.
        self.plotter_marks = self._style_input(QComboBox())
        self.plotter_marks.addItems(
            ["Aucun", "Graphtec ARMS — type 1", "Graphtec ARMS — type 2"]
        )
        self.plotter_mark_length = self._style_input(QSpinBox())
        self.plotter_mark_length.setRange(5, 20)
        self.plotter_mark_length.setValue(15)

        # Bleed: 0 = off. The artwork is extended past the trim line so a
        # drifting blade never exposes white; cutting still targets the
        # finished size.
        self.add_bleed = self._style_input(QDoubleSpinBox())
        self.add_bleed.setRange(0.0, 20.0)
        self.add_bleed.setSingleStep(0.5)
        self.add_bleed.setSuffix(" mm")
        self.add_bleed.setToolTip(
            "0 = désactivé. Les fichiers livrés sans fond perdu sont étendus "
            "automatiquement (bords étirés en vectoriel, miroir pour les images) ; "
            "ceux qui en ont déjà un sont conservés tels quels."
        )

        layout.addRow("Largeur Planche (mm):", self.sheet_width)
        layout.addRow("Hauteur Planche (mm):", self.sheet_height)
        layout.addRow("Espacement entre poses (mm):", self.spacing)
        layout.addRow("Marge autour de la planche (mm):", self.margin)
        layout.addRow("", self.rotation_allowed)
        layout.addRow("Repères plotter:", self.plotter_marks)
        layout.addRow("Longueur des repères (mm):", self.plotter_mark_length)
        layout.addRow("Fond perdu automatique (mm):", self.add_bleed)

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
        self.export_format.addItems(["PDF/X-4", "PDF (Standard)", "TIFF", "JDF", "JPEG"])

        self.export_dpi = self._style_input(QSpinBox())
        self.export_dpi.setRange(72, 2400)
        self.export_dpi.setValue(300)

        # Compatibility settings
        self.tiff_compression = self._style_input(QComboBox())
        self.tiff_compression.addItems(["LZW (Standard)", "Aucune / RAW (Vieux RIPs)"])
        
        self.tiff_photoshop_compat = QCheckBox("Mode compatibilité TIFF Photoshop (Predictor 2, RowsPerStrip 4, sans ICC)")
        
        self.jpeg_color_mode = self._style_input(QComboBox())
        self.jpeg_color_mode.addItems(["CMJN (Standard)", "RVB (Vieux RIPs)"])
        
        self.pdf_rasterize = QCheckBox("Pixelliser les exports PDF (Compatibilité Vieux RIPs - Supprime la découpe)")

        self.archive_days = self._style_input(QSpinBox())
        self.archive_days.setRange(1, 365)

        self.enable_notifications = QCheckBox("Activer les notifications système (Windows)")

        # Real ICC profile (a file), not a free-text label: without one, the
        # CMYK conversion is Pillow's naive formula, which turns black into
        # 300% ink. Discovered profiles are listed; "Parcourir" accepts the
        # shop's own (FOGRA39, printer linearisation…).
        self.icc_profile = self._style_input(QComboBox())
        self.icc_profile.setMinimumWidth(220)
        self.btn_icc_browse = QPushButton("Parcourir…")
        self.btn_icc_browse.clicked.connect(self._browse_icc)
        icc_row = QHBoxLayout()
        icc_row.addWidget(self.icc_profile, 1)
        icc_row.addWidget(self.btn_icc_browse)

        self.cut_contour = QCheckBox(
            "Couche CutContour (ton direct) sur les planches — RIP print & cut"
        )

        layout.addRow("Format de sortie:", self.export_format)
        layout.addRow("Résolution (DPI):", self.export_dpi)
        layout.addRow("Compression TIFF:", self.tiff_compression)
        layout.addRow("", self.tiff_photoshop_compat)
        layout.addRow("Mode Couleur JPEG:", self.jpeg_color_mode)
        layout.addRow("", self.pdf_rasterize)
        layout.addRow("Archiver pendant (jours):", self.archive_days)
        layout.addRow("", self.enable_notifications)
        layout.addRow("Profil ICC (CMJN):", icc_row)
        layout.addRow("", self.cut_contour)

    def setup_tab_users(self):
        # "Rôle actif" retiré : aucun contrôle d'accès n'existe dans le produit,
        # et laisser le champ laissait croire à une gestion des droits. À
        # remettre le jour où les droits sont réellement appliqués.
        tab, layout = self._create_form_tab("Apparence")

        self.ui_theme = self._style_input(QComboBox())
        self.ui_theme.addItems(["dark", "light"])

        layout.addRow("Thème (Nécessite redémarrage):", self.ui_theme)

    def setup_tab_automation(self):
        tab, layout = self._create_form_tab("Automatisation")

        self.group_delay = self._style_input(QSpinBox())
        self.group_delay.setMaximum(1440)

        self.max_files = self._style_input(QSpinBox())
        self.max_files.setMaximum(1000)

        self.enable_scheduling = QCheckBox("Activer le déclenchement planifié")
        self.scheduled_time = self._style_input(QLineEdit())
        self.scheduled_time.setPlaceholderText("ex: 20:00")

        self.btn_watch_rules = QPushButton("[DOSSIERS SURVEILLÉS…]")
        self.btn_watch_rules.setToolTip(
            "Lier un dossier à une gamme produit : déposer un fichier suffit à "
            "créer le job avec la bonne recette (mode 24/7)"
        )
        self.btn_watch_rules.clicked.connect(self._open_watch_rules)

        layout.addRow("Délai de regroupement (min):", self.group_delay)
        layout.addRow("Limite de fichiers par Job:", self.max_files)
        layout.addRow("", self.enable_scheduling)
        layout.addRow("Heure de déclenchement:", self.scheduled_time)
        layout.addRow("Hot folders à règles:", self.btn_watch_rules)

    def _populate_icc_profiles(self, selected: str = "") -> None:
        """Lists the CMYK profiles found on the machine; the stored value is
        the profile's PATH (data), the name is only what the operator reads."""
        from src.core.engines.icc_engine import discover_profiles

        self.icc_profile.blockSignals(True)
        self.icc_profile.clear()
        self.icc_profile.addItem("— aucun (conversion approximative) —", "")
        try:
            for info in discover_profiles(cmyk_only=True):
                self.icc_profile.addItem(f"{info.name}  ({info.path.name})", str(info.path))
        except Exception:
            pass
        if selected:
            index = self.icc_profile.findData(selected)
            if index < 0:  # a profile chosen before but no longer discovered
                self.icc_profile.addItem(Path(selected).name, selected)
                index = self.icc_profile.count() - 1
            self.icc_profile.setCurrentIndex(index)
        self.icc_profile.blockSignals(False)

    def _browse_icc(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Profil ICC CMJN", "", "Profils ICC (*.icc *.icm);;Tous (*.*)"
        )
        if not path:
            return
        from src.core.engines.icc_engine import read_profile

        info = read_profile(Path(path))
        if info is None:
            QMessageBox.warning(
                self, "Profil illisible",
                f"{Path(path).name} n'est pas un profil ICC valide.",
            )
            return
        if not info.is_cmyk:
            reply = QMessageBox.question(
                self, "Profil non CMJN",
                f"« {info.name} » est un profil {info.color_space or 'inconnu'}, "
                "pas CMJN. L'utiliser quand même ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._populate_icc_profiles(selected=path)

    def _open_watch_rules(self):
        """Edited rules take effect immediately — restarting the app to watch a
        new folder would defeat the point of unattended production."""
        from src.ui.widgets.watch_rules_dialog import WatchRulesDialog

        dialog = WatchRulesDialog(self)
        dialog.exec()
        if not dialog.changed:
            return
        window = self.window()
        restart = getattr(window, "restart_hot_folder_monitors", None)
        if callable(restart):
            restart()

    def setup_tab_performance(self):
        tab, layout = self._create_form_tab("Performance")

        self.workers = self._style_input(QSpinBox())
        self.workers.setMinimum(1)
        self.workers.setMaximum(64)

        # "Limite mémoire" retirée : aucune limite n'était appliquée nulle part.
        self.workers.setToolTip(
            "Nombre de processus de traitement en parallèle.\n"
            "Pris en compte au prochain démarrage de l'application."
        )
        layout.addRow("Nombre de Workers (processus):", self.workers)

    def setup_bottom_actions(self):
        layout = QHBoxLayout()

        self.btn_import = QPushButton("IMPORT.CFG")
        self.btn_export = QPushButton("EXPORT.CFG")
        self.btn_save = QPushButton("[SAUVEGARDER]")
        self.btn_save.setObjectName("primary")

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
        self.margin.setValue(self.config.get("imposition", "margin") or 0)
        self.rotation_allowed.setChecked(self.config.get("imposition", "rotation_allowed") or False)
        marks_index = {"none": 0, "graphtec1": 1, "graphtec2": 2}.get(
            self.config.get("imposition", "plotter_marks") or "none", 0
        )
        self.plotter_marks.setCurrentIndex(marks_index)
        self.plotter_mark_length.setValue(
            int(self.config.get("imposition", "plotter_mark_length") or 15)
        )
        self.add_bleed.setValue(float(self.config.get("imposition", "add_bleed") or 0.0))

        # Preflight
        self.min_dpi.setValue(self.config.get("preflight", "min_dpi") or 300)
        self.allowed_formats.setText(self.config.get("preflight", "allowed_formats") or "")

        # Export
        fmt = self.config.get("export", "format")
        if fmt:
            idx = self.export_format.findText(fmt)
            if idx >= 0:
                self.export_format.setCurrentIndex(idx)
        self.export_dpi.setValue(self.config.get("export", "dpi") or 300)
        self.cut_contour.setChecked(self.config.get("export", "cut_contour") or False)
        
        tiff_comp = self.config.get("export", "tiff_compression") or "tiff_lzw"
        self.tiff_compression.setCurrentIndex(0 if tiff_comp == "tiff_lzw" else 1)
        
        self.tiff_photoshop_compat.setChecked(self.config.get("export", "tiff_photoshop_compat") or False)
        
        jpeg_cm = self.config.get("export", "jpeg_color_mode") or "CMYK"
        self.jpeg_color_mode.setCurrentIndex(0 if jpeg_cm == "CMYK" else 1)
        
        self.pdf_rasterize.setChecked(self.config.get("export", "pdf_rasterize") or False)

        # Output & Archive
        self.archive_days.setValue(self.config.get("output", "archive_days") or 15)
        self.enable_notifications.setChecked(self.config.get("output", "enable_notifications") or False)
        # Historically a free-text label ("Coated FOGRA39"); only a real file
        # path can drive a conversion, so a legacy label resolves to "none".
        stored = self.config.get("export", "icc_profile") or ""
        self._populate_icc_profiles(selected=stored if Path(stored).is_file() else "")

        # Apparence
        theme = self.config.get("ui", "theme")
        if theme:
            idx = self.ui_theme.findText(theme)
            if idx >= 0:
                self.ui_theme.setCurrentIndex(idx)

        # Automation
        self.group_delay.setValue(self.config.get("automation", "group_delay_minutes") or 5)
        self.max_files.setValue(self.config.get("automation", "max_files_per_job") or 50)
        self.enable_scheduling.setChecked(self.config.get("automation", "enable_scheduling") or False)
        self.scheduled_time.setText(self.config.get("automation", "scheduled_time") or "")

        # Performance
        self.workers.setValue(self.config.get("performance", "workers") or 4)

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
        self.config.set("imposition", "margin", self.margin.value())
        self.config.set("imposition", "rotation_allowed", self.rotation_allowed.isChecked())
        self.config.set(
            "imposition", "plotter_marks",
            ("none", "graphtec1", "graphtec2")[self.plotter_marks.currentIndex()],
        )
        self.config.set("imposition", "plotter_mark_length", self.plotter_mark_length.value())
        self.config.set("imposition", "add_bleed", self.add_bleed.value())

        # Preflight
        self.config.set("preflight", "min_dpi", self.min_dpi.value())
        self.config.set("preflight", "allowed_formats", self.allowed_formats.text())

        # Export
        self.config.set("export", "format", self.export_format.currentText())
        self.config.set("export", "dpi", self.export_dpi.value())
        self.config.set("export", "cut_contour", self.cut_contour.isChecked())
        
        self.config.set("export", "tiff_compression", "tiff_lzw" if self.tiff_compression.currentIndex() == 0 else "raw")
        self.config.set("export", "tiff_photoshop_compat", self.tiff_photoshop_compat.isChecked())
        self.config.set("export", "jpeg_color_mode", "CMYK" if self.jpeg_color_mode.currentIndex() == 0 else "RGB")
        self.config.set("export", "pdf_rasterize", self.pdf_rasterize.isChecked())

        # Output & Archive
        self.config.set("output", "archive_days", self.archive_days.value())
        self.config.set("output", "enable_notifications", self.enable_notifications.isChecked())
        self.config.set("export", "icc_profile", self.icc_profile.currentData() or "")

        # Users & UI
        self.config.set("ui", "theme", self.ui_theme.currentText())

        # Automation
        self.config.set("automation", "group_delay_minutes", self.group_delay.value())
        self.config.set("automation", "max_files_per_job", self.max_files.value())
        self.config.set("automation", "enable_scheduling", self.enable_scheduling.isChecked())
        self.config.set("automation", "scheduled_time", self.scheduled_time.text())

        # Performance
        self.config.set("performance", "workers", self.workers.value())

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
