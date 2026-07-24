"""Baseline TIFF conformance — what makes a file readable by print software.

Regression: Maintop DTP v5.3 (and other legacy RIPs) refused every export.
The files were written as ".tiff", which legacy import filters matching "*.tif"
never list, and they lacked the CMYK ink tags TIFF 6.0 §20 requires.
"""

import uuid

import pytest
from PIL import Image

from src.core.engines.photoshop_tiff import (
    normalise_compression,
    rows_per_strip,
    save_tiff,
)


@pytest.fixture
def cmyk_image():
    return Image.new("CMYK", (600, 400), (0, 0, 0, 255))


# --- strip sizing ---------------------------------------------------------- #

def test_rows_per_strip_never_degenerates():
    """RowsPerStrip=2 on a tall sheet meant thousands of strips; 0 or a value
    above the image height would be an invalid file."""
    assert rows_per_strip(width=5000, samples=4, height=10512) >= 1
    assert rows_per_strip(width=5000, samples=4, height=10512) <= 10512
    # A tiny image can't ask for more rows than it has.
    assert rows_per_strip(width=10, samples=4, height=3) == 3
    # A pathologically wide row still yields at least one row per strip.
    assert rows_per_strip(width=10_000_000, samples=4, height=50) == 1


def test_strip_count_stays_reasonable_on_a_large_sheet(tmp_path):
    # Compressed so the fixture stays small: what matters is the strip layout,
    # not the payload. RowsPerStrip=2 previously gave one strip per 2 rows.
    img = Image.new("CMYK", (1200, 1600), (0, 0, 0, 255))
    path = save_tiff(img, tmp_path / "big.tif", dpi=300, compression="tiff_lzw")

    with Image.open(path) as im:
        strips = len(im.tag_v2.get(273, ()))
    assert strips < 200, f"{strips} bandes — trop de strips pour un vieux décodeur"
    assert strips >= 1


# --- CMYK baseline tags ---------------------------------------------------- #

@pytest.mark.parametrize("compression", ["tiff_lzw", "raw", "packbits"])
def test_cmyk_ink_tags_are_written(cmyk_image, tmp_path, compression):
    """Without InkSet/NumberOfInks a CMYK TIFF is ambiguous and legacy decoders
    read it as greyscale or refuse it."""
    path = save_tiff(cmyk_image, tmp_path / f"{compression}.tif", dpi=300,
                     compression=compression)

    with Image.open(path) as im:
        tags = im.tag_v2
        assert tags.get(332) == 1, "InkSet doit valoir 1 (CMYK)"
        assert tags.get(334) == 4, "NumberOfInks doit valoir 4"
        assert tags.get(262) == 5, "PhotometricInterpretation doit valoir 5"
        assert tags.get(284) == 1, "PlanarConfiguration doit être chunky"
        assert tuple(tags.get(258)) == (8, 8, 8, 8)
        assert im.mode == "CMYK"


def test_rgb_image_does_not_get_cmyk_ink_tags(tmp_path):
    path = save_tiff(Image.new("RGB", (50, 50)), tmp_path / "rgb.tif", dpi=72)
    with Image.open(path) as im:
        assert im.tag_v2.get(332) is None, "pas d'InkSet sur une image RGB"


def test_resolution_is_declared_in_inches(cmyk_image, tmp_path):
    path = save_tiff(cmyk_image, tmp_path / "res.tif", dpi=300)
    with Image.open(path) as im:
        assert im.tag_v2.get(296) == 2, "ResolutionUnit doit être le pouce"
        assert float(im.tag_v2.get(282)) == 300.0
        assert im.info.get("dpi") == (300.0, 300.0)


def test_icc_profile_embedded_only_when_supplied(cmyk_image, tmp_path):
    tagged = save_tiff(cmyk_image, tmp_path / "tagged.tif", dpi=300,
                       icc_profile=b"\x00" * 128)
    with Image.open(tagged) as im:
        assert im.info.get("icc_profile"), "le profil fourni doit être embarqué"

    bare = save_tiff(cmyk_image, tmp_path / "bare.tif", dpi=300, icc_profile=None)
    with Image.open(bare) as im:
        assert not im.info.get("icc_profile")


def test_software_tag_is_written(cmyk_image, tmp_path):
    path = save_tiff(cmyk_image, tmp_path / "sw.tif", dpi=300,
                     software="Jelotia Imposer 9.9.9")
    with Image.open(path) as im:
        assert "Jelotia" in str(im.tag_v2.get(305))


# --- compression mapping --------------------------------------------------- #

@pytest.mark.parametrize("value,expected", [
    ("raw", None), ("none", None), ("RAW", None),
    ("packbits", "packbits"), ("tiff_packbits", "packbits"),
    ("lzw", "tiff_lzw"), ("tiff_lzw", "tiff_lzw"),
    (None, "tiff_lzw"), ("n'importe quoi", "tiff_lzw"),
])
def test_compression_names_are_normalised(value, expected):
    assert normalise_compression(value) is expected or \
           normalise_compression(value) == expected


def test_uncompressed_file_is_actually_uncompressed(cmyk_image, tmp_path):
    path = save_tiff(cmyk_image, tmp_path / "raw.tif", dpi=300, compression="raw")
    with Image.open(path) as im:
        assert im.tag_v2.get(259) == 1, "compression 1 = aucune"


def test_written_file_reopens_identically(cmyk_image, tmp_path):
    """A file no decoder can round-trip is worthless regardless of its tags."""
    path = save_tiff(cmyk_image, tmp_path / "rt.tif", dpi=300, compression="packbits")
    with Image.open(path) as im:
        assert im.size == cmyk_image.size
        assert im.getpixel((10, 10)) == (0, 0, 0, 255)


def test_export_uses_the_three_letter_extension(tmp_path):
    """The confound behind every failed import test: legacy filters match *.tif."""
    import fitz

    from src.core.engines.export_engine import ExportEngine
    from src.core.models.domain import JobSettings, Sheet

    doc = fitz.open()
    doc.new_page(width=200, height=150)
    base = tmp_path / "base.pdf"
    doc.save(str(base))
    doc.close()

    sheet = Sheet(job_id=uuid.uuid4(), sheet_number=1, width_mm=70.0, height_mm=52.0)
    result = ExportEngine().export_sheet(
        uuid.uuid4(), sheet, base, JobSettings(export_format="TIFF", export_dpi=72),
        tmp_path / "out", job_name="ext",
    )
    assert result.suffix == ".tif", "Photoshop et les vieux RIP attendent .tif"
