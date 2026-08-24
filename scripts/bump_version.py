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
- src/_version.py: the version the running app reports in Info Système;
- README.md: the version badge;
- uv.lock: NEVER edited by hand — `uv lock` regenerates it correctly.

`src/_version.py` and the README were added after an audit found four versions
in circulation at once. The script only wrote pyproject and the installer, so
the app displayed one version while the installer registered another and
support could not identify a build — aligning the files by hand never held for
more than one increment, because the drift was in the tooling.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
INSTALLER = ROOT / "installer" / "jelotia_imposer.iss"
VERSION_MODULE = ROOT / "src" / "_version.py"
README = ROOT / "README.md"

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


def write_version_module(new_version: str) -> bool:
    """`src/_version.py` — the version the RUNNING app displays (Info Système).

    This file claims in its own header to be "Updated by scripts/bump_version.py"
    while the script never wrote it, so the app kept reporting an older version
    than the installer registered — support could not identify a build. It is
    rewritten wholesale: it holds nothing else.
    """
    VERSION_MODULE.parent.mkdir(parents=True, exist_ok=True)
    VERSION_MODULE.write_text(
        "# Auto-generated — do not edit manually.\n"
        "# Updated by scripts/bump_version.py and the build pipeline.\n"
        f'__version__ = "{new_version}"\n',
        encoding="utf-8",
    )
    return True


def write_readme(new_version: str) -> bool:
    """The README badge, so the published page stops advertising a stale build."""
    if not README.exists():
        return False
    text = README.read_text(encoding="utf-8")
    new_text, badge = re.subn(r"(badge/version-)\d+\.\d+\.\d+", rf"\g<1>{new_version}", text)
    new_text, alt = re.subn(r'(alt="Version )\d+\.\d+\.\d+', rf"\g<1>{new_version}", new_text)
    if badge or alt:
        README.write_text(new_text, encoding="utf-8")
    return bool(badge or alt)


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


def declared_versions() -> dict:
    """Every place a version is published, for the coherence check."""
    found = {"pyproject.toml": read_current_version()}

    if VERSION_MODULE.exists():
        match = re.search(r'__version__\s*=\s*"([^"]+)"', VERSION_MODULE.read_text("utf-8"))
        found["src/_version.py"] = match.group(1) if match else "?"
    if INSTALLER.exists():
        match = re.search(r'#define\s+AppVersion\s+"([^"]+)"', INSTALLER.read_text("utf-8"))
        found["installer"] = match.group(1) if match else "?"
    if README.exists():
        match = re.search(r"badge/version-(\d+\.\d+\.\d+)", README.read_text("utf-8"))
        if match:
            found["README.md"] = match.group(1)
    return found


def check_versions() -> int:
    """CI gate: every published version must agree. Exits non-zero otherwise."""
    found = declared_versions()
    for source, version in found.items():
        print(f"  {source:<18} {version}")
    unique = set(found.values())
    if len(unique) == 1:
        print(f"\nCohérent : {unique.pop()}")
        return 0
    print(f"\nINCOHÉRENT — {len(unique)} versions en circulation : {sorted(unique)}")
    print("Lancez `python scripts/bump_version.py <X.Y.Z>` pour réaligner.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bump de version (pyproject + installeur + _version.py + README + uv.lock)"
    )
    parser.add_argument("version", nargs="?", help="version explicite, ex: 1.29.0")
    parser.add_argument("--check", action="store_true",
                        help="vérifie que toutes les sources déclarent la même version")
    group = parser.add_mutually_exclusive_group()
    for part in ("major", "minor", "patch"):
        group.add_argument(f"--{part}", action="store_true", help=f"incrémente {part}")
    args = parser.parse_args()

    if args.check:
        return check_versions()

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
    if write_version_module(new_version):
        print(f"  src/_version.py: {new_version}  (version affichée par l'app)")
    if write_readme(new_version):
        print(f"  README.md      : {new_version}")
    if sync_lockfile():
        print("  uv.lock        : régénéré par uv lock")
    print(f"\nVersion {new_version} appliquée. Pensez à `[bump {new_version}]` dans le commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
