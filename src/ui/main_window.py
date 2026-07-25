import sys
import uuid
from pathlib import Path

from PySide6.QtGui import QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from src.core.models.domain import JobSettings, PlacedItem, Sheet
from src.core.output_manager import OutputManager
from src.core.system_notifier import SystemNotifier
from src.database.repository import DatabaseRepository
from src.ui.theme import ThemeManager
from src.ui.widgets.common import LedDot
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
        # Never open larger than the (logical) screen: on scaled displays
        # (e.g. 1366x768 or 1920x1080 at 125-150% Windows zoom) a hardcoded
        # 1200x800 can already overflow the available desktop area.
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            self.resize(min(1200, avail.width()), min(800, avail.height()))
        else:
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
        # Stores job_name → {path: quantity}, so every re-submission (resume,
        # duplicate, gang) reprints the ordered number of copies.
        self._job_quantities: dict[str, dict] = {}

        self.db = DatabaseRepository()

        from src.core.licensing import current_license

        self.license = current_license()

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.setup_topnav()
        self.setup_stacked_widget()

        self.notifier = SystemNotifier(self)
        self.output_manager = OutputManager()

        self.setup_status_bar()
        self._apply_license_to_ui()
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
            margin_mm=float(config.get("imposition", "margin") or 0.0),
            allow_rotation=bool(config.get("imposition", "rotation_allowed")),
            add_bleed_mm=float(config.get("imposition", "add_bleed") or 0.0),
            min_dpi=int(config.get("preflight", "min_dpi") or 300),
            icc_profile_path=str(config.get("export", "icc_profile") or ""),
            export_format=export_format,
            export_dpi=int(config.get("export", "dpi") or 300),
            generate_thumbnail=True,
            plotter_marks=str(config.get("imposition", "plotter_marks") or "none"),
            plotter_mark_length_mm=float(
                config.get("imposition", "plotter_mark_length") or 15.0
            ),
            cut_contour_spot=bool(config.get("export", "cut_contour")),
            watermark_text=(
                "JELOTIA IMPOSER — NON LICENCIÉ" if self.license.watermark else ""
            ),
        )

    # Priority labels (JobDialog) -> queue rank (WorkerPoolManager).
    _PRIORITY_RANKS = {"Urgente": 0, "Haute": 1, "Normale": 2}

    def _submit_job(
        self,
        job_name: str,
        file_paths: list[str],
        overrides: dict = None,
        reuse_job_id: uuid.UUID = None,
        settings_override: JobSettings = None,
    ) -> str:
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

        `overrides` (from JobDialog) may carry a per-job sheet size
        (`sheet_width_mm`/`sheet_height_mm`, falling back to the global
        setting when omitted) and a per-file quantity map
        (`quantities: {path: qty}`, applied by process_job_files after import).

        Returns the shared job UUID string.
        """
        from src.utils.config_manager import ConfigManager

        overrides = overrides or {}
        paths = [Path(f) for f in file_paths if Path(f).exists()]

        # A manufacturing preset ("gamme") carries the product's whole recipe.
        preset_id = overrides.get("preset_id")
        if settings_override is None and preset_id:
            try:
                from src.core.presets import PresetStore

                preset = PresetStore().load(preset_id)
                settings_override = preset.settings.model_copy()
                self._log(f"Job {job_name} — gamme « {preset.name} »")
            except Exception as e:
                self._log(f"Gamme illisible ({e}) — réglages globaux utilisés")

        # settings_override (job duplication / preset) reuses those settings
        # instead of whatever the global config says today.
        settings = settings_override or self._build_job_settings()
        if overrides.get("sheet_width_mm"):
            settings.sheet_width_mm = overrides["sheet_width_mm"]
        if overrides.get("sheet_height_mm"):
            settings.sheet_height_mm = overrides["sheet_height_mm"]
        # Per-job target file size. Truthy-only so a job left at "origine" (0)
        # never wipes a size the selected gamme already carries.
        if overrides.get("target_file_width_mm"):
            settings.target_file_width_mm = overrides["target_file_width_mm"]
        if overrides.get("target_file_height_mm"):
            settings.target_file_height_mm = overrides["target_file_height_mm"]
        self._job_settings[job_name] = settings

        priority_label = overrides.get("priority") or "Normale"
        priority = self._PRIORITY_RANKS.get(priority_label, 2)
        if priority < 2:
            self._log(f"Job {job_name} soumis en priorité {priority_label.upper()}")
        # Normalize the per-file quantity keys to str(Path(...)): the dialog
        # keys them by the raw path string (forward slashes, as Qt returns),
        # but process_job_files looks them up by str(Path(file_path)) — which
        # uses OS-native separators (backslashes on Windows). Without this the
        # keys never matched and every file silently stayed at quantity 1.
        raw_quantities = overrides.get("quantities") or {}
        quantities = {str(Path(k)): v for k, v in raw_quantities.items()}

        chunk_size = max(1, int(ConfigManager().get("automation", "max_files_per_job") or 50))
        chunks = [paths[i : i + chunk_size] for i in range(0, len(paths), chunk_size)] or [[]]

        job_id = reuse_job_id or uuid.uuid4()
        job_id_str = str(job_id)
        self.jobs_view.job_uuid_map[job_id_str] = job_name
        self._job_ids[job_name] = job_id

        source_path_strs = [str(p) for p in paths]
        self._job_source_paths[job_name] = source_path_strs
        self._job_quantities[job_name] = dict(quantities)
        self.db.create_job_stub(
            job_id_str, job_name, source_path_strs, settings, quantities=quantities
        )

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
            self.worker_thread.submit_job(job_id, chunk, settings, quantities, priority=priority)
        return job_id_str

    def handle_job_started(self, job_id: str):
        job_name = self.jobs_view.job_uuid_map.get(job_id, job_id[:8])
        group = self._job_group_state.get(job_name)
        self.jobs_view.update_job_status(job_id, "PROCESSING")

        # Only log/persist once per logical job, not once per sub-job chunk.
        if group is None or group["started"] == 0:
            self._log(f"Job {job_name} en cours...")
            self.db.update_job_status(job_id, "PROCESSING")
            self._refresh_dashboard()
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

        if group is None:
            self._log(f"Erreur — Job {job_name}")
            self.notifier.notify("Erreur Job", f"{job_name}: {error_msg}", True)
            self.jobs_view.update_job_status(job_id, "ERROR")
            self.db.update_job_status(job_id, "ERROR")
            self._refresh_dashboard()
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
        and refreshes the dashboard from the DB (which the caller has already
        updated with this job's final status/sheets)."""
        status = "ERROR" if errored else "DONE"
        self._log(f"Job {job_name} terminé — {sheet_count} planche(s)")
        self.notifier.notify("Job Terminé", f"{job_name} — {sheet_count} planche(s) générée(s).", errored)
        self.jobs_view.update_job_status(job_id, status, sheet_count)

        if preflight_map:
            from src.ui.widgets.preflight_report import PreflightDialog
            PreflightDialog(self, preflight_map).exec()

        self._refresh_dashboard()

    def _refresh_dashboard(self) -> None:
        """Recomputes all dashboard KPIs and the production chart from the DB —
        the single source of truth — instead of nudging label counters by hand
        (which drifted: active jobs were decremented twice and errors counted
        on success). Aggregated in SQL, so it stays cheap at high job counts."""
        self.dashboard_view.refresh_stats(self.db.get_dashboard_stats())

    # ------------------------------------------------------------------ #
    #  Top navigation (F1-F4)                                              #
    # ------------------------------------------------------------------ #

    def setup_topnav(self):
        self.topnav = QFrame()
        self.topnav.setObjectName("topnav")
        self.topnav.setFixedHeight(44)

        layout = QHBoxLayout(self.topnav)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.btn_dashboard = QPushButton("F1·DASHBOARD")
        self.btn_jobs = QPushButton("F2·JOBS")
        self.btn_planches = QPushButton("F3·PLANCHES")
        self.btn_qr = QPushButton("F4·QR")
        self.btn_pdf = QPushButton("F5·PDF")
        self.btn_settings = QPushButton("F6·CONFIG")
        self.btn_sysinfo = QPushButton("F7·INFO SYSTÈME")
        # Order = stacked-widget indices (see setup_stacked_widget) = Fn keys.
        self._nav_buttons = (
            self.btn_dashboard, self.btn_jobs, self.btn_planches,
            self.btn_qr, self.btn_pdf, self.btn_settings, self.btn_sysinfo,
        )

        for index, btn in enumerate(self._nav_buttons):
            btn.setCheckable(True)
            btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
            layout.addWidget(btn)
            btn.clicked.connect(
                lambda checked=False, i=index, b=btn: self.switch_view(i, b)
            )
            # The labels promise F1..F7 — honor them as real shortcuts.
            shortcut = QShortcut(QKeySequence(f"F{index + 1}"), self)
            shortcut.activated.connect(
                lambda i=index, b=btn: self.switch_view(i, b)
            )
        layout.addStretch()
        self.main_layout.addWidget(self.topnav)

        self._set_active_nav(self.btn_dashboard)

    def _set_active_nav(self, button: QPushButton) -> None:
        for btn in self._nav_buttons:
            btn.setChecked(btn is button)
        if hasattr(self, "_status_context_label"):
            self._status_context_label.setText(button.text())

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
        self.jobs_view.delete_job_requested.connect(self.handle_delete_job)
        self.jobs_view.archive_job_requested.connect(self.handle_archive_job)
        self.jobs_view.duplicate_job_requested.connect(self.handle_duplicate_job)
        self.jobs_view.archives_requested.connect(self._show_archived_jobs)
        self.jobs_view.gang_requested.connect(self._show_gang_dialog)
        self.jobs_view.job_created.connect(self._on_job_created)
        self.jobs_view.view_details_requested.connect(self.show_preview)

        from src.ui.widgets.sheet_preview import SheetPreviewWidget
        self.preview_view = SheetPreviewWidget()

        self.settings_view = SettingsWidget()

        from src.ui.widgets.qr_generator import QRGeneratorWidget
        self.qr_view = QRGeneratorWidget()
        self.qr_view.imposition_job_requested.connect(self._handle_qr_imposition_job)

        from src.ui.widgets.pdf_editor_view import PdfEditorWidget
        self.pdf_view = PdfEditorWidget()

        from src.ui.widgets.system_info import SystemInfoWidget
        self.sysinfo_view = SystemInfoWidget(self.db)

        # Indices must match _nav_buttons order in setup_topnav (= Fn keys):
        # 0 dashboard, 1 jobs, 2 planches, 3 QR, 4 PDF, 5 config, 6 info.
        self.stacked_widget.addWidget(self.dashboard_view)
        self.stacked_widget.addWidget(self.jobs_view)
        self.stacked_widget.addWidget(self.preview_view)
        self.stacked_widget.addWidget(self.qr_view)
        self.stacked_widget.addWidget(self.pdf_view)
        self.stacked_widget.addWidget(self.settings_view)
        self.stacked_widget.addWidget(self.sysinfo_view)

    def _on_job_created(self, job_name: str, file_paths: list, overrides: dict):
        """Called when a manual job is created in the dialog."""
        if file_paths:
            if not self._volume_check(len(file_paths)):
                self.jobs_view.remove_job_row(job_name)
                return
            self._submit_job(job_name, file_paths, overrides=overrides)
        else:
            self._log(f"Job {job_name} créé (aucun fichier — en attente)")

    def _handle_qr_imposition_job(self, job_name: str, file_paths: list, overrides: dict):
        """A finished QR batch handed over for imposition: same flow as a hot
        folder job (row + submit), then jump to F2·JOBS so the operator sees
        the job running immediately."""
        self.jobs_view.add_job(job_name, len(file_paths), "PENDING")
        self._log(f"Lot QR: {job_name} ({len(file_paths)} fichier(s)) → imposition")
        self._submit_job(job_name, file_paths, overrides=overrides)
        self.switch_view(1, self.btn_jobs)

    def show_preview(self, job_name: str):
        self.stacked_widget.setCurrentWidget(self.preview_view)
        self._set_active_nav(self.btn_planches)
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
        self._set_active_nav(button)

    # ------------------------------------------------------------------ #
    #  Status bar & tray                                                   #
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    #  Licence enforcement                                                 #
    # ------------------------------------------------------------------ #

    def _apply_license_to_ui(self) -> None:
        """Locks the Enterprise-only controls (and explains why) whenever the
        active license doesn't allow them. Re-run after (de)activation."""
        gated = (
            (getattr(self.jobs_view, "btn_gang", None), "ganging"),
            (getattr(self.dashboard_view, "btn_report", None), "reports"),
            (getattr(self.settings_view, "btn_watch_rules", None), "watch_rules"),
        )
        for button, feature in gated:
            if button is None:
                continue
            allowed = self.license.allows(feature)
            button.setEnabled(allowed)
            if not allowed:
                button.setToolTip("Réservé à la licence Entreprise")

        label = self.license.label
        if hasattr(self, "_status_context_label"):
            # Surface the tier in the status bar so it's always visible.
            self.setWindowTitle(f"JELOTIA IMPOSER — {label}")

    def refresh_license(self) -> None:
        """Reloads the license after activation and re-applies every gate."""
        from src.core.licensing import current_license

        self.license = current_license(refresh=True)
        self._apply_license_to_ui()
        self._log(f"Licence : {self.license.label}")

    def _volume_check(self, incoming_files: int) -> bool:
        """True if this job may run under the current daily cap. Enterprise and
        any unlimited license always pass."""
        if self.license.unlimited_volume:
            return True
        cap = self.license.max_files_per_day
        already = self.db.files_processed_today()
        if already + incoming_files > cap:
            QMessageBox.warning(
                self, "Plafond journalier atteint",
                f"Licence {self.license.label} : {cap} fichiers/jour maximum.\n"
                f"Déjà traités aujourd'hui : {already}. "
                f"Ce job ({incoming_files}) dépasserait la limite.\n\n"
                "Passez en licence Entreprise pour un volume illimité.",
            )
            return False
        return True

    def _log(self, text: str) -> None:
        """Shows `text` in the status bar and, if the dashboard is already
        built, appends it to its rolling JOURNAL.SYSTEME panel — the single
        place every status update flows through, instead of duplicating the
        text at each call site."""
        self.status_bar.showMessage(text)
        if hasattr(self, "dashboard_view"):
            self.dashboard_view.push_log(text)

    def setup_status_bar(self):
        self.status_bar = self.statusBar()
        self._status_led = LedDot(ThemeManager.STATE_OK, size=7, glow=False)
        self.status_bar.addWidget(self._status_led)
        self._status_context_label = QLabel(self.btn_dashboard.text())
        self._status_context_label.setStyleSheet(
            f"color:{ThemeManager.ACCENT_TEXT}; padding-right:8px; border:none; background:transparent;"
        )
        self.status_bar.addPermanentWidget(self._status_context_label)
        self._log("PRÊT | 0 JOB ACTIF")

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
        """Watches the default input folder plus every configured watch rule
        (one folder = one product preset). All monitors feed the same
        AutoProcessor, which keeps their files apart by rule."""
        from src.core.auto_processor import AutoProcessor
        from src.core.hot_folder_monitor import HotFolderMonitor
        from src.core.watch_rules import active_rules, ensure_folders
        from src.utils.config_manager import ConfigManager

        config = ConfigManager()
        input_path = config.get("paths", "input") or str(
            Path.home() / "Jelotia" / "HotFolder" / "Input"
        )
        processing_path = str(Path(input_path).parent / "Processing")

        self.auto_processor = AutoProcessor(self)
        self.auto_processor.job_grouped.connect(self._handle_hot_folder_job)
        self.auto_processor.start()

        # Default folder: rule_id "" → global settings (unchanged behaviour).
        self.hf_monitors = []
        self.hf_monitor = HotFolderMonitor(input_path, processing_path)
        self.hf_monitor.signals.new_job_ready.connect(self.auto_processor.add_file)
        self.hf_monitor.start()
        self.hf_monitors.append(self.hf_monitor)

        rules = active_rules()
        ensure_folders(rules)
        for rule in rules:
            try:
                monitor = HotFolderMonitor(rule.folder, processing_path, rule_id=str(rule.id))
                monitor.signals.new_job_ready.connect(self.auto_processor.add_file)
                monitor.start()
                self.hf_monitors.append(monitor)
            except Exception as e:
                self._log(f"Surveillance impossible pour « {rule.name} » : {e}")
        if rules:
            self._log(f"{len(rules)} dossier(s) surveillé(s) avec gamme")

    def restart_hot_folder_monitors(self):
        """Applies edited watch rules without restarting the application."""
        for monitor in getattr(self, "hf_monitors", []):
            try:
                monitor.stop()
            except Exception:
                pass
        self.hf_monitors = []

        from src.core.hot_folder_monitor import HotFolderMonitor
        from src.core.watch_rules import active_rules, ensure_folders
        from src.utils.config_manager import ConfigManager

        config = ConfigManager()
        input_path = config.get("paths", "input") or str(
            Path.home() / "Jelotia" / "HotFolder" / "Input"
        )
        processing_path = str(Path(input_path).parent / "Processing")

        self.hf_monitor = HotFolderMonitor(input_path, processing_path)
        self.hf_monitor.signals.new_job_ready.connect(self.auto_processor.add_file)
        self.hf_monitor.start()
        self.hf_monitors.append(self.hf_monitor)

        rules = active_rules()
        ensure_folders(rules)
        for rule in rules:
            try:
                monitor = HotFolderMonitor(rule.folder, processing_path, rule_id=str(rule.id))
                monitor.signals.new_job_ready.connect(self.auto_processor.add_file)
                monitor.start()
                self.hf_monitors.append(monitor)
            except Exception as e:
                self._log(f"Surveillance impossible pour « {rule.name} » : {e}")
        self._log(f"Surveillance relancée — {len(self.hf_monitors)} dossier(s)")

    def _handle_hot_folder_job(self, group_name: str, files: list, rule_id: str = ""):
        """A hot folder produced a group: the watched folder's rule decides the
        product preset, so the job is produced with the right recipe without
        anyone touching the settings."""
        from src.core.watch_rules import load_rules, settings_for_rule

        rule = None
        if rule_id:
            rule = next((r for r in load_rules() if str(r.id) == rule_id), None)
        settings = settings_for_rule(rule, self._build_job_settings())

        self.jobs_view.add_job(group_name, len(files), "PENDING")
        origin = f" [{rule.name}]" if rule is not None else ""
        self._log(f"Hot Folder{origin}: {group_name} ({len(files)} fichier(s))")
        self.notifier.notify("Nouveau Job", f"{group_name} — {len(files)} fichier(s)", False)
        self._submit_job(group_name, files, settings_override=settings)

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
                self._log(
                    f"{recovered} job(s) interrompu(s) remis en attente après redémarrage."
                )
            jobs = self.db.get_all_jobs()
        except Exception as e:
            self._log(f"Erreur de chargement des jobs sauvegardés : {e}")
            return

        for job in jobs:
            self._register_persisted_job(job)

        # Populate the dashboard KPIs/chart from the restored job history.
        self._refresh_dashboard()

    def _register_persisted_job(self, job) -> None:
        """Registers one persisted JobModel into the view and the in-memory
        caches — used at startup for every non-archived job, and again when a
        job is restored from the archives."""
        status = "PENDING" if job.status == "PROCESSING" else job.status
        self.jobs_view.job_uuid_map[job.id] = job.name
        self._job_ids[job.name] = uuid.UUID(job.id)
        self._job_source_paths[job.name] = list(job.source_paths or [])
        self._job_quantities[job.name] = dict(getattr(job, "quantities", None) or {})

        try:
            self._job_settings[job.name] = JobSettings(**(job.settings or {}))
        except Exception:
            pass

        self.jobs_view.add_job(
            job.name, len(job.source_paths or []), status, date_str=job.created_at
        )
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
                    self._log(f"Planche non restaurée pour {job.name} : {e}")
            if restored_sheets:
                self._job_sheets[job.name] = restored_sheets

    def _show_archived_jobs(self):
        from src.ui.widgets.job_queue import ArchivedJobsDialog

        dialog = ArchivedJobsDialog(self.db, self)
        dialog.restored.connect(self._register_persisted_job)
        dialog.duplicated.connect(self._duplicate_from_model)
        dialog.exec()
        self._refresh_dashboard()  # deletions in the dialog affect the stats

    # ------------------------------------------------------------------ #
    #  Ganging (multi-job amalgame)                                        #
    # ------------------------------------------------------------------ #

    def _show_gang_dialog(self):
        """Offers to gang the PENDING orders that share production settings."""
        from src.core.ganging import find_gang_groups
        from src.ui.widgets.job_queue import GangDialog

        candidates = []
        for name in self.jobs_view.names_with_status("PENDING"):
            settings = self._job_settings.get(name)
            paths = self._job_source_paths.get(name) or []
            if settings is None:
                continue
            candidates.append((name, settings, paths, self._job_quantities.get(name) or {}))

        dialog = GangDialog(find_gang_groups(candidates), self)
        dialog.gang_requested.connect(self._create_gang)
        dialog.exec()

    def _create_gang(self, group) -> None:
        """Turns a compatible group into ONE job: all files, quantities summed,
        a single nesting pass (that's where the media saving comes from). The
        source orders are archived — kept for history, out of the way."""
        from src.core.ganging import gang_job_name

        paths = [p for p in group.merged_paths() if Path(p).exists()]
        if not paths:
            QMessageBox.warning(
                self, "Amalgame impossible",
                "Aucun fichier source de ces commandes n'existe encore sur le disque.",
            )
            return
        quantities = {p: q for p, q in group.merged_quantities().items() if p in set(paths)}

        gang_name = gang_job_name(group)
        members = [m.name for m in group.members]
        self.jobs_view.add_job(gang_name, len(paths), "PENDING")
        self._log(
            f"Amalgame : {len(members)} commande(s) → {gang_name} "
            f"({sum(quantities.values())} exemplaire(s))"
        )
        self._submit_job(
            gang_name, paths,
            overrides={"quantities": quantities},
            settings_override=group.settings.model_copy(),
        )

        # Archive the source orders: they are produced by the gang now.
        for name in members:
            job_id = self._job_ids.get(name)
            if job_id is not None and self.db.set_job_archived(str(job_id), True):
                self._forget_job(name)
        self._refresh_dashboard()

    # ------------------------------------------------------------------ #
    #  Job duplication                                                     #
    # ------------------------------------------------------------------ #

    def _launch_duplicate(
        self, base_name: str, source_paths: list, settings, quantities: dict = None
    ) -> None:
        """Shared duplication path: new unique name, new job_id, same source
        files, quantities and (where possible) the original job's settings."""
        existing = [p for p in source_paths if Path(p).exists()]
        if not existing:
            QMessageBox.warning(
                self, "Duplication impossible",
                f"Aucun des fichiers sources de « {base_name} » n'existe encore "
                "sur le disque.",
            )
            return
        missing = len(source_paths) - len(existing)

        new_name = f"{base_name} (copie)"
        counter = 2
        while self.jobs_view._find_row_by_name(new_name) != -1 or new_name in self._job_ids:
            new_name = f"{base_name} (copie {counter})"
            counter += 1

        self.jobs_view.add_job(new_name, len(existing), "PENDING")
        note = f" — {missing} fichier(s) source(s) introuvable(s) ignoré(s)" if missing else ""
        self._log(f"Job dupliqué : {base_name} → {new_name}{note}")
        self._submit_job(
            new_name, existing,
            overrides={"quantities": dict(quantities or {})},
            settings_override=settings,
        )

    def handle_duplicate_job(self, job_name: str):
        """DUPL. button on a Jobs row."""
        source_paths = self._job_source_paths.get(job_name) or []
        self._launch_duplicate(
            job_name, source_paths, self._job_settings.get(job_name),
            quantities=self._job_quantities.get(job_name),
        )

    def _duplicate_from_model(self, job) -> None:
        """DUPLIQUER from the archives dialog (JobModel from the DB)."""
        try:
            settings = JobSettings(**(job.settings or {}))
        except Exception:
            settings = None
        self._launch_duplicate(
            job.name, list(job.source_paths or []), settings,
            quantities=dict(job.quantities or {}),
        )

    # ------------------------------------------------------------------ #
    #  Orphan recovery                                                     #
    # ------------------------------------------------------------------ #

    def recover_orphan_jobs(self):
        processing_dir = Path(self.output_manager.processing_dir)
        if not processing_dir.exists():
            return
        for p in processing_dir.iterdir():
            if p.is_file() and p.suffix.lower() in (".pdf", ".tiff", ".jpg", ".png"):
                # No rule_id: a file already moved to Processing has lost the
                # folder it came from, so it is reprocessed with the global
                # settings rather than guessing a preset.
                self.auto_processor.add_file(str(p))

    # ------------------------------------------------------------------ #
    #  Job actions                                                         #
    # ------------------------------------------------------------------ #

    def handle_cancel_job(self, job_name: str):
        self._log(f"Job annulé: {job_name}")
        self.notifier.notify("Job Annulé", job_name, False)

    def _forget_job(self, job_name: str) -> None:
        """Drops every in-memory trace of a job (row + caches) after it was
        deleted or archived; the DB is the source of truth."""
        self.jobs_view.remove_job_row(job_name)
        job_id = self._job_ids.pop(job_name, None)
        if job_id is not None:
            self.jobs_view.job_uuid_map.pop(str(job_id), None)
        for cache in (self._job_sheets, self._job_settings, self._job_source_paths,
                      self._job_quantities, self._job_group_state):
            cache.pop(job_name, None)

    def handle_delete_job(self, job_name: str):
        """Permanent removal (already confirmed by the Jobs view)."""
        job_id = self._job_ids.get(job_name)
        if job_id is not None:
            self.db.delete_job(str(job_id))
        self._forget_job(job_name)
        self._log(f"Job supprimé : {job_name}")
        self._refresh_dashboard()

    def handle_archive_job(self, job_name: str):
        """Hides the job from the view while keeping it (and its production
        history) in the DB for potential reuse."""
        job_id = self._job_ids.get(job_name)
        if job_id is None:
            self._forget_job(job_name)
            return
        if self.db.set_job_archived(str(job_id), True):
            self._forget_job(job_name)
            self._log(f"Job archivé : {job_name}")
        else:
            self._log(f"Archivage impossible : {job_name}")

    def handle_resume_job(self, job_name: str):
        """Actually re-runs a failed job through the whole pipeline again,
        from its original source files — reusing the same job_id so this
        updates the existing row (DB and table) instead of duplicating it."""
        source_paths = self._job_source_paths.get(job_name)
        if not source_paths:
            self._log(
                f"Impossible de reprendre {job_name} : fichiers sources introuvables."
            )
            self.jobs_view.update_job_status(job_name, "ERROR")
            return

        self._log(f"Job repris: {job_name}")
        self.notifier.notify("Job Repris", job_name, False)
        # Carry the original quantities over: without them the resumed job
        # would silently reprint 1 copy of each file instead of the order.
        self._submit_job(
            job_name, source_paths,
            overrides={"quantities": self._job_quantities.get(job_name) or {}},
            reuse_job_id=self._job_ids.get(job_name),
            settings_override=self._job_settings.get(job_name),
        )

    # ------------------------------------------------------------------ #
    #  Cleanup                                                             #
    # ------------------------------------------------------------------ #

    def closeEvent(self, event):
        # Every watch-rule monitor must be stopped, not just the default one —
        # otherwise their observer threads outlive the window.
        for monitor in getattr(self, "hf_monitors", []):
            try:
                monitor.stop()
            except Exception:
                pass
        for attr in ("auto_processor", "worker_thread"):
            obj = getattr(self, attr, None)
            if obj:
                obj.stop()
        super().closeEvent(event)
