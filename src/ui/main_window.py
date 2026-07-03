import sys
import uuid
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QFrame, QPushButton, QStackedWidget, QLabel,
    QSystemTrayIcon, QMenu
)
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt

from src.ui.widgets.job_queue import JobsWidget
from src.ui.widgets.settings_view import SettingsWidget
from src.core.system_notifier import SystemNotifier
from src.core.output_manager import OutputManager
from src.core.models.domain import JobSettings


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JELOTIA IMPOSER")
        self.resize(1200, 800)

        # Stores job_name → list of export PDF paths for preview
        self._job_sheets: dict[str, list[Path]] = {}

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.setup_sidebar()
        self.setup_stacked_widget()

        self.notifier = SystemNotifier(self)
        self.output_manager = OutputManager()

        self.setup_status_bar()
        self.setup_system_tray()
        self.setup_worker_pool()
        self.setup_hot_folder_monitor()
        self.recover_orphan_jobs()

    # ------------------------------------------------------------------ #
    #  Worker pool                                                         #
    # ------------------------------------------------------------------ #

    def setup_worker_pool(self):
        from src.core.worker_thread import WorkerPoolThread
        self.worker_thread = WorkerPoolThread(self)
        self.worker_thread.job_started.connect(self.handle_job_started)
        self.worker_thread.job_completed.connect(self.handle_job_completed)
        self.worker_thread.job_failed.connect(self.handle_job_failed)
        self.worker_thread.start()

    def _submit_job(self, job_name: str, file_paths: list[str]) -> str:
        """Submit a job to the worker pool. Returns the job UUID string."""
        job_id = uuid.uuid4()
        job_id_str = str(job_id)
        self.jobs_view.job_uuid_map[job_id_str] = job_name

        settings = JobSettings(
            sheet_width_mm=900.0,
            sheet_height_mm=600.0,
            gap_mm=3.0,
            allow_rotation=True,
            min_dpi=300,
            generate_thumbnail=True,
        )
        paths = [Path(f) for f in file_paths if Path(f).exists()]
        self.worker_thread.submit_job(job_id, paths, settings)
        return job_id_str

    def handle_job_started(self, job_id: str):
        self.status_bar.showMessage(f"Job {job_id[:8]} en cours...")
        self.jobs_view.update_job_status(job_id, "PROCESSING")

        count = int(self.dashboard_view.card_active_jobs.value_label.text())
        self.dashboard_view.card_active_jobs.value_label.setText(str(count + 1))

    def handle_job_completed(self, job_id: str, files: list, sheets: list):
        job_name = self.jobs_view.job_uuid_map.get(job_id, job_id[:8])
        sheet_count = len(sheets)
        self.status_bar.showMessage(f"Job {job_name} terminé — {sheet_count} planche(s)")
        self.notifier.notify("Job Terminé", f"{job_name} — {sheet_count} planche(s) générée(s).", False)
        self.jobs_view.update_job_status(job_id, "DONE", sheet_count)

        # Store sheet paths for preview
        sheet_paths = [s.export_path for s in sheets if s.export_path and s.export_path.exists()]
        if sheet_paths:
            self._job_sheets[job_name] = sheet_paths

        # Show preflight warnings if any
        from src.core.models.domain import PreflightStatus
        preflight_map = {}
        for f in files:
            if f.preflight_status in (PreflightStatus.ERROR, PreflightStatus.WARNING) and f.preflight_errors:
                preflight_map[f.path.name] = [
                    {
                        "type": e.type.value,
                        "desc": e.message,
                        "solution": "Vérifiez le fichier source.",
                    }
                    for e in f.preflight_errors
                ]
        if preflight_map:
            from src.ui.widgets.preflight_report import PreflightDialog
            PreflightDialog(self, preflight_map).exec()

        # Update dashboard
        count = int(self.dashboard_view.card_active_jobs.value_label.text())
        self.dashboard_view.card_active_jobs.value_label.setText(str(max(0, count - 1)))
        sheets_total = int(self.dashboard_view.card_sheets.value_label.text())
        self.dashboard_view.card_sheets.value_label.setText(str(sheets_total + sheet_count))

    def handle_job_failed(self, job_id: str, error_msg: str):
        job_name = self.jobs_view.job_uuid_map.get(job_id, job_id[:8])
        self.status_bar.showMessage(f"Erreur — Job {job_name}")
        self.notifier.notify("Erreur Job", f"{job_name}: {error_msg}", True)
        self.jobs_view.update_job_status(job_id, "ERROR")

        count = int(self.dashboard_view.card_active_jobs.value_label.text())
        self.dashboard_view.card_active_jobs.value_label.setText(str(max(0, count - 1)))
        err_count = int(self.dashboard_view.card_errors.value_label.text())
        self.dashboard_view.card_errors.value_label.setText(str(err_count + 1))

    # ------------------------------------------------------------------ #
    #  Sidebar                                                             #
    # ------------------------------------------------------------------ #

    def setup_sidebar(self):
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(250)

        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(0, 20, 0, 0)
        self.sidebar_layout.setSpacing(5)

        title_label = QLabel("JELOTIA IMPOSER")
        title_label.setStyleSheet(
            "color: white; font-size: 18px; font-weight: bold; padding: 10px 20px;"
        )
        self.sidebar_layout.addWidget(title_label)
        self.sidebar_layout.addSpacing(20)

        self.btn_dashboard = QPushButton("Dashboard")
        self.btn_dashboard.setCheckable(True)
        self.btn_dashboard.setChecked(True)

        self.btn_jobs = QPushButton("Jobs & Files")
        self.btn_jobs.setCheckable(True)

        self.btn_settings = QPushButton("Settings")
        self.btn_settings.setCheckable(True)

        self.sidebar_layout.addWidget(self.btn_dashboard)
        self.sidebar_layout.addWidget(self.btn_jobs)
        self.sidebar_layout.addWidget(self.btn_settings)
        self.sidebar_layout.addStretch()
        self.main_layout.addWidget(self.sidebar)

        self.btn_dashboard.clicked.connect(lambda: self.switch_view(0, self.btn_dashboard))
        self.btn_jobs.clicked.connect(lambda: self.switch_view(1, self.btn_jobs))
        self.btn_settings.clicked.connect(lambda: self.switch_view(3, self.btn_settings))

    # ------------------------------------------------------------------ #
    #  Stacked widget                                                      #
    # ------------------------------------------------------------------ #

    def setup_stacked_widget(self):
        self.stacked_widget = QStackedWidget()
        self.main_layout.addWidget(self.stacked_widget)

        from src.ui.widgets.dashboard import DashboardWidget
        self.dashboard_view = DashboardWidget()

        self.jobs_view = JobsWidget()
        self.jobs_view.cancel_job_requested.connect(self.handle_cancel_job)
        self.jobs_view.resume_job_requested.connect(self.handle_resume_job)
        self.jobs_view.job_created.connect(self._on_job_created)
        self.jobs_view.view_details_requested.connect(self.show_preview)

        from src.ui.widgets.sheet_preview import SheetPreviewWidget
        self.preview_view = SheetPreviewWidget()

        self.settings_view = SettingsWidget()

        self.stacked_widget.addWidget(self.dashboard_view)
        self.stacked_widget.addWidget(self.jobs_view)
        self.stacked_widget.addWidget(self.preview_view)
        self.stacked_widget.addWidget(self.settings_view)

    def _on_job_created(self, job_name: str, file_paths: list):
        """Called when a manual job is created in the dialog."""
        if file_paths:
            self._submit_job(job_name, file_paths)
        else:
            self.status_bar.showMessage(f"Job {job_name} créé (aucun fichier — en attente)")

    def show_preview(self, job_name: str):
        self.stacked_widget.setCurrentWidget(self.preview_view)
        sheets = self._job_sheets.get(job_name, [])
        if sheets:
            # Show first sheet's PDF
            self.preview_view.load_pdf(str(sheets[0]), fill_rate=None)
        else:
            self.preview_view.info_label.setText(
                f"Aperçu pour {job_name} — planches non encore générées."
            )

    def switch_view(self, index: int, button: QPushButton):
        self.stacked_widget.setCurrentIndex(index)
        for btn in (self.btn_dashboard, self.btn_jobs, self.btn_settings):
            btn.setChecked(btn is button)

    # ------------------------------------------------------------------ #
    #  Status bar & tray                                                   #
    # ------------------------------------------------------------------ #

    def setup_status_bar(self):
        self.status_bar = self.statusBar()
        self.status_bar.showMessage("Prêt | 0 job actif")

    def setup_system_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray_icon = QSystemTrayIcon(QIcon(), self)
        self.tray_menu = QMenu()
        self.tray_menu.addAction("Afficher").triggered.connect(self.showNormal)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction("Quitter").triggered.connect(sys.exit)
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.setToolTip("JELOTIA IMPOSER")
        self.tray_icon.show()
        self.tray_icon.activated.connect(self._tray_activated)

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.showNormal()

    # ------------------------------------------------------------------ #
    #  Hot folder                                                          #
    # ------------------------------------------------------------------ #

    def setup_hot_folder_monitor(self):
        from src.utils.config_manager import ConfigManager
        from src.core.hot_folder_monitor import HotFolderMonitor
        from src.core.auto_processor import AutoProcessor

        config = ConfigManager()
        input_path = config.get("paths", "input") or str(
            Path.home() / "Jelotia" / "HotFolder" / "Input"
        )
        processing_path = str(Path(input_path).parent / "Processing")

        self.auto_processor = AutoProcessor(self)
        self.auto_processor.job_grouped.connect(self._handle_hot_folder_job)
        self.auto_processor.start()

        self.hf_monitor = HotFolderMonitor(input_path, processing_path)
        self.hf_monitor.signals.new_job_ready.connect(self.auto_processor.add_file)
        self.hf_monitor.start()

    def _handle_hot_folder_job(self, group_name: str, files: list):
        self.jobs_view.add_job(group_name, len(files), "PENDING")
        self.status_bar.showMessage(f"Hot Folder: {group_name} ({len(files)} fichier(s))")
        self.notifier.notify("Nouveau Job", f"{group_name} — {len(files)} fichier(s)", False)
        self._submit_job(group_name, files)

    # ------------------------------------------------------------------ #
    #  Orphan recovery                                                     #
    # ------------------------------------------------------------------ #

    def recover_orphan_jobs(self):
        processing_dir = Path(self.output_manager.processing_dir)
        if not processing_dir.exists():
            return
        for p in processing_dir.iterdir():
            if p.is_file() and p.suffix.lower() in (".pdf", ".tiff", ".jpg", ".png"):
                self.auto_processor.add_file(str(p))

    # ------------------------------------------------------------------ #
    #  Job actions                                                         #
    # ------------------------------------------------------------------ #

    def handle_cancel_job(self, job_name: str):
        self.status_bar.showMessage(f"Job annulé: {job_name}")
        self.notifier.notify("Job Annulé", job_name, False)

    def handle_resume_job(self, job_name: str):
        self.status_bar.showMessage(f"Job repris: {job_name}")
        self.notifier.notify("Job Repris", job_name, False)

    # ------------------------------------------------------------------ #
    #  Cleanup                                                             #
    # ------------------------------------------------------------------ #

    def closeEvent(self, event):
        for attr in ("hf_monitor", "auto_processor", "worker_thread"):
            obj = getattr(self, attr, None)
            if obj:
                obj.stop()
        super().closeEvent(event)
