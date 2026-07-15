import uuid

import fitz
import pytest

from src.core.ganging import (
    GangGroup,
    GangMember,
    find_gang_groups,
    gang_signature,
)
from src.core.models.domain import JobSettings


def _settings(**kwargs):
    base = {"sheet_width_mm": 550.0, "sheet_height_mm": 890.0, "gap_mm": 3.0}
    base.update(kwargs)
    return JobSettings(**base)


# --------------------------------------------------------------------------- #
#  Compatibility signature                                                     #
# --------------------------------------------------------------------------- #

def test_same_physical_settings_share_a_signature():
    a = _settings(min_dpi=300, generate_thumbnail=True)
    b = _settings(min_dpi=1200, generate_thumbnail=False, force_cmyk=False)
    # min_dpi/thumbnail/force_cmyk n'affectent pas la planche : gang possible.
    assert gang_signature(a) == gang_signature(b)


@pytest.mark.parametrize(
    "override",
    [
        {"sheet_width_mm": 700.0},
        {"gap_mm": 5.0},
        {"margin_mm": 10.0},
        {"allow_rotation": False},
        {"export_format": "TIFF"},
        {"export_dpi": 600},
        {"plotter_marks": "graphtec2"},
        {"cut_contour_spot": True},
        {"add_bleed_mm": 3.0},
    ],
)
def test_physical_differences_break_compatibility(override):
    assert gang_signature(_settings()) != gang_signature(_settings(**override))


# --------------------------------------------------------------------------- #
#  Grouping                                                                    #
# --------------------------------------------------------------------------- #

def test_groups_only_compatible_jobs():
    candidates = [
        ("Badges A", _settings(), ["a.pdf"], {"a.pdf": 50}),
        ("Badges B", _settings(), ["b.pdf"], {"b.pdf": 30}),
        ("Vinyle", _settings(sheet_width_mm=1000.0), ["c.pdf"], {}),
        ("Cartes", _settings(cut_contour_spot=True), ["d.pdf"], {}),
    ]
    groups = find_gang_groups(candidates)

    assert len(groups) == 1, "seuls les deux jobs compatibles forment un groupe"
    assert {m.name for m in groups[0].members} == {"Badges A", "Badges B"}
    assert groups[0].total_copies == 80


def test_lone_job_is_not_a_gang():
    assert find_gang_groups([("Seul", _settings(), ["a.pdf"], {})]) == []


def test_jobs_without_files_are_ignored():
    candidates = [
        ("Vide", _settings(), [], {}),
        ("A", _settings(), ["a.pdf"], {}),
        ("B", _settings(), ["b.pdf"], {}),
    ]
    groups = find_gang_groups(candidates)
    assert len(groups) == 1
    assert {m.name for m in groups[0].members} == {"A", "B"}


def test_groups_sorted_by_potential():
    candidates = [
        ("A", _settings(), ["a.pdf"], {}),
        ("B", _settings(), ["b.pdf"], {}),
        ("C", _settings(gap_mm=8.0), ["c.pdf"], {}),
        ("D", _settings(gap_mm=8.0), ["d.pdf"], {}),
        ("E", _settings(gap_mm=8.0), ["e.pdf"], {}),
    ]
    groups = find_gang_groups(candidates)
    assert [len(g.members) for g in groups] == [3, 2], "le plus gros groupe d'abord"


# --------------------------------------------------------------------------- #
#  Merging                                                                     #
# --------------------------------------------------------------------------- #

def test_merged_quantities_sum_shared_files():
    """Deux commandes du même fichier doivent additionner leurs exemplaires —
    en garder une seule sous-produirait silencieusement."""
    group = GangGroup(
        settings=_settings(),
        members=[
            GangMember("Cmd1", ["logo.pdf", "a.pdf"], {"logo.pdf": 20, "a.pdf": 5}),
            GangMember("Cmd2", ["logo.pdf"], {"logo.pdf": 30}),
        ],
    )
    assert group.merged_paths() == ["logo.pdf", "a.pdf"], "pas de doublon de chemin"
    assert group.merged_quantities() == {"logo.pdf": 50, "a.pdf": 5}
    assert group.total_copies == 55


def test_files_without_quantity_count_as_one():
    group = GangGroup(
        settings=_settings(),
        members=[GangMember("Cmd", ["a.pdf", "b.pdf"], {"a.pdf": 3})],
    )
    assert group.merged_quantities() == {"a.pdf": 3, "b.pdf": 1}
    assert group.total_copies == 4


# --------------------------------------------------------------------------- #
#  End-to-end: ganging really fills sheets better                              #
# --------------------------------------------------------------------------- #

def test_ganging_uses_fewer_sheets_than_separate_jobs(tmp_path, monkeypatch):
    """La preuve du bénéfice : 3 commandes imposées séparément consomment plus
    de planches que les mêmes commandes amalgamées."""
    from src.core.processors.job_processor import finalize_job_sheets, process_job_files
    from src.utils import config as config_module

    monkeypatch.setattr(config_module.config, "processing_dir", tmp_path / "proc")
    monkeypatch.setattr(config_module.config, "output_dir", tmp_path / "out")

    badge = tmp_path / "badge.pdf"
    doc = fitz.open()
    doc.new_page(width=(53 / 25.4) * 72, height=(84 / 25.4) * 72)
    doc.save(str(badge))
    doc.close()

    settings = _settings(allow_rotation=True)
    orders = [("Cmd1", 20), ("Cmd2", 20), ("Cmd3", 20)]

    # 1. Chaque commande imposée seule.
    separate_sheets = 0
    separate_fills = []
    for name, qty in orders:
        job_id = uuid.uuid4()
        items = process_job_files(job_id, [badge], settings, quantities={str(badge): qty})
        sheets = finalize_job_sheets(job_id, items, settings, job_name=name)
        separate_sheets += len(sheets)
        separate_fills += [s.fill_rate for s in sheets]

    # 2. Les trois commandes amalgamées (une seule imposition).
    group = GangGroup(
        settings=settings,
        members=[GangMember(name, [str(badge)], {str(badge): qty}) for name, qty in orders],
    )
    assert group.merged_quantities() == {str(badge): 60}

    gang_id = uuid.uuid4()
    gang_items = process_job_files(
        gang_id, [badge], settings, quantities=group.merged_quantities()
    )
    gang_sheets = finalize_job_sheets(gang_id, gang_items, settings, job_name="AMALGAME")

    assert sum(len(s.items) for s in gang_sheets) == 60, "les 60 exemplaires sont posés"
    assert len(gang_sheets) < separate_sheets, (
        f"l'amalgame doit économiser des planches : {len(gang_sheets)} vs "
        f"{separate_sheets} séparément"
    )
    # 60 badges de 53×84 ne peuvent occuper que ~55 % d'une planche 550×890
    # (capacité ~90) : le gain se mesure en planches épargnées et en
    # remplissage par planche, pas en valeur absolue de remplissage.
    gang_fill = max(s.fill_rate for s in gang_sheets)
    assert gang_fill > 2 * max(separate_fills), (
        f"chaque planche amalgamée doit être bien mieux remplie : "
        f"{gang_fill:.1f}% contre {max(separate_fills):.1f}% en séparé"
    )
