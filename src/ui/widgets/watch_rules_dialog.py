from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from src.core.models.domain import WatchRule
from src.core.watch_rules import ensure_folders, load_rules, save_rules
from src.ui.theme import ThemeManager

_T = ThemeManager
_NO_PRESET = "— réglages globaux —"


class WatchRulesDialog(QDialog):
    """Bind hot folders to product presets: dropping a file into a watched
    folder creates the job with that gamme's whole recipe, no click. This is
    what makes the 24/7 unattended mode real."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dossiers surveillés")
        self.resize(760, 480)
        self.changed = False
        self.rules = load_rules()
        self.current = None

        root = QHBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

        # -- Left: rules ------------------------------------------------- #
        left = QVBoxLayout()
        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self._on_selected)
        left.addWidget(self.list_widget, 1)
        self.btn_new = QPushButton("[+ NOUVELLE RÈGLE]")
        self.btn_new.clicked.connect(self._new_rule)
        left.addWidget(self.btn_new)
        self.btn_delete = QPushButton("SUPPRIMER LA RÈGLE")
        self.btn_delete.clicked.connect(self._delete_rule)
        left.addWidget(self.btn_delete)
        root.addLayout(left, 1)

        # -- Right: rule form -------------------------------------------- #
        right = QVBoxLayout()
        form = QFormLayout()
        form.setSpacing(9)

        self.name_input = QLineEdit()
        form.addRow("Nom :", self.name_input)

        folder_row = QHBoxLayout()
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("Dossier à surveiller")
        btn_browse = QPushButton("Parcourir…")
        btn_browse.clicked.connect(self._pick_folder)
        folder_row.addWidget(self.folder_input, 1)
        folder_row.addWidget(btn_browse)
        form.addRow("Dossier :", folder_row)

        self.preset_combo = QComboBox()
        form.addRow("Gamme produit :", self.preset_combo)

        self.enabled_check = QCheckBox("Règle active")
        self.enabled_check.setChecked(True)
        form.addRow("", self.enabled_check)
        right.addLayout(form)

        hint = QLabel(
            "Chaque dossier surveillé produit ses jobs avec la gamme choisie "
            "(planche, repères, fond perdu, export…). Les fichiers de dossiers "
            "différents ne sont jamais regroupés dans un même job."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{_T.TEXT_MUTE}; font-size:11px; border:none;")
        right.addWidget(hint)
        right.addStretch()

        actions = QHBoxLayout()
        self.btn_save = QPushButton("[ENREGISTRER LA RÈGLE]")
        self.btn_save.setObjectName("primary")
        self.btn_save.clicked.connect(self._save_rule)
        btn_close = QPushButton("Fermer")
        btn_close.clicked.connect(self.accept)
        actions.addStretch()
        actions.addWidget(self.btn_save)
        actions.addWidget(btn_close)
        right.addLayout(actions)
        root.addLayout(right, 2)

        self._load_presets()
        self._reload(select_first=True)

    # ------------------------------------------------------------------ #

    def _load_presets(self):
        from src.core.presets import PresetStore

        self.preset_combo.clear()
        self.preset_combo.addItem(_NO_PRESET, "")
        try:
            self.presets = PresetStore().list()
        except Exception:
            self.presets = []
        for preset in self.presets:
            support = f" · {preset.support}" if preset.support else ""
            self.preset_combo.addItem(f"{preset.name}{support}", str(preset.id))

    def _reload(self, select_id=None, select_first=False):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for rule in self.rules:
            state = "" if rule.enabled else "  (inactive)"
            folder = Path(rule.folder).name if rule.folder else "—"
            self.list_widget.addItem(f"{rule.name}  ·  {folder}{state}")
        self.list_widget.blockSignals(False)

        row = 0 if (select_first and self.rules) else -1
        if select_id is not None:
            for index, rule in enumerate(self.rules):
                if str(rule.id) == str(select_id):
                    row = index
                    break
        self.btn_delete.setEnabled(bool(self.rules))
        if row >= 0:
            self.list_widget.setCurrentRow(row)
            self._on_selected(row)
        elif not self.rules:
            self._new_rule()

    def _on_selected(self, row: int):
        if not (0 <= row < len(self.rules)):
            return
        self.current = self.rules[row]
        self._fill_form(self.current)

    def _fill_form(self, rule: WatchRule):
        self.name_input.setText(rule.name)
        self.name_input.setCursorPosition(0)
        self.folder_input.setText(rule.folder)
        self.folder_input.setCursorPosition(0)
        index = self.preset_combo.findData(rule.preset_id or "")
        self.preset_combo.setCurrentIndex(index if index >= 0 else 0)
        self.enabled_check.setChecked(rule.enabled)

    def _new_rule(self):
        self.current = WatchRule()
        self.list_widget.clearSelection()
        self._fill_form(self.current)

    def _pick_folder(self):
        start = self.folder_input.text() or str(Path.home() / "Jelotia" / "HotFolder")
        path = QFileDialog.getExistingDirectory(self, "Dossier à surveiller", start)
        if path:
            self.folder_input.setText(path)

    def _save_rule(self):
        if self.current is None:
            return
        name = self.name_input.text().strip()
        folder = self.folder_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Nom manquant", "Donnez un nom à la règle.")
            return
        if not folder:
            QMessageBox.warning(self, "Dossier manquant", "Choisissez un dossier à surveiller.")
            return
        # Two rules on the same folder would double-process every drop.
        for rule in self.rules:
            if rule.id != self.current.id and Path(rule.folder or "x") == Path(folder):
                QMessageBox.warning(
                    self, "Dossier déjà surveillé",
                    f"« {rule.name} » surveille déjà ce dossier.",
                )
                return

        self.current.name = name
        self.current.folder = folder
        self.current.preset_id = self.preset_combo.currentData() or ""
        self.current.enabled = self.enabled_check.isChecked()
        if self.current not in self.rules:
            self.rules.append(self.current)

        save_rules(self.rules)
        ensure_folders([self.current])
        self.changed = True
        self._reload(select_id=self.current.id)

    def _delete_rule(self):
        row = self.list_widget.currentRow()
        if not (0 <= row < len(self.rules)):
            return
        rule = self.rules[row]
        reply = QMessageBox.question(
            self, "Supprimer",
            f"Supprimer la règle « {rule.name} » ?\n"
            "Le dossier et son contenu ne sont pas touchés.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.rules.pop(row)
        save_rules(self.rules)
        self.changed = True
        self._reload(select_first=True)
