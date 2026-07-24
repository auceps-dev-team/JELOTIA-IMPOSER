"""Baseline-conformant TIFF writing, the way Photoshop writes it.

Print software (RIPs, Maintop, Onyx, Caldera…) is overwhelmingly tested against
files Photoshop produced, so matching Photoshop's baseline is the pragmatic
definition of "compatible". What Photoshop actually emits for a CMYK TIFF:

- extension `.tif` (three letters) — its default, and the only pattern a lot of
  legacy import filters match on;
- little-endian ("II"), classic TIFF, IFD right after the header;
- PhotometricInterpretation = 5 (Separated), 4 samples of 8 bits, chunky;
- InkSet = 1 and NumberOfInks = 4 — TIFF 6.0 §20 asks for these on CMYK, and
  decoders that miss them fall back to greyscale or refuse the file;
- strips sized in the tens of KB, not thousands of tiny strips;
- resolution in inches (ResolutionUnit = 2) with the real DPI;
- the ICC profile embedded (tag 34675) so the colour space is declared.

Pillow gets most of this right but leaves InkSet/NumberOfInks out and slices
strips by a fixed byte budget, which on a large sheet yields thousands of them.
Both are corrected here.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# TIFF tag numbers we set explicitly (names per TIFF 6.0).
TAG_ROWS_PER_STRIP = 278
TAG_SOFTWARE = 305
TAG_INK_SET = 332
TAG_NUMBER_OF_INKS = 334

# Photoshop keeps strips in the tens of KB. Large enough that a big sheet does
# not produce thousands of strips (which old decoders choke on), small enough
# that a decoder never has to buffer the whole image.
STRIP_TARGET_BYTES = 256 * 1024

# Compression values accepted from settings, mapped to Pillow's names. RAW is
# the most portable, LZW the Photoshop default, PackBits the safe middle ground.
COMPRESSIONS = {
    "raw": None,
    "none": None,
    "tiff_lzw": "tiff_lzw",
    "lzw": "tiff_lzw",
    "packbits": "packbits",
    "tiff_packbits": "packbits",
    "tiff_adobe_deflate": "tiff_adobe_deflate",
}


def normalise_compression(value: Optional[str]) -> Optional[str]:
    """Pillow's compression name for a settings value; LZW when unrecognised."""
    if value is None:
        return "tiff_lzw"
    return COMPRESSIONS.get(str(value).strip().lower(), "tiff_lzw")


def rows_per_strip(width: int, samples: int, height: int) -> int:
    """Rows per strip targeting STRIP_TARGET_BYTES, clamped to the image.

    Never returns 0 (a zero-row strip is an invalid file) and never exceeds the
    image height (a strip taller than the image is equally invalid).
    """
    row_bytes = max(1, width * samples)
    rows = max(1, STRIP_TARGET_BYTES // row_bytes)
    return int(min(rows, max(1, height)))


def save_tiff(
    img,
    path: Path,
    dpi: int,
    compression: Optional[str] = "tiff_lzw",
    software: str = "",
    icc_profile: Optional[bytes] = None,
) -> Path:
    """Writes `img` as a baseline-conformant TIFF and returns the path.

    `compression` takes a settings-level value ("raw", "packbits", "tiff_lzw"…).
    The ICC profile is embedded when supplied — omit it only for decoders known
    to choke on the tag.
    """
    from PIL import TiffImagePlugin

    path = Path(path)
    pillow_compression = normalise_compression(compression)

    tiffinfo = TiffImagePlugin.ImageFileDirectory_v2()
    if img.mode == "CMYK":
        # TIFF 6.0 §20: without these a CMYK file is ambiguous, and legacy
        # decoders read it as greyscale or reject it outright.
        tiffinfo[TAG_INK_SET] = 1          # 1 = CMYK
        tiffinfo[TAG_NUMBER_OF_INKS] = 4
    if software:
        tiffinfo[TAG_SOFTWARE] = software

    samples = len(img.getbands())
    tiffinfo[TAG_ROWS_PER_STRIP] = rows_per_strip(img.width, samples, img.height)

    options = {"dpi": (dpi, dpi), "tiffinfo": tiffinfo}
    if icc_profile:
        options["icc_profile"] = icc_profile

    # Pillow slices strips against this module-level budget; align it with the
    # RowsPerStrip we just asked for so the two agree.
    original_strip_size = TiffImagePlugin.STRIP_SIZE
    try:
        TiffImagePlugin.STRIP_SIZE = STRIP_TARGET_BYTES
        img.save(str(path), format="TIFF", compression=pillow_compression, **options)
    finally:
        TiffImagePlugin.STRIP_SIZE = original_strip_size

    logger.info(
        f"TIFF écrit : {path.name} "
        f"(compression={pillow_compression or 'aucune'}, {img.mode}, {dpi} dpi)"
    )
    return path
