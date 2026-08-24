"""Disk-space guard for the export stage.

Field incident (QA 14.5): the disk filled up mid-run, sheets 4 to 20 were never
exported, the failure was written to the log and **nothing reached the
operator** — who kept working believing the job had completed.

Failing loudly *before* writing is the point. A partial export that nobody is
told about is worse than a refused one: the operator sends an incomplete job to
the press.
"""

import shutil
from pathlib import Path

from loguru import logger

# A sheet at 300 dpi CMYK routinely weighs tens of MB, and the pipeline also
# writes intermediates. Refuse to start an export below this headroom.
MIN_FREE_MB = 500


class InsufficientDiskSpaceError(OSError):
    """Not enough room to export safely. Carries a message meant to be shown
    to the operator as-is, not just logged."""


def free_space_mb(path) -> float:
    """Free megabytes on the volume holding `path`.

    Walks up to the first existing parent: the target directory is often about
    to be created, and `disk_usage` needs a path that exists.
    """
    candidate = Path(path).resolve()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return shutil.disk_usage(str(candidate)).free / (1024 * 1024)


def ensure_free_space(path, required_mb: float = MIN_FREE_MB) -> None:
    """Raises InsufficientDiskSpaceError when `path`'s volume is too full.

    A volume we cannot measure is not treated as full — refusing to export
    because of a probing failure would be its own outage; the attempt is logged
    and allowed to proceed.
    """
    try:
        available = free_space_mb(path)
    except OSError as e:
        logger.warning(f"Espace disque non mesurable pour {path} : {e}")
        return

    if available < required_mb:
        raise InsufficientDiskSpaceError(
            f"Espace disque insuffisant sur le volume de {path} : "
            f"{available:.0f} Mo disponibles, {required_mb:.0f} Mo requis. "
            "Libérez de l'espace avant de relancer l'export — "
            "aucune planche n'a été écrite."
        )
