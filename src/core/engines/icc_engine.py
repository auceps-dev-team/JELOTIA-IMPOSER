"""Real ICC colour management.

`img.convert("CMYK")` in Pillow is a naive formula (C = 255 - R …), not a
colorimetric conversion, and it is actively harmful for print. Measured on
pure black with the SWOP profile:

    naive : C255 M255 J255 N0  -> 300 % total ink
    ICC   : C0   M0   J0   N255 -> 100 %, clean 100K black

300 % ink floods the media, never dries, and gets a job rejected by the RIP.
This module routes conversions through littleCMS (Pillow's ImageCms) with real
profiles instead, and can measure total ink coverage (TAC) afterwards.

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

    Above ~300 % the ink no longer dries and RIPs reject the file — this is the
    number the naive conversion silently blows past on blacks.
    """
    if image.mode != "CMYK":
        return 0.0
    # Per-channel histograms can't answer this: the four inks must be summed on
    # the SAME pixel, so walk the data once and keep the worst.
    worst = 0
    for pixel in image.get_flattened_data():
        total = sum(pixel)
        if total > worst:
            worst = total
    return worst / 255.0 * 100.0
