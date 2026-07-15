"""Multi-job ganging: combine several compatible orders onto the same sheets.

Nesting one job at a time is what wastes media: a 20-pose order alone leaves
most of a 550×890 sheet empty. Feeding several orders to a SINGLE nesting pass
fills that same sheet — the exact effect already proven for chunks of one job
(see tests/unit/test_finalize_job_sheets.py). Ganging generalizes it across
orders.

Two jobs may only share a sheet if their PHYSICAL production parameters match
(same media size, same gaps/margins, same cut marks, same export target).
`gang_signature` captures exactly those; anything else (name, priority,
quantities…) is free to differ.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.core.models.domain import JobSettings

logger = logging.getLogger(__name__)


def gang_signature(settings: JobSettings) -> tuple:
    """The production parameters two jobs MUST share to be printed together.

    Deliberately excludes anything that doesn't affect the physical sheet
    (min_dpi, force_cmyk, thumbnails…): being stricter than necessary would
    reject gangs that are perfectly printable.
    """
    return (
        round(settings.sheet_width_mm, 3),
        round(settings.sheet_height_mm, 3),
        round(settings.gap_mm, 3),
        round(settings.margin_mm, 3),
        settings.allow_rotation,
        round(settings.add_bleed_mm, 3),
        settings.export_format,
        settings.export_dpi,
        settings.plotter_marks,
        round(settings.plotter_mark_length_mm, 3),
        settings.cut_contour_spot,
        settings.draw_cutlines,
        settings.add_crop_marks,
    )


def describe_signature(settings: JobSettings) -> str:
    """Human-readable summary of what makes this group compatible."""
    parts = [
        f"{settings.sheet_width_mm:.0f}×{settings.sheet_height_mm:.0f} mm",
        f"espacement {settings.gap_mm:.0f} mm",
        settings.export_format,
    ]
    if settings.plotter_marks != "none":
        parts.append("repères ARMS")
    if settings.cut_contour_spot:
        parts.append("CutContour")
    return " · ".join(parts)


@dataclass
class GangMember:
    """One order eligible for a gang."""
    name: str
    source_paths: List[str] = field(default_factory=list)
    quantities: Dict[str, int] = field(default_factory=dict)

    @property
    def total_copies(self) -> int:
        """Copies actually printed: files without an explicit quantity count 1."""
        return sum(max(1, int(self.quantities.get(p, 1))) for p in self.source_paths)


@dataclass
class GangGroup:
    """A set of mutually compatible orders that can share sheets."""
    settings: JobSettings
    members: List[GangMember] = field(default_factory=list)

    @property
    def description(self) -> str:
        return describe_signature(self.settings)

    @property
    def total_files(self) -> int:
        return sum(len(m.source_paths) for m in self.members)

    @property
    def total_copies(self) -> int:
        return sum(m.total_copies for m in self.members)

    def merged_paths(self) -> List[str]:
        """Union of every member's files, first occurrence order kept."""
        seen: set = set()
        merged: List[str] = []
        for member in self.members:
            for path in member.source_paths:
                if path not in seen:
                    seen.add(path)
                    merged.append(path)
        return merged

    def merged_quantities(self) -> Dict[str, int]:
        """Copies per file across the whole gang. A file ordered by two
        different jobs must be printed the SUM of both orders — dropping one
        would silently under-produce."""
        merged: Dict[str, int] = {}
        for member in self.members:
            for path in member.source_paths:
                merged[path] = merged.get(path, 0) + max(
                    1, int(member.quantities.get(path, 1))
                )
        return merged


def find_gang_groups(
    candidates: List[tuple], min_members: int = 2
) -> List[GangGroup]:
    """Groups eligible orders by production signature.

    `candidates`: (name, settings, source_paths, quantities) tuples — typically
    the PENDING jobs. Only groups reaching `min_members` are returned (a lone
    job has nothing to gang with), sorted by potential (most orders first).
    """
    groups: Dict[tuple, GangGroup] = {}
    for name, settings, source_paths, quantities in candidates:
        if not source_paths:
            continue  # nothing to print
        key = gang_signature(settings)
        group = groups.get(key)
        if group is None:
            group = GangGroup(settings=settings)
            groups[key] = group
        group.members.append(
            GangMember(
                name=name,
                source_paths=list(source_paths),
                quantities=dict(quantities or {}),
            )
        )

    result = [g for g in groups.values() if len(g.members) >= min_members]
    result.sort(key=lambda g: (len(g.members), g.total_copies), reverse=True)
    return result


def gang_job_name(group: GangGroup, when: Optional[str] = None) -> str:
    """A name that says what the gang contains, for the Jobs view."""
    import datetime

    stamp = when or datetime.datetime.now().strftime("%H%M%S")
    return f"AMALGAME-{len(group.members)}JOBS-{stamp}"
