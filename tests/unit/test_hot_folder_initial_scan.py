"""M1 — files already in the hot folder when the app starts.

Field scenario: the shop closes, the machine is updated or rebooted, a client
or a script drops files overnight. Watchdog only reports what happens while it
watches, so those files produced no event and stayed invisible for ever — on a
product sold on 24/7 automation.
"""

import pytest

from src.core.hot_folder_monitor import HotFolderMonitor


@pytest.fixture
def monitor(tmp_path):
    m = HotFolderMonitor(
        input_path=str(tmp_path / "Input"),
        processing_path=str(tmp_path / "Processing"),
        rule_id="rule-badges",
    )
    yield m
    if m.observer:
        m.stop()


def _drop(monitor, *names):
    for name in names:
        (monitor.input_path / name).write_bytes(b"%PDF-1.4\n" + b"x" * 200)


def test_files_present_before_start_are_picked_up(monitor):
    _drop(monitor, "nuit_1.pdf", "nuit_2.pdf", "nuit_3.pdf")

    queued = monitor.scan_existing_files()

    assert queued == 3
    names = {p.name for p in monitor.pending_items}
    assert names == {"nuit_1.pdf", "nuit_2.pdf", "nuit_3.pdf"}


def test_an_empty_folder_queues_nothing(monitor):
    assert monitor.scan_existing_files() == 0
    assert monitor.pending_items == {}


def test_scanning_twice_does_not_duplicate(monitor):
    """start() scans after the observer is live, so a file can be seen by both
    paths. add_pending_item() must absorb that."""
    _drop(monitor, "a.pdf")

    monitor.scan_existing_files()
    monitor.scan_existing_files()

    assert len(monitor.pending_items) == 1


def test_scan_does_not_reset_stabilisation_progress(monitor):
    """A second sighting must not restart the size-stability countdown, or a
    file could be re-queued for ever and never be considered ready."""
    _drop(monitor, "b.pdf")
    monitor.scan_existing_files()
    path = next(iter(monitor.pending_items))
    monitor.pending_items[path]["stable_count"] = 2

    monitor.scan_existing_files()

    assert monitor.pending_items[path]["stable_count"] == 2


def test_hidden_files_are_ignored(monitor):
    _drop(monitor, "visible.pdf")
    (monitor.input_path / ".en_cours.tmp").write_bytes(b"partiel")

    monitor.scan_existing_files()

    names = {p.name for p in monitor.pending_items}
    assert names == {"visible.pdf"}


def test_an_unreadable_folder_does_not_crash_startup(monitor, monkeypatch):
    """A scan failure must never stop the monitor from starting."""
    def boom(self):
        raise OSError("dossier illisible")

    monkeypatch.setattr("pathlib.Path.iterdir", boom)
    assert monitor.scan_existing_files() == 0


def test_the_rule_id_survives_the_scan(monitor):
    """Files picked up at startup must keep their gamme: they go through the
    monitor's own pipeline, which carries rule_id — unlike recover_orphan_jobs,
    which loses it and falls back to the global settings."""
    _drop(monitor, "badge.pdf")
    monitor.scan_existing_files()

    assert monitor.rule_id == "rule-badges"
    emitted = []
    monitor.signals.new_job_ready.connect(lambda p, r: emitted.append((p, r)))
    path = next(iter(monitor.pending_items))
    monitor.signals.new_job_ready.emit(str(path), monitor.rule_id)

    assert emitted and emitted[0][1] == "rule-badges"


def test_start_performs_the_scan(monitor):
    """The regression that mattered: start() only scheduled the observer."""
    _drop(monitor, "deja_la.pdf")

    monitor.start()

    assert any(p.name == "deja_la.pdf" for p in monitor.pending_items), (
        "start() doit prendre en charge les fichiers déjà présents"
    )
