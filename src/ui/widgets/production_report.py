from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.core.reporting import build_production_report, export_production_xlsx
from src.ui.theme import ThemeManager

_T = ThemeManager
_HEADERS = ["Date", "Job", "Statut", "Fich.", "Planches", "Poses",
            "Surface m²", "Rempl. %", "Chute m²"]


class ProductionReportDialog(QDialog):
    """Production over a period: per-job sheets, poses, consumed area and
    waste — the figures a print shop manages by — with an Excel export."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Rapport de production")
        self.resize(920, 560)
        self.db = db
        self.report = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        period = QHBoxLayout()
        period.addWidget(QLabel("Du :"))
        self.date_start = QDateEdit(QDate.currentDate().addDays(-30))
        self.date_start.setCalendarPopup(True)
        period.addWidget(self.date_start)
        period.addWidget(QLabel("au :"))
        self.date_end = QDateEdit(QDate.currentDate())
        self.date_end.setCalendarPopup(True)
        period.addWidget(self.date_end)
        self.btn_refresh = QPushButton("ACTUALISER")
        self.btn_refresh.clicked.connect(self._refresh)
        period.addWidget(self.btn_refresh)
        period.addStretch()
        layout.addLayout(period)

        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        self.totals_label = QLabel("")
        self.totals_label.setStyleSheet(
            f"color:{_T.ACCENT_TEXT}; font-weight:600; border:none; padding:4px 2px;"
        )
        layout.addWidget(self.totals_label)

        actions = QHBoxLayout()
        self.btn_export = QPushButton("[EXPORT EXCEL…]")
        self.btn_export.setObjectName("primary")
        self.btn_export.clicked.connect(self._export)
        btn_close = QPushButton("Fermer")
        btn_close.clicked.connect(self.accept)
        actions.addStretch()
        actions.addWidget(self.btn_export)
        actions.addWidget(btn_close)
        layout.addLayout(actions)

        self._refresh()

    def _period(self) -> tuple:
        start = self.date_start.date().toPython()
        end = self.date_end.date().toPython()
        if start > end:
            start, end = end, start
        return start, end

    def _refresh(self):
        start, end = self._period()
        try:
            jobs = self.db.get_all_jobs(include_archived=True)
        except Exception as e:
            QMessageBox.warning(self, "Erreur", f"Lecture de la base impossible : {e}")
            return
        self.report = build_production_report(jobs, start=start, end=end)

        self.table.setRowCount(0)
        for row_data in self.report.rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                row_data.date.strftime("%d/%m %H:%M") if row_data.date else "—",
                row_data.name, row_data.status, str(row_data.files),
                str(row_data.sheets), str(row_data.poses),
                f"{row_data.area_m2:.2f}", f"{row_data.avg_fill:.1f}",
                f"{row_data.waste_m2:.2f}",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col >= 3:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.table.setItem(row, col, item)

        totals = self.report.totals
        self.totals_label.setText(
            f"TOTAL — {totals['jobs']} job(s) · {totals['sheets']} planche(s) · "
            f"{totals['poses']} pose(s) · {totals['area_m2']:.2f} m² consommés · "
            f"remplissage moyen {totals['avg_fill']:.1f} % · "
            f"chute {totals['waste_m2']:.2f} m²"
        )
        self.btn_export.setEnabled(bool(self.report.rows))

    def _export(self):
        if self.report is None or not self.report.rows:
            return
        start, end = self._period()
        default = f"production_{start:%Y%m%d}_{end:%Y%m%d}.xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter le rapport", default, "Excel (*.xlsx)"
        )
        if not path:
            return
        try:
            export_production_xlsx(self.report, Path(path))
        except OSError as e:
            QMessageBox.warning(self, "Erreur", f"Export impossible : {e}")
            return
        QMessageBox.information(self, "Succès", f"Rapport exporté :\n{path}")
