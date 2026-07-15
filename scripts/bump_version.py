"""Bump the application version safely, everywhere it must match.

    uv run python scripts/bump_version.py 1.29.0
    uv run python scripts/bump_version.py --patch|--minor|--major

Why this script exists: version bumps used to be done with
`sed 's/^version = "X"/version = "Y"/' pyproject.toml uv.lock`, which rewrites
EVERY line matching that version in uv.lock — including dependencies. It
silently corrupted the lockfile the day the project reached 1.28.0, the exact
version of the `pymupdf` package (declared 1.28.1, wheels still 1.28.0 →
`uv run` refused to start). The project shares its 1.x range with pymupdf, so
that collision will happen again.

Rules enforced here:
- pyproject.toml: only the `version` of the [project] table is touched;
- installer/jelotia_imposer.iss: the AppVersion define is kept in sync;
- uv.lock: NEVER edited by hand — `uv lock` regenerates it correctly.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
INSTALLER = ROOT / "installer" / "jelotia_imposer.iss"

# The Windows console defaults to cp1252, which can't encode every character
# of the French output — never let a print() crash mid-bump and leave the
# files half-updated.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):  # pragma: no cover - exotic consoles
        pass

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def read_current_version() -> str:
    """The version of the [project] table (not a dependency's)."""
    table = None
    for line in PYPROJECT.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            table = stripped
        elif table == "[project]" and stripped.startswith("version"):
            return stripped.split('"')[1]
    raise SystemExit("Version introuvable dans [project] de pyproject.toml")


def bumped(version: str, part: str) -> str:
    match = _VERSION_RE.match(version)
    if not match:
        raise SystemExit(f"Version courante illisible : {version}")
    major, minor, patch = (int(g) for g in match.groups())
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def write_pyproject(new_version: str) -> None:
    lines = PYPROJECT.read_text(encoding="utf-8").splitlines(keepends=True)
    table = None
    done = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            table = stripped
        elif table == "[project]" and stripped.startswith("version") and not done:
            lines[index] = re.sub(r'"[^"]+"', f'"{new_version}"', line, count=1)
            done = True
    if not done:
        raise SystemExit("Ligne version de [project] non trouvée")
    PYPROJECT.write_text("".join(lines), encoding="utf-8")


def write_installer(new_version: str) -> bool:
    if not INSTALLER.exists():
        return False
    text = INSTALLER.read_text(encoding="utf-8")
    new_text, count = re.subn(
        r'(#define\s+AppVersion\s+")[^"]+(")', rf"\g<1>{new_version}\g<2>", text, count=1
    )
    if count:
        INSTALLER.write_text(new_text, encoding="utf-8")
    return bool(count)


def sync_lockfile() -> bool:
    """uv.lock is regenerated, never hand-edited (see module docstring)."""
    try:
        result = subprocess.run(
            ["uv", "lock"], cwd=ROOT, capture_output=True, text=True, timeout=180
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"  ! uv lock impossible ({e}) — lancez `uv lock` manuellement")
        return False
    if result.returncode != 0:
        print(f"  ! uv lock a échoué :\n{result.stderr.strip()}")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bump de version (pyproject + installeur + uv.lock)"
    )
    parser.add_argument("version", nargs="?", help="version explicite, ex: 1.29.0")
    group = parser.add_mutually_exclusive_group()
    for part in ("major", "minor", "patch"):
        group.add_argument(f"--{part}", action="store_true", help=f"incrémente {part}")
    args = parser.parse_args()

    current = read_current_version()
    if args.version:
        if not _VERSION_RE.match(args.version):
            raise SystemExit("Format attendu : X.Y.Z")
        new_version = args.version
    elif args.major or args.minor or args.patch:
        part = "major" if args.major else "minor" if args.minor else "patch"
        new_version = bumped(current, part)
    else:
        print(f"Version actuelle : {current}")
        return 0

    # No early exit when new_version == current: the three files can be out of
    # sync (a half-applied bump), and re-running must repair them. Every write
    # below is idempotent.
    write_pyproject(new_version)
    print(f"  pyproject.toml : {current} -> {new_version}")
    if write_installer(new_version):
        print(f"  installeur     : {new_version}")
    if sync_lockfile():
        print("  uv.lock        : régénéré par uv lock")
    print(f"\nVersion {new_version} appliquée. Pensez à `[bump {new_version}]` dans le commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
