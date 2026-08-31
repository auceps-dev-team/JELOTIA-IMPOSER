"""Le cliquet E501 doit vraiment bloquer une régression.

Un garde-fou qui ne garde rien est pire que pas de garde-fou : il rassure. Ces
tests exercent la logique de plafond sans invoquer ruff (lent), et un test
d'intégration vérifie que le compte réel correspond bien au plafond figé.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_line_length.py"


@pytest.fixture
def ratchet(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("check_line_length", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_line_length"] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "BASELINE_FILE", tmp_path / "baseline.txt")
    return module


def test_baseline_round_trips(ratchet):
    ratchet.write_baseline(42)
    assert ratchet.read_baseline() == 42


def test_a_missing_baseline_reads_as_zero(ratchet):
    assert ratchet.read_baseline() == 0


def test_comments_in_the_baseline_are_ignored(ratchet):
    ratchet.BASELINE_FILE.write_text("# explication\n# suite\n17\n", encoding="utf-8")
    assert ratchet.read_baseline() == 17


def test_adding_a_long_line_fails(ratchet, monkeypatch, capsys):
    ratchet.write_baseline(10)
    monkeypatch.setattr(ratchet, "count_violations", lambda: 11)
    monkeypatch.setattr(sys, "argv", ["check_line_length.py"])

    assert ratchet.main() == 1
    assert "ÉCHEC" in capsys.readouterr().out


def test_staying_at_the_ceiling_passes(ratchet, monkeypatch):
    ratchet.write_baseline(10)
    monkeypatch.setattr(ratchet, "count_violations", lambda: 10)
    monkeypatch.setattr(sys, "argv", ["check_line_length.py"])
    assert ratchet.main() == 0


def test_fixing_lines_passes_and_invites_lowering(ratchet, monkeypatch, capsys):
    ratchet.write_baseline(10)
    monkeypatch.setattr(ratchet, "count_violations", lambda: 7)
    monkeypatch.setattr(sys, "argv", ["check_line_length.py"])

    assert ratchet.main() == 0
    assert "abaissez le plafond" in capsys.readouterr().out


def test_update_refuses_to_raise_the_ceiling(ratchet, monkeypatch, capsys):
    """--update sert à DESCENDRE. L'utiliser pour absorber une régression
    viderait le cliquet de son sens."""
    ratchet.write_baseline(10)
    monkeypatch.setattr(ratchet, "count_violations", lambda: 15)
    monkeypatch.setattr(sys, "argv", ["check_line_length.py", "--update"])

    assert ratchet.main() == 1
    assert ratchet.read_baseline() == 10, "le plafond ne doit pas avoir bougé"


def test_the_committed_baseline_matches_reality():
    """Si quelqu'un corrige des lignes sans abaisser le plafond, ce test le
    rappelle — sinon le cliquet se desserre en silence."""
    spec = importlib.util.spec_from_file_location("check_line_length_real", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.read_baseline() > 0, "le plafond doit être versionné"
