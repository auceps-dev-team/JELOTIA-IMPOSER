"""Guards against the M8 + M13 data-loss chain.

Field scenario, already survived once (QA 14.5): the disk fills up during a
run, the archive is written truncated without raising, the originals are
deleted anyway, and nothing reaches the operator. Three links, one lost job.

These tests pin each link:
  - an unreadable/incomplete archive must NEVER cost the originals;
  - a full volume must raise before a single sheet is written;
  - the error must carry a message an operator can act on.
"""

import zipfile

import pytest

from src.utils.disk import (
    InsufficientDiskSpaceError,
    ensure_free_space,
    free_space_mb,
)

# --------------------------------------------------------------------------- #
#  M8 — the archive is proven readable before anything is deleted             #
# --------------------------------------------------------------------------- #

@pytest.fixture
def manager(tmp_path, monkeypatch):
    """An OutputManager writing into tmp_path, with Qt's timer neutralised."""
    monkeypatch.setattr("PySide6.QtCore.QTimer.start", lambda *a, **k: None)
    from src.core.output_manager import OutputManager

    instance = OutputManager.__new__(OutputManager)
    instance.archive_dir = tmp_path / "Archive"
    instance.archive_dir.mkdir(parents=True, exist_ok=True)
    return instance


def _sources(tmp_path, count=3):
    paths = []
    for i in range(count):
        p = tmp_path / f"art_{i}.pdf"
        p.write_bytes(b"%PDF-1.4\n" + b"x" * 500)
        paths.append(p)
    return paths


def test_successful_archive_removes_the_originals(manager, tmp_path):
    sources = _sources(tmp_path)

    result = manager.archive_files("job_ok", [str(p) for p in sources])

    assert result is not None, "l'archivage doit réussir"
    assert all(not p.exists() for p in sources), "les originaux doivent être retirés"
    with zipfile.ZipFile(result) as zf:
        assert sorted(zf.namelist()) == sorted(p.name for p in sources)


def test_a_corrupt_archive_never_costs_the_originals(manager, tmp_path, monkeypatch):
    """The heart of M8: if verification fails, the sources stay on disk."""
    sources = _sources(tmp_path)
    monkeypatch.setattr(
        manager, "_verify_archive",
        lambda *a, **k: (_ for _ in ()).throw(OSError("archive corrompue"))
    )

    result = manager.archive_files("job_ko", [str(p) for p in sources])

    assert result is None, "un archivage non vérifié doit être signalé en échec"
    assert all(p.exists() for p in sources), (
        "AUCUN original ne doit être supprimé si l'archive n'est pas prouvée lisible"
    )


def test_verification_rejects_a_truncated_member(manager, tmp_path):
    """Simulates the disk-full signature: a member smaller than its source."""
    source = tmp_path / "big.pdf"
    source.write_bytes(b"y" * 10_000)
    zip_path = tmp_path / "truncated.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("big.pdf", b"y" * 40)  # written short

    with pytest.raises(OSError, match="tronqué"):
        manager._verify_archive(zip_path, {"big.pdf": source})


def test_verification_rejects_a_missing_member(manager, tmp_path):
    source = tmp_path / "absent.pdf"
    source.write_bytes(b"z" * 100)
    zip_path = tmp_path / "partial.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("other.pdf", b"z" * 100)

    with pytest.raises(OSError, match="incomplète"):
        manager._verify_archive(zip_path, {"absent.pdf": source})


# --------------------------------------------------------------------------- #
#  M13 — refuse to export on a full volume, and say so                        #
# --------------------------------------------------------------------------- #

def test_free_space_is_measured_on_a_real_volume(tmp_path):
    assert free_space_mb(tmp_path) > 0


def test_free_space_walks_up_to_an_existing_parent(tmp_path):
    """The output directory often does not exist yet."""
    assert free_space_mb(tmp_path / "pas" / "encore" / "cree") > 0


def test_plenty_of_room_passes_silently(tmp_path):
    ensure_free_space(tmp_path, required_mb=1)


def test_a_full_volume_raises_before_writing(tmp_path, monkeypatch):
    monkeypatch.setattr("src.utils.disk.free_space_mb", lambda _p: 12.0)

    with pytest.raises(InsufficientDiskSpaceError) as excinfo:
        ensure_free_space(tmp_path, required_mb=500)

    message = str(excinfo.value)
    assert "12" in message and "500" in message, "les chiffres doivent être cités"
    assert "aucune planche" in message.lower(), (
        "l'opérateur doit savoir que rien n'a été écrit"
    )


def test_an_unmeasurable_volume_does_not_block_the_export(tmp_path, monkeypatch):
    """A probing failure must not become its own outage."""
    def boom(_p):
        raise OSError("volume illisible")

    monkeypatch.setattr("src.utils.disk.free_space_mb", boom)
    ensure_free_space(tmp_path, required_mb=500)  # ne doit pas lever


def test_disk_error_reaches_the_operator_not_just_the_log():
    """M13 was 'logged silently'. The exception must survive finalize's broad
    `except Exception`, which is what swallowed it before."""
    import inspect

    from src.core.processors import job_processor

    source = inspect.getsource(job_processor.finalize_job_sheets)
    assert "ensure_free_space" in source, "l'espace doit être vérifié avant export"
    assert "except InsufficientDiskSpaceError" in source and "raise" in source, (
        "l'erreur disque doit être re-levée, pas absorbée par le except générique"
    )
