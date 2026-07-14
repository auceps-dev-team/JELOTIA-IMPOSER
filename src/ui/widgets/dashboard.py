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

        # Start at zero; refresh_stats() fills these from the DB (called on
        # startup and after every job event by MainWindow).
        self.card_active_jobs = StatCard("JOBS.ACTIFS", "0", led_color=_T.STATE_OK)
        self.card_errors = StatCard("ERR.PREFLIGHT", "0", led_color=_T.STATE_OK)
        self.card_sheets = StatCard("PLANCHES.GEN", "0", led_color=_T.ACCENT)
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
        self.btn_report = QPushButton("[RAPPORT PRODUCTION…]")
        self.btn_report.clicked.connect(self._open_report)
        header.addWidget(self.btn_report)
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

        # Bare hand-built bar row (pyqtgraph's axis/grid chrome doesn't match
        # the design system's look). Populated by refresh_stats() from real
        # per-day sheet counts; starts at zero over the real last-7-days window.
        self._chart_bars_row = QHBoxLayout()
        self._chart_bars_row.setSpacing(16)
        self._chart_bars_row.setContentsMargins(6, 20, 6, 0)
        layout.addLayout(self._chart_bars_row, 1)
        self._rebuild_chart({})
        return panel

    @staticmethod
    def _clear_layout(layout) -> None:
        """Recursively removes and deletes every widget/child-layout under
        `layout` (Qt has no one-shot 'empty this layout' call)."""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Unparent immediately so it stops rendering this frame;
                # deleteLater alone would leave it drawn at its stale geometry
                # until the event loop next runs.
                widget.setParent(None)
                widget.deleteLater()
            else:
                child = item.layout()
                if child is not None:
                    DashboardWidget._clear_layout(child)
                    child.deleteLater()

    def _rebuild_chart(self, sheets_by_date: dict) -> None:
        """Redraws the 7-day production bars from a {ISO-date: sheet_count} map.
        Uses UTC dates to match how job created_at is stored (utcnow)."""
        self._clear_layout(self._chart_bars_row)

        today = datetime.datetime.now(datetime.timezone.utc).date()
        days = [today - datetime.timedelta(days=i) for i in range(6, -1, -1)]
        values = [int(sheets_by_date.get(d.isoformat(), 0)) for d in days]
        max_val = max(values) if values else 0

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

            day_label = QLabel(day.strftime("%d/%m"))
            day_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            day_label.setStyleSheet(f"color:{_T.TEXT_MUTE}; font-size:10px; border:none;")
            col.addWidget(day_label)

            self._chart_bars_row.addLayout(col)

    def refresh_stats(self, stats: dict) -> None:
        """Updates every KPI card and the production chart from a stats dict
        (see DatabaseRepository.get_dashboard_stats). Called on startup and
        after each job event, so the dashboard always reflects DB truth."""
        self.card_active_jobs.set_value(str(stats.get("active_jobs", 0)))

        errors = int(stats.get("preflight_errors", 0))
        self.card_errors.set_value(str(errors))
        if self.card_errors.led is not None:
            self.card_errors.led.set_color(_T.STATE_ERR if errors else _T.STATE_OK)

        self.card_sheets.set_value(str(stats.get("total_sheets", 0)))

        fill = float(stats.get("avg_fill_rate", 0.0))
        self.card_fill_rate.set_value(f"{fill:.1f}%")
        if self.card_fill_rate.progress is not None:
            self.card_fill_rate.progress.setValue(round(max(0.0, min(100.0, fill))))

        self._rebuild_chart(stats.get("sheets_by_date", {}))

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

    def _open_report(self):
        from src.database.repository import DatabaseRepository
        from src.ui.widgets.production_report import ProductionReportDialog

        ProductionReportDialog(DatabaseRepository(), self).exec()

    def toggle_hotfolder(self, checked):
        if checked:
            self.btn_hotfolder.setText("[ ARRÊTER ]")
            self._hf_led.set_color(_T.STATE_OK)
            # Logic to start Hot Folder watchdog will go here
        else:
            self.btn_hotfolder.setText("[ DÉMARRER ]")
            self._hf_led.set_color(_T.STATE_ERR)
            # Logic to stop Hot Folder watchdog will go here
