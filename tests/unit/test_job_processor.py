import uuid
from pathlib import Path

import fitz
import pytest

from src.core.models.domain import JobSettings
from src.core.processors.job_processor import process_job_files


@pytest.fixture
def two_page_pdf(tmp_path):
    """A 2-page PDF, to confirm a quantity override applies to every page."""
    path = tmp_path / "multi.pdf"
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    doc.new_page(width=200, height=200)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def simple_pdf(tmp_path):
    path = tmp_path / "single.pdf"
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    doc.save(str(path))
    doc.close()
    return path


def test_quantity_override_applies_to_matching_file(tmp_path, simple_pdf, monkeypatch):
    from src.utils import config as config_module
    monkeypatch.setattr(config_module.config, "processing_dir", tmp_path / "processing")

    job_id = uuid.uuid4()
    settings = JobSettings()

    items = process_job_files(
        job_id, [simple_pdf], settings, quantities={str(simple_pdf): 7}
    )

    assert len(items) == 1
    assert items[0].quantity == 7


def test_quantity_override_applies_to_every_page_of_a_pdf(tmp_path, two_page_pdf, monkeypatch):
    from src.utils import config as config_module
    monkeypatch.setattr(config_module.config, "processing_dir", tmp_path / "processing")

    job_id = uuid.uuid4()
    settings = JobSettings()

    items = process_job_files(
        job_id, [two_page_pdf], settings, quantities={str(two_page_pdf): 3}
    )

    assert len(items) == 2
    assert all(it.quantity == 3 for it in items)


def test_no_quantity_override_defaults_to_one(tmp_path, simple_pdf, monkeypatch):
    from src.utils import config as config_module
    monkeypatch.setattr(config_module.config, "processing_dir", tmp_path / "processing")

    job_id = uuid.uuid4()
    settings = JobSettings()

    items = process_job_files(job_id, [simple_pdf], settings, quantities=None)

    assert len(items) == 1
    assert items[0].quantity == 1


def test_quantity_key_normalization_bridges_dialog_and_processor(tmp_path, simple_pdf, monkeypatch):
    """Regression: JobDialog keys the quantities map by the raw path string Qt
    returns (forward slashes), while process_job_files looks it up by
    str(Path(file_path)) — OS-native separators (backslashes on Windows). On
    Windows the two never matched, so every file silently stayed at quantity 1.
    MainWindow._submit_job bridges them by normalizing keys to str(Path(...));
    this locks that a forward-slash key, once normalized, is honored."""
    from src.utils import config as config_module
    monkeypatch.setattr(config_module.config, "processing_dir", tmp_path / "processing")

    posix_key = simple_pdf.as_posix()  # forward slashes, as the dialog produces
    normalized = {str(Path(k)): v for k, v in {posix_key: 6}.items()}

    items = process_job_files(uuid.uuid4(), [simple_pdf], JobSettings(), quantities=normalized)

    assert len(items) == 1
    assert items[0].quantity == 6


def test_quantity_map_only_affects_matching_path(tmp_path, simple_pdf, monkeypatch):
    """A quantities dict that doesn't mention this file must not change its
    default quantity of 1 (e.g. only one of several files in a job was
    multiplied)."""
    from src.utils import config as config_module
    monkeypatch.setattr(config_module.config, "processing_dir", tmp_path / "processing")

    job_id = uuid.uuid4()
    settings = JobSettings()

    items = process_job_files(
        job_id, [simple_pdf], settings, quantities={"C:/some/other/file.pdf": 9}
    )

    assert len(items) == 1
    assert items[0].quantity == 1
