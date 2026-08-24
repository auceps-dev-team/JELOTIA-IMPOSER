import time

import pytest
from PySide6.QtCore import QCoreApplication

from src.core.auto_processor import AutoProcessor
from src.core.hot_folder_monitor import HotFolderMonitor
from src.utils.config import config


@pytest.fixture
def temp_dirs(tmp_path):
    # Setup temp dirs
    input_dir = tmp_path / "input"
    processing_dir = tmp_path / "processing"
    output_dir = tmp_path / "output"

    input_dir.mkdir()
    processing_dir.mkdir()
    output_dir.mkdir()

    # Override config
    original_input = config.input_dir
    original_processing = config.processing_dir
    original_output = config.output_dir

    config.input_dir = input_dir
    config.processing_dir = processing_dir
    config.output_dir = output_dir

    yield input_dir, processing_dir, output_dir

    # Restore config
    config.input_dir = original_input
    config.processing_dir = original_processing
    config.output_dir = original_output


def test_hot_folder_monitor(temp_dirs):
    # We need a QCoreApplication instance for QThread/Signals
    app = QCoreApplication.instance()
    if not app:
        app = QCoreApplication([])

    input_dir, processing_dir, output_dir = temp_dirs

    files_detected = []

    def on_file_added(path):
        files_detected.append(path)

    monitor = HotFolderMonitor(str(input_dir), str(processing_dir))
    monitor.signals.new_job_ready.connect(on_file_added)
    monitor.start()

    # Create files
    time.sleep(1) # wait for watchdog to start
    test_file_1 = input_dir / "test1.pdf"
    test_file_1.touch()
    
    test_file_2 = input_dir / "test2.jpg"
    test_file_2.touch()

    # Wait for events (needs stabilization, 2 seconds + polling)
    for _ in range(60):
        app.processEvents()
        time.sleep(0.1)
        if len(files_detected) >= 2:
            break
            
    monitor.stop()

    # Verify
    assert len(files_detected) == 2
    assert any("test1.pdf" in str(p) for p in files_detected)
    assert any("test2.jpg" in str(p) for p in files_detected)


def test_auto_processor(temp_dirs):
    app = QCoreApplication.instance()
    if not app:
        app = QCoreApplication([])

    input_dir, processing_dir, output_dir = temp_dirs
    
    # Configure AutoProcessor via ConfigManager mock/setup
    processor = AutoProcessor()
    # Force schedule check to pass
    processor.config.set("automation", "enable_scheduling", False)
    processor.config.set("automation", "group_delay_minutes", 0)
    processor.config.set("automation", "max_files_per_job", 2)
    
    groups_emitted = []
    
    def on_job_grouped(group_name, file_paths):
        groups_emitted.append((group_name, file_paths))
        
    processor.job_grouped.connect(on_job_grouped)
    processor.start()
    
    # Add fake files and touch them to exist
    f1 = input_dir / "A1.pdf"
    f1.touch()
    f2 = input_dir / "A2.pdf"
    f2.touch()
    f3 = input_dir / "A3.pdf"
    f3.touch()

    processor.add_file(str(f1))
    processor.add_file(str(f2))
    processor.add_file(str(f3))
    
    # AutoProcessor.run() polls every 5 s (see its loop), so a 6 s budget left
    # barely one second of margin and the test failed roughly one run in five
    # under load — enough to make CI red at random. Allow 5x the poll interval;
    # the loop still exits as soon as the group arrives, so the passing case
    # stays as fast as before.
    deadline = time.monotonic() + 25.0
    while time.monotonic() < deadline and not groups_emitted:
        app.processEvents()
        time.sleep(0.1)

    processor.stop()

    assert len(groups_emitted) > 0, (
        "aucun groupe émis en 25 s — AutoProcessor sonde toutes les 5 s"
    )
    # The 3 files should be grouped into 2 batches due to max_files_per_job=2
    # But since their sizes are (0,0) they are grouped together
    total_files_in_groups = sum(len(fps) for _, fps in groups_emitted)
    assert total_files_in_groups == 3
