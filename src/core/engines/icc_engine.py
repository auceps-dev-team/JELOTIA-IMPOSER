"""Real ICC colour management.

`img.convert("CMYK")` in Pillow is a naive formula (C = 255 - R …), not a
colorimetric conversion, and it is actively harmful for print: it lays down
roughly equal amounts of all four inks whatever the press, ~300 % on a pure
black. This module routes conversions through littleCMS (Pillow's ImageCms)
with real profiles instead.

What the profile then produces is the PRESS CONDITION's business, not ours —
measured on a pure black:

    naive                 C255 M255 J255 N0   -> 300 % ink, meaningless
    SWOP                  C0   M0   J0   N255 -> 100 %, clean 100K
    ISO Coated v2/FOGRA39 C216 M198 J185 N242 -> 330 %, rich black (in spec)

Both profiled results are correct for their condition. Do not assume a
conversion "should" come out at 100K — an earlier version of this note did, and
tests written against it broke the moment a coated-offset profile was used.

CAUTION, currently unenforced: FOGRA39's 330 % suits sheet-fed offset on coated
stock, NOT the digital and large-format work this shop does, where that much ink
floods the media and never dries. `total_ink_coverage()` below measures TAC but
nothing in the pipeline calls it — no ink limit is applied anywhere.

PDFs are out of scope here: converting their content colorimetrically needs a
full RIP (Ghostscript). The export engine already tags them with an
OutputIntent, which is what PDF/X asks for.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Rendering intents (littleCMS numbering).
INTENT_PERCEPTUAL = 0
INTENT_RELATIVE_COLORIMETRIC = 1
INTENT_SATURATION = 2
INTENT_ABSOLUTE_COLORIMETRIC = 3

_SUFFIXES = (".icc", ".icm")
# Windows ships real profiles (RSWOP.icm…); the app folder lets a shop drop in
# the profile its printer actually uses (FOGRA39, its own linearisation…).
_SYSTEM_DIRS = (Path("C:/Windows/System32/spool/drivers/color"),)


class ICCError(Exception):
    """Raised when a colour conversion cannot be performed."""


@dataclass
class ProfileInfo:
    path: Path
    name: str
    color_space: str

    @property
    def is_cmyk(self) -> bool:
        return self.color_space.strip().upper().startswith("CMYK")


def profiles_dir() -> Path:
    """Where the shop can drop its own profiles."""
    from src.utils.config import config

    path = Path(config.base_dir) / "Profiles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_profile(path: Path) -> Optional[ProfileInfo]:
    """Description and colour space of an ICC file, or None if unreadable."""
    from PIL import ImageCms

    path = Path(path)
    try:
        profile = ImageCms.getOpenProfile(str(path))
        name = (ImageCms.getProfileDescription(profile) or path.stem).strip()
        space = str(profile.profile.xcolor_space or "").strip()
    except Exception as e:
        logger.debug(f"Profil ICC illisible ({path.name}) : {e}")
        return None
    return ProfileInfo(path=path, name=name, color_space=space)


def discover_profiles(cmyk_only: bool = True) -> List[ProfileInfo]:
    """Every usable profile: the shop's own folder first, then the system's."""
    found: List[ProfileInfo] = []
    seen: set = set()
    try:
        search_dirs = [profiles_dir(), *_SYSTEM_DIRS]
    except Exception:
        search_dirs = list(_SYSTEM_DIRS)

    for directory in search_dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.suffix.lower() not in _SUFFIXES or path.name.lower() in seen:
                continue
            info = read_profile(path)
            if info is None or (cmyk_only and not info.is_cmyk):
                continue
            seen.add(path.name.lower())
            found.append(info)
    return found


def convert_image_to_cmyk(image, dest_profile: Path, intent: int = INTENT_PERCEPTUAL):
    """Colorimetric RGB/grey -> CMYK conversion through `dest_profile`.

    The source is the image's EMBEDDED profile when it has one (honouring what
    the designer actually worked in); otherwise sRGB is assumed, which is the
    safe default for untagged artwork.
    """
    from PIL import Image, ImageCms

    dest_profile = Path(dest_profile)
    if not dest_profile.is_file():
        raise ICCError(f"Profil ICC introuvable : {dest_profile}")

    if image.mode == "CMYK":
        return image
    # Everything goes through RGB first: the source profile used for untagged
    # artwork is sRGB, and littleCMS refuses to build an "L" -> CMYK transform
    # from an RGB profile ("cannot build transform").
    if image.mode != "RGB":
        image = image.convert("RGB")

    try:
        embedded = image.info.get("icc_profile")
        if embedded:
            import io

            source = ImageCms.getOpenProfile(io.BytesIO(embedded))
        else:
            source = ImageCms.createProfile("sRGB")
        target = ImageCms.getOpenProfile(str(dest_profile))
        transform = ImageCms.buildTransform(
            source, target, image.mode, "CMYK", renderingIntent=intent
        )
        converted = ImageCms.applyTransform(image, transform)
    except ICCError:
        raise
    except Exception as e:
        raise ICCError(f"Conversion ICC impossible ({dest_profile.name}) : {e}") from e

    if converted is None:  # pragma: no cover - defensive
        raise ICCError("La conversion ICC n'a produit aucune image.")
    # Carry the destination profile so downstream tools know what this is.
    converted.info["icc_profile"] = Path(dest_profile).read_bytes()
    assert isinstance(converted, Image.Image)
    return converted


def total_ink_coverage(image) -> float:
    """Highest total ink coverage in the image, in % (C+M+Y+K).

    Per-channel histograms cannot answer this: the four inks must be summed on
    the SAME pixel, so the worst pixel has to be found across the whole image.

    Vectorised through numpy because the obvious Python loop costs ~0.65 s per
    megapixel — some 45 s on an A1 sheet at 300 dpi. That is almost certainly
    why this function sat unused: too slow to call anywhere real. The pure
    Python path is kept as a fallback and gives identical results.
    """
    if image.mode != "CMYK":
        return 0.0

    try:
        import numpy as np

        # uint16: four channels sum up to 1020 and would wrap around in uint8.
        channels = np.asarray(image, dtype=np.uint16)
        if channels.ndim != 3 or channels.shape[2] < 4:
            raise ValueError("image CMJN attendue")
        worst = int(channels.sum(axis=2).max())
    except Exception:
        worst = 0
        for pixel in image.get_flattened_data():
            total = sum(pixel)
            if total > worst:
                worst = total

    return worst / 255.0 * 100.0


# Above this, ink stops drying on the media and the job is refused or smears.
# 300 % is the figure the trade quotes for coated offset; digital and
# large-format want appreciably less, which is why it is configurable.
DEFAULT_MAX_INK_COVERAGE = 300.0

# Ink coverage comes from large solid areas, which survive downsampling, so the
# artwork is measured at a deliberately low resolution: a page renders in a few
# hundredths of a second instead of seconds. Hairlines could be averaged away,
# but a hairline never drives TAC.
_INK_PROBE_DPI = 72


def estimate_ink_coverage(path, dest_profile=None) -> float:
    """Total ink coverage (%) the artwork at `path` would lay down.

    Rendered small and converted through `dest_profile` — the same profile the
    export will use, since ink load is decided by the press condition, not by
    the file. Returns 0.0 when it cannot be measured: this feeds a warning, and
    a probe failure must never fail a job.
    """
    from pathlib import Path

    from PIL import Image

    path = Path(path)
    try:
        if path.suffix.lower() == ".pdf":
            import fitz

            doc = fitz.open(str(path))
            try:
                if not len(doc):
                    return 0.0
                zoom = _INK_PROBE_DPI / 72.0
                pix = doc[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            finally:
                doc.close()
        else:
            image = Image.open(str(path))
            image.thumbnail((1200, 1200))

        if image.mode != "CMYK":
            if dest_profile is None:
                # Without a profile we would be measuring Pillow's naive
                # formula, which says nothing about the real press.
                return 0.0
            image = convert_image_to_cmyk(image, dest_profile)

        return total_ink_coverage(image)
    except Exception as e:
        logger.debug(f"Encrage non mesurable ({path.name}) : {e}")
        return 0.0
