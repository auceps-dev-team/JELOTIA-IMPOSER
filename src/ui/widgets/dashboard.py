import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from src.ui.theme import ThemeManager
from src.ui.widgets.common import LedDot, StatCard, StripedBar

_T = ThemeManager
_MAX_LOG_ENTRIES = 8


class DashboardWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._log_entries: list[str] = []
        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(18, 18, 18, 18)
        self.main_layout.setSpacing(14)

        self.main_layout.addLayout(self._build_header())

        self.cards_layout = QHBoxLayout()
        self.cards_layout.setSpacing(14)

        # Placeholder values, same as before the redesign — wiring these to
        # real job/sheet counts from the DB is a separate feature, not part
        # of this visual pass.
        self.card_active_jobs = StatCard("JOBS.ACTIFS", "000", led_color=_T.STATE_OK)
        self.card_errors = StatCard("ERR.PREFLIGHT", "000", led_color=_T.STATE_OK)
        self.card_sheets = StatCard("PLANCHES.GEN", "000", led_color=_T.ACCENT)
        self.card_fill_rate = StatCard(
            "TAUX.REMPLISSAGE", "0.0%", led_color=_T.ACCENT, highlight=True
        )
        self.card_fill_rate.add_progress_bar(0)

        for card in (self.card_active_jobs, self.card_errors, self.card_sheets, self.card_fill_rate):
            self.cards_layout.addWidget(card)
        self.main_layout.addLayout(self.cards_layout)

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self._build_chart_panel(), 1)
        body.addWidget(self._build_journal_panel())
        self.main_layout.addLayout(body, 1)

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.addStretch()
        header.addWidget(QLabel("HOT.FOLDER"))
        self._hf_led = LedDot(_T.STATE_ERR, size=8)
        header.addWidget(self._hf_led)
        self.btn_hotfolder = QPushButton("[ DÉMARRER ]")
        self.btn_hotfolder.setCheckable(True)
        self.btn_hotfolder.toggled.connect(self.toggle_hotfolder)
        header.addWidget(self.btn_hotfolder)
        return header

    def _panel(self) -> QFrame:
        panel = QFrame()
        panel.setStyleSheet(
            f"QFrame {{ background-color:{_T.BG_PANEL}; border:1px solid {_T.BORDER}; }}"
        )
        return panel

    def _build_chart_panel(self) -> QFrame:
        panel = self._panel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 16, 20, 16)

        title = QLabel("┌ PRODUCTION.7J — PLANCHES/JOUR")
        title.setStyleSheet(
            f"color:{_T.TEXT_2}; font-weight:600; font-size:12px; letter-spacing:1.5px; border:none;"
        )
        layout.addWidget(title)

        # Mock data — same placeholder values as the previous pyqtgraph-based
        # chart; pyqtgraph's axis/grid chrome doesn't match the design
        # system's bare-bars look, so this is a plain hand-built bar row.
        days = ["03/07", "04/07", "05/07", "06/07", "07/07", "08/07", "09/07"]
        values = [12, 18, 14, 25, 22, 30, 42]
        max_val = max(values)

        bars_row = QHBoxLayout()
        bars_row.setSpacing(16)
        bars_row.setContentsMargins(6, 20, 6, 0)
        for day, value in zip(days, values):
            col = QVBoxLayout()
            col.setSpacing(6)

            value_label = QLabel(str(value))
            value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value_label.setStyleSheet(
                f"color:{_T.ACCENT_TEXT}; font-weight:600; font-size:12px; border:none;"
            )
            col.addWidget(value_label)

            bar = StripedBar()
            bar.setMinimumHeight(120)
            bar.set_fill_ratio(value / max_val if max_val else 0)
            col.addWidget(bar, 1)

            day_label = QLabel(day)
            day_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            day_label.setStyleSheet(f"color:{_T.TEXT_MUTE}; font-size:10px; border:none;")
            col.addWidget(day_label)

            bars_row.addLayout(col)

        layout.addLayout(bars_row, 1)
        return panel

    def _build_journal_panel(self) -> QFrame:
        panel = self._panel()
        panel.setFixedWidth(380)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(9)

        title = QLabel("┌ JOURNAL.SYSTEME")
        title.setStyleSheet(
            f"color:{_T.TEXT_2}; font-weight:600; font-size:12px; letter-spacing:1.5px; border:none;"
        )
        layout.addWidget(title)

        self._journal_layout = QVBoxLayout()
        self._journal_layout.setSpacing(9)
        layout.addLayout(self._journal_layout)
        layout.addStretch()
        return panel

    def push_log(self, text: str) -> None:
        """Appends a line to the rolling JOURNAL.SYSTEME panel — called from
        MainWindow._log alongside every status bar message, so the journal
        reflects real events instead of being decorative."""
        self._log_entries.insert(0, f"{datetime.datetime.now():%H:%M} {text}")
        del self._log_entries[_MAX_LOG_ENTRIES:]

        while self._journal_layout.count():
            item = self._journal_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for entry in self._log_entries:
            label = QLabel(entry)
            label.setWordWrap(True)
            label.setStyleSheet(f"color:{_T.TEXT_2}; font-size:11px; border:none;")
            self._journal_layout.addWidget(label)

    def toggle_hotfolder(self, checked):
        if checked:
            self.btn_hotfolder.setText("[ ARRÊTER ]")
            self._hf_led.set_color(_T.STATE_OK)
            # Logic to start Hot Folder watchdog will go here
        else:
            self.btn_hotfolder.setText("[ DÉMARRER ]")
            self._hf_led.set_color(_T.STATE_ERR)
            # Logic to stop Hot Folder watchdog will go here
