"""M6 — settings the interface writes must actually do something.

The screen let the operator set a worker count, a memory limit, an allowed
format list and a user role; it confirmed the save, and nothing changed. Two of
those are now wired to real consumers; the two that could not be honoured
honestly were removed from the interface rather than left as decoration.
"""

import pytest

from src.core.engines.preflight_engine import PreflightEngine
from src.core.models.domain import (
    ColorMode,
    FileFormat,
    FileItem,
    JobSettings,
    PreflightErrorType,
    PreflightStatus,
)


def _item(fmt=FileFormat.PDF):
    from uuid import uuid4

    return FileItem(
        job_id=uuid4(), path="a.pdf", format=fmt,
        width_mm=100.0, height_mm=100.0, dpi=300, color_mode=ColorMode.CMYK,
    )


# --- preflight.allowed_formats --------------------------------------------- #

def test_empty_list_accepts_everything():
    """Default behaviour must not change for shops that never set this."""
    settings = JobSettings(allowed_formats="")
    for fmt in (FileFormat.PDF, FileFormat.TIFF, FileFormat.JPEG, FileFormat.PNG):
        item = PreflightEngine().run_preflight(_item(fmt), settings)
        types = [e.type for e in item.preflight_errors]
        assert PreflightErrorType.FORMAT_NOT_ALLOWED not in types


def test_a_disallowed_format_is_blocked():
    settings = JobSettings(allowed_formats="PDF,TIFF")
    item = PreflightEngine().run_preflight(_item(FileFormat.JPEG), settings)

    errors = [e for e in item.preflight_errors
              if e.type == PreflightErrorType.FORMAT_NOT_ALLOWED]
    assert errors, "le format non autorisé doit être signalé"
    assert errors[0].is_blocking, "rien en aval ne peut rattraper un format refusé"
    assert item.preflight_status == PreflightStatus.ERROR
    assert "JPEG" in errors[0].message and "PDF" in errors[0].message


def test_an_allowed_format_passes():
    settings = JobSettings(allowed_formats="PDF,TIFF")
    item = PreflightEngine().run_preflight(_item(FileFormat.PDF), settings)
    types = [e.type for e in item.preflight_errors]
    assert PreflightErrorType.FORMAT_NOT_ALLOWED not in types


@pytest.mark.parametrize("value", ["pdf", " PDF ", "pdf , tiff", "PDF,,TIFF"])
def test_the_list_is_forgiving_about_spacing_and_case(value):
    """Operators type this by hand in a text field."""
    settings = JobSettings(allowed_formats=value)
    item = PreflightEngine().run_preflight(_item(FileFormat.PDF), settings)
    types = [e.type for e in item.preflight_errors]
    assert PreflightErrorType.FORMAT_NOT_ALLOWED not in types


# --- performance.workers ---------------------------------------------------- #

def test_worker_count_is_read_from_the_settings(monkeypatch):
    import os

    from src.ui.main_window import MainWindow

    monkeypatch.setattr(
        "src.utils.config_manager.ConfigManager.get",
        lambda self, section, key: 2 if (section, key) == ("performance", "workers") else None,
    )
    assert MainWindow._configured_workers() == min(2, os.cpu_count() or 1)


def test_worker_count_is_clamped_to_the_machine(monkeypatch):
    """A stray 64 on a 4-core shop PC would spawn 64 processes and thrash it."""
    import os

    from src.ui.main_window import MainWindow

    monkeypatch.setattr(
        "src.utils.config_manager.ConfigManager.get",
        lambda self, section, key: 64 if (section, key) == ("performance", "workers") else None,
    )
    assert MainWindow._configured_workers() == (os.cpu_count() or 1)


@pytest.mark.parametrize("stored", [None, 0, "", "abc"])
def test_an_unusable_value_falls_back_to_the_pool_default(monkeypatch, stored):
    from src.ui.main_window import MainWindow

    monkeypatch.setattr(
        "src.utils.config_manager.ConfigManager.get",
        lambda self, section, key: stored if (section, key) == ("performance", "workers") else None,
    )
    assert MainWindow._configured_workers() is None


# --- the two fields that were removed --------------------------------------- #

def test_removed_fields_are_gone_from_the_settings_screen():
    """`users.role` implied an access control the product does not have, and
    `memory_limit_mb` was never enforced anywhere. Both were removed rather than
    left on screen confirming a save that changed nothing."""
    import inspect

    from src.ui.widgets import settings_view

    source = inspect.getsource(settings_view)
    assert "memory_limit" not in source, "le champ limite mémoire doit être retiré"
    assert "user_role" not in source, "le champ rôle doit être retiré"
    assert 'config.set("users", "role"' not in source
