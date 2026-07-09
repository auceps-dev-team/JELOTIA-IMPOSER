import sys
import uuid
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from src.core.models.domain import JobSettings, PlacedItem, Sheet
from src.core.output_manager import OutputManager
from src.core.system_notifier import SystemNotifier
from src.database.repository import DatabaseRepository
from src.ui.widgets.job_queue import JobsWidget
from src.ui.widgets.settings_view import SettingsWidget


def _resolve_app_icon() -> Path | None:
    """Locates jelotia.ico whether running from source (installer/jelotia.ico)
    or as a frozen PyInstaller build (bundled at the root of sys._MEIPASS via
    the spec file's datas entry)."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidate = base / "jelotia.ico"
    else:
        candidate = Path(__file__).resolve().parents[2] / "installer" / "jelotia.ico"
    return candidate if candidate.exists() else None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JELOTIA IMPOSER")
        self.resize(1200, 800)
        icon_path = _resolve_app_icon()
        if icon_path:
            self.setWindowIcon(QIcon(str(icon_path)))

        # Stores job_name → the full Sheet objects (with PlacedItem layout data),
        # accumulated across sub-job chunks. Needed for preview navigation,
        # manual repositioning, and grouped re-export — not just the rendered PDFs.
        self._job_sheets: dict[str, list[Sheet]] = {}
        # Stores job_name → the JobSettings used to submit it, so sheets can be
        # regenerated/re-exported later (manual edits, grouped export).
        self._job_settings: dict[str, JobSettings] = {}
        # Stores job_name → its original input file paths, so a failed job can
        # actually be resumed (re-run through the pipeline), not just have its
        # status reset with nothing to reprocess.
        self._job_source_paths: dict[str, list[str]] = {}
        # Stores job_name → its canonical job_id, so resuming reuses the same
        # id (and DB row / table row) instead of creating a duplicate job.
        self._job_ids: dict[str, uuid.UUID] = {}

        self.db = DatabaseRepository()

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
        self.load_persisted_jobs()
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
        self.worker_thread.finalize_completed.connect(self.handle_finalize_completed)
        self.worker_thread.finalize_failed.connect(self.handle_finalize_failed)
        self.worker_thread.start()

        # Aggregate state per job_name, keyed the same way multiple chunks of
        # one logical job share a single Jobs-table row. See _submit_job().
        self._job_group_state: dict[str, dict] = {}

    # ExportEngine only implements these formats; other combo entries fall back to PDF/X.
    _EXPORT_FORMAT_MAP = {
        "PDF (STANDARD)": "PDF",
        "JDF": "PDF/X-4",
    }

    def _build_job_settings(self) -> JobSettings:
        """Builds JobSettings from the user-configured config.json (Settings screen)
        instead of hardcoded defaults, so imposition/preflight/export settings
        actually take effect on the next job."""
        from src.utils.config_manager import ConfigManager

        config = ConfigManager()
        export_format = (config.get("export", "format") or "PDF/X-4").upper()
        export_format = self._EXPORT_FORMAT_MAP.get(export_format, export_format)

        return JobSettings(
            sheet_width_mm=float(config.get("imposition", "sheet_width") or 900.0),
            sheet_height_mm=float(config.get("imposition", "sheet_height") or 600.0),
            gap_mm=float(config.get("imposition", "spacing") or 3.0),
            allow_rotation=bool(config.get("imposition", "rotation_allowed")),
            min_dpi=int(config.get("preflight", "min_dpi") or 300),
            export_format=export_format,
            export_dpi=int(config.get("export", "dpi") or 300),
            generate_thumbnail=True,
        )

    def _submit_job(self, job_name: str, file_paths: list[str], reuse_job_id: uuid.UUID = None) -> str:
        """Submit a job to the worker pool.

        WorkerPoolManager parallelizes at the job level: one process_job_files()
        call runs entirely on a single worker, regardless of max_workers. A job
        with thousands of files would therefore run on exactly one CPU core.
        To actually use the configured worker pool, large batches are split
        into chunks (automation.max_files_per_job) and dispatched as separate
        sub-jobs, all aggregated under the single `job_name` row in the Jobs
        table (see _job_group_state / handle_job_* below).

        All chunks share the SAME job_id (rather than each getting its own):
        nesting needs every chunk's files combined to pack sheets well (see
        job_processor.finalize_job_sheets), so once every chunk completes we
        submit one finalize step for the whole logical job, keyed by this
        shared id, instead of nesting each chunk's files independently.

        `reuse_job_id` is passed when resuming a previously failed job, so it
        updates the same DB row / table row instead of creating a duplicate.

        Returns the shared job UUID string.
        """
        from src.utils.config_manager import ConfigManager

        paths = [Path(f) for f in file_paths if Path(f).exists()]
        settings = self._build_job_settings()
        self._job_settings[job_name] = settings

        chunk_size = max(1, int(ConfigManager().get("automation", "max_files_per_job") or 50))
        chunks = [paths[i : i + chunk_size] for i in range(0, len(paths), chunk_size)] or [[]]

        job_id = reuse_job_id or uuid.uuid4()
        job_id_str = str(job_id)
        self.jobs_view.job_uuid_map[job_id_str] = job_name
        self._job_ids[job_name] = job_id

        source_path_strs = [str(p) for p in paths]
        self._job_source_paths[job_name] = source_path_strs
        self.db.create_job_stub(job_id_str, job_name, source_path_strs, settings)

        self._job_group_state[job_name] = {
            "job_id": job_id,
            "total": len(chunks),
            "started": 0,
            "completed": 0,
            "file_items": [],
            "errored": False,
            "preflight_map": {},
        }

        for chunk in chunks:
            self.worker_thread.submit_job(job_id, chunk, settings)
        return job_id_str

    def handle_job_started(self, job_id: str):
        job_name = self.jobs_view.job_uuid_map.get(job_id, job_id[:8])
        group = self._job_group_state.get(job_name)
        self.jobs_view.update_job_status(job_id, "PROCESSING")

        # Only count once per logical job, not once per sub-job chunk.
        if group is None or group["started"] == 0:
            self.status_bar.showMessage(f"Job {job_name} en cours...")
            count = int(self.dashboard_view.card_active_jobs.value_label.text())
            self.dashboard_view.card_active_jobs.value_label.setText(str(count + 1))
            self.db.update_job_status(job_id, "PROCESSING")
        if group is not None:
            group["started"] += 1

    def handle_job_completed(self, job_id: str, files: list):
        """A single chunk's import/preflight/correction finished. Accumulates
        its FileItems; once every chunk of the logical job is done, submits
        one finalize step (nesting/layout/export) for all of them combined."""
        job_name = self.jobs_view.job_uuid_map.get(job_id, job_id[:8])
        group = self._job_group_state.get(job_name)

        # Collect preflight warnings, aggregated per logical job so we show
        # a single dialog at the end instead of one per chunk.
        from src.core.models.domain import PreflightStatus
        preflight_map = group["preflight_map"] if group is not None else {}
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

        if group is None:
            # No group state (shouldn't normally happen — every submit_job
            # goes through _submit_job); finalize immediately with just these files.
            self.worker_thread.submit_finalize(uuid.UUID(job_id), files, self._build_job_settings(), job_name)
            return

        group["file_items"].extend(files)
        group["completed"] += 1

        if group["completed"] < group["total"]:
            # Other chunks still running; reflect progress without finalizing.
            self.jobs_view.update_job_status(job_id, "PROCESSING")
            return

        self._dispatch_finalize(job_name, group)

    def handle_job_failed(self, job_id: str, error_msg: str):
        job_name = self.jobs_view.job_uuid_map.get(job_id, job_id[:8])
        group = self._job_group_state.get(job_name)

        err_count = int(self.dashboard_view.card_errors.value_label.text())
        self.dashboard_view.card_errors.value_label.setText(str(err_count + 1))

        if group is None:
            self.status_bar.showMessage(f"Erreur — Job {job_name}")
            self.notifier.notify("Erreur Job", f"{job_name}: {error_msg}", True)
            self.jobs_view.update_job_status(job_id, "ERROR")
            self.db.update_job_status(job_id, "ERROR")
            count = int(self.dashboard_view.card_active_jobs.value_label.text())
            self.dashboard_view.card_active_jobs.value_label.setText(str(max(0, count - 1)))
            return

        group["errored"] = True
        group["completed"] += 1

        if group["completed"] < group["total"]:
            self.jobs_view.update_job_status(job_id, "PROCESSING")
            return

        self._dispatch_finalize(job_name, group)

    def _dispatch_finalize(self, job_name: str, group: dict):
        """All chunks of this logical job are done — submit the combined
        FileItems for nesting/layout/export as a single finalize step."""
        job_id_str = str(group["job_id"])
        if not group["file_items"]:
            # Nothing to nest (every chunk failed, or produced no files).
            self.db.update_job_status(job_id_str, "ERROR")
            self._finalize_job(job_name, job_id_str, 0, group["preflight_map"], errored=True)
            del self._job_group_state[job_name]
            return

        settings = self._job_settings.get(job_name) or self._build_job_settings()
        self.jobs_view.update_job_status(job_id_str, "PROCESSING")
        self.db.update_job_files(job_id_str, group["file_items"])
        self.worker_thread.submit_finalize(group["job_id"], group["file_items"], settings, job_name)

    def handle_finalize_completed(self, job_id: str, sheets: list):
        job_name = self.jobs_view.job_uuid_map.get(job_id, job_id[:8])
        group = self._job_group_state.get(job_name)

        valid_sheets = [s for s in sheets if s.export_path and s.export_path.exists()]
        if valid_sheets:
            self._job_sheets[job_name] = valid_sheets
        self.db.update_job_sheets(job_id, valid_sheets)

        preflight_map = group["preflight_map"] if group is not None else {}
        errored = group["errored"] if group is not None else False
        self.db.update_job_status(job_id, "ERROR" if errored else "DONE")
        self._finalize_job(job_name, job_id, len(sheets), preflight_map, errored=errored)

        if group is not None:
            del self._job_group_state[job_name]

    def handle_finalize_failed(self, job_id: str, error_msg: str):
        job_name = self.jobs_view.job_uuid_map.get(job_id, job_id[:8])
        group = self._job_group_state.get(job_name)

        self.notifier.notify("Erreur Job", f"{job_name}: {error_msg}", True)
        self.db.update_job_status(job_id, "ERROR")
        preflight_map = group["preflight_map"] if group is not None else {}
        self._finalize_job(job_name, job_id, 0, preflight_map, errored=True)

        if group is not None:
            del self._job_group_state[job_name]

    def _finalize_job(self, job_name: str, job_id: str, sheet_count: int, preflight_map: dict, errored: bool):
        """Marks a logical job (all its sub-job chunks) as finished: updates
        the Jobs row, notifies, shows the aggregated preflight dialog once,
        and updates dashboard counters exactly once per logical job."""
        status = "ERROR" if errored else "DONE"
        self.status_bar.showMessage(f"Job {job_name} terminé — {sheet_count} planche(s)")
        self.notifier.notify("Job Terminé", f"{job_name} — {sheet_count} planche(s) générée(s).", errored)
        self.jobs_view.update_job_status(job_id, status, sheet_count)

        if preflight_map:
            from src.ui.widgets.preflight_report import PreflightDialog
            PreflightDialog(self, preflight_map).exec()

        count = int(self.dashboard_view.card_active_jobs.value_label.text())
        self.dashboard_view.card_active_jobs.value_label.setText(str(max(0, count - 1)))
        sheets_total = int(self.dashboard_view.card_sheets.value_label.text())
        self.dashboard_view.card_sheets.value_label.setText(str(sheets_total + sheet_count))

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
        settings = self._job_settings.get(job_name)
        if sheets:
            self.preview_view.load_job(job_name, sheets, settings)
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
        icon_path = _resolve_app_icon()
        self.tray_icon = QSystemTrayIcon(QIcon(str(icon_path)) if icon_path else QIcon(), self)
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
        from src.core.auto_processor import AutoProcessor
        from src.core.hot_folder_monitor import HotFolderMonitor
        from src.utils.config_manager import ConfigManager

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
    #  Job persistence                                                     #
    # ------------------------------------------------------------------ #

    def load_persisted_jobs(self):
        """Repopulates the Jobs table and in-memory state from the database
        on startup, so job history (and completed jobs' planches) survives an
        app restart or crash instead of vanishing."""
        try:
            recovered = self.db.recover_processing_jobs()
            if recovered:
                self.status_bar.showMessage(
                    f"{recovered} job(s) interrompu(s) remis en attente après redémarrage."
                )
            jobs = self.db.get_all_jobs()
        except Exception as e:
            self.status_bar.showMessage(f"Erreur de chargement des jobs sauvegardés : {e}")
            return

        for job in jobs:
            status = "PENDING" if job.status == "PROCESSING" else job.status
            self.jobs_view.job_uuid_map[job.id] = job.name
            self._job_ids[job.name] = uuid.UUID(job.id)
            self._job_source_paths[job.name] = list(job.source_paths or [])

            try:
                self._job_settings[job.name] = JobSettings(**(job.settings or {}))
            except Exception:
                pass

            self.jobs_view.add_job(job.name, len(job.source_paths or []), status, date_str=job.created_at)
            self.jobs_view.update_job_status(job.id, status, len(job.sheets))

            if job.sheets:
                restored_sheets = []
                for sm in job.sheets:
                    try:
                        items = [PlacedItem(**it) for it in (sm.items or [])]
                        restored_sheets.append(
                            Sheet(
                                job_id=uuid.UUID(job.id),
                                sheet_number=sm.sheet_number,
                                width_mm=sm.width_mm,
                                height_mm=sm.height_mm,
                                fill_rate=sm.fill_rate or 0.0,
                                items=items,
                                export_path=Path(sm.export_path) if sm.export_path else None,
                            )
                        )
                    except Exception as e:
                        self.status_bar.showMessage(f"Planche non restaurée pour {job.name} : {e}")
                if restored_sheets:
                    self._job_sheets[job.name] = restored_sheets

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
        """Actually re-runs a failed job through the whole pipeline again,
        from its original source files — reusing the same job_id so this
        updates the existing row (DB and table) instead of duplicating it."""
        source_paths = self._job_source_paths.get(job_name)
        if not source_paths:
            self.status_bar.showMessage(
                f"Impossible de reprendre {job_name} : fichiers sources introuvables."
            )
            self.jobs_view.update_job_status(job_name, "ERROR")
            return

        self.status_bar.showMessage(f"Job repris: {job_name}")
        self.notifier.notify("Job Repris", job_name, False)
        self._submit_job(job_name, source_paths, reuse_job_id=self._job_ids.get(job_name))

    # ------------------------------------------------------------------ #
    #  Cleanup                                                             #
    # ------------------------------------------------------------------ #

    def closeEvent(self, event):
        for attr in ("hf_monitor", "auto_processor", "worker_thread"):
            obj = getattr(self, attr, None)
            if obj:
                obj.stop()
        super().closeEvent(event)
