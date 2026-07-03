from pathlib import Path

import fitz
import pytest
from PIL import Image

from src.core.engines.correction_engine import CorrectionEngine
from src.core.models.domain import (
    ColorMode,
    FileFormat,
    FileItem,
    JobSettings,
    PreflightError,
    PreflightErrorType,
    PreflightStatus,
)


@pytest.fixture
def work_dir(tmp_path):
    d = tmp_path / "processing"
    d.mkdir()
    return d


@pytest.fixture
def settings():
    return JobSettings(min_dpi=300, force_cmyk=True)


@pytest.fixture
def engine(settings, work_dir):
    return CorrectionEngine(settings=settings, work_dir=work_dir)


def create_dummy_image(path: Path, mode: str = "RGB", size=(100, 100), dpi=(72, 72)):
    if mode == "RGBA":
        img = Image.new("RGBA", size, (255, 0, 0, 128))
    elif mode == "LA":
        img = Image.new("LA", size, (255, 128))
    elif mode == "P":
        img = Image.new("P", size, 1)
    else:
        img = Image.new(mode, size, color=0 if mode == "L" else (255, 0, 0))
    img.save(path, dpi=dpi)
    return path


def create_dummy_pdf(path: Path):
    doc = fitz.open()
    page = doc.new_page(width=100, height=100)
    page.draw_rect(fitz.Rect(10, 10, 90, 90), color=(1, 0, 0), fill=(1, 0, 0))
    doc.save(path)
    doc.close()
    return path


def test_process_no_warning(engine, tmp_path):
    img_path = create_dummy_image(tmp_path / "test.jpg")
    item = FileItem(
        job_id="00000000-0000-0000-0000-000000000000",
        path=img_path,
        format=FileFormat.JPEG,
        width_mm=100.0,
        height_mm=100.0,
        dpi=300,
        color_mode=ColorMode.CMYK,
        preflight_status=PreflightStatus.OK,
    )
    result = engine.process(item)
    assert result.path == img_path  # Should not be modified


def test_process_rgb_to_cmyk_image(engine, tmp_path):
    img_path = create_dummy_image(tmp_path / "test_rgb.jpg", mode="RGB")
    item = FileItem(
        job_id="00000000-0000-0000-0000-000000000000",
        path=img_path,
        format=FileFormat.JPEG,
        width_mm=100.0,
        height_mm=100.0,
        dpi=300,
        color_mode=ColorMode.RGB,
        preflight_status=PreflightStatus.WARNING,
        preflight_errors=[
            PreflightError(
                type=PreflightErrorType.WRONG_COLOR_MODE, message="RGB detected", is_blocking=False
            )
        ],
    )
    result = engine.process(item)
    assert result.path != img_path
    assert result.preflight_status == PreflightStatus.OK
    assert result.color_mode == ColorMode.CMYK

    # Verify the actual file
    with Image.open(result.path) as img:
        assert img.mode == "CMYK"


def test_process_flattening_image(engine, tmp_path):
    img_path = create_dummy_image(tmp_path / "test_alpha.png", mode="RGBA")
    item = FileItem(
        job_id="00000000-0000-0000-0000-000000000000",
        path=img_path,
        format=FileFormat.PNG,
        width_mm=100.0,
        height_mm=100.0,
        dpi=300,
        color_mode=ColorMode.RGB,
        preflight_status=PreflightStatus.WARNING,
        preflight_errors=[
            PreflightError(
                type=PreflightErrorType.TRANSPARENCY_DETECTED,
                message="Alpha detected",
                is_blocking=False,
            )
        ],
    )
    result = engine.process(item)
    assert result.path != img_path
    assert result.preflight_status == PreflightStatus.OK

    with Image.open(result.path) as img:
        assert img.mode in ("RGB", "CMYK")
        assert "A" not in img.mode


def test_process_dpi_resampling_image(engine, tmp_path):
    img_path = create_dummy_image(tmp_path / "test_lowdpi.jpg", dpi=(72, 72))
    item = FileItem(
        job_id="00000000-0000-0000-0000-000000000000",
        path=img_path,
        format=FileFormat.JPEG,
        width_mm=100.0,
        height_mm=100.0,
        dpi=72,
        color_mode=ColorMode.CMYK,
        preflight_status=PreflightStatus.WARNING,
        preflight_errors=[
            PreflightError(
                type=PreflightErrorType.RESOLUTION_LOW, message="DPI is 72", is_blocking=False
            )
        ],
    )
    result = engine.process(item)
    assert result.dpi == 300
    assert result.preflight_status == PreflightStatus.OK

    with Image.open(result.path) as img:
        assert img.info.get("dpi") == (300, 300)


def test_process_pdf_correction(engine, tmp_path):
    pdf_path = create_dummy_pdf(tmp_path / "test.pdf")
    item = FileItem(
        job_id="00000000-0000-0000-0000-000000000000",
        path=pdf_path,
        format=FileFormat.PDF,
        width_mm=100.0,
        height_mm=100.0,
        dpi=72,
        color_mode=ColorMode.RGB,
        preflight_status=PreflightStatus.WARNING,
        preflight_errors=[
            PreflightError(
                type=PreflightErrorType.WRONG_COLOR_MODE, message="RGB detected", is_blocking=False
            ),
            PreflightError(
                type=PreflightErrorType.RESOLUTION_LOW, message="Low DPI", is_blocking=False
            ),
        ],
    )
    result = engine.process(item)

    assert result.path != pdf_path
    assert result.preflight_status == PreflightStatus.OK
    assert result.color_mode == ColorMode.CMYK
    assert result.dpi == 300

    # Verify the generated PDF
    doc = fitz.open(result.path)
    assert len(doc) == 1
    # Check that it contains an image (rasterized)
    images = doc[0].get_images()
    assert len(images) == 1

    # Extract the image to verify colorspace
    xref = images[0][0]
    pix = fitz.Pixmap(doc, xref)
    assert pix.colorspace.n == 4  # CMYK has 4 components
    doc.close()


def test_process_exception(engine, tmp_path):
    # Pass a path that doesn't exist, which will raise an Exception in PIL/fitz
    item = FileItem(
        job_id="00000000-0000-0000-0000-000000000000",
        path=tmp_path / "does_not_exist.jpg",
        format=FileFormat.JPEG,
        width_mm=100.0,
        height_mm=100.0,
        dpi=300,
        color_mode=ColorMode.RGB,
        preflight_status=PreflightStatus.WARNING,
        preflight_errors=[
            PreflightError(
                type=PreflightErrorType.RESOLUTION_LOW, message="Low", is_blocking=False
            )
        ],
    )
    result = engine.process(item)
    # Should return untouched because exception was caught
    assert result.path == item.path


def test_process_flattening_la(engine, tmp_path):
    img_path = create_dummy_image(tmp_path / "test_la.png", mode="LA")
    item = FileItem(
        job_id="00000000-0000-0000-0000-000000000000",
        path=img_path,
        format=FileFormat.PNG,
        width_mm=100.0,
        height_mm=100.0,
        dpi=300,
        color_mode=ColorMode.RGB,
        preflight_status=PreflightStatus.WARNING,
        preflight_errors=[
            PreflightError(
                type=PreflightErrorType.TRANSPARENCY_DETECTED, message="Alpha", is_blocking=False
            )
        ],
    )
    result = engine.process(item)
    assert result.preflight_status == PreflightStatus.OK


def test_process_flattening_p(engine, tmp_path):
    img_path = create_dummy_image(tmp_path / "test_p.png", mode="P")
    item = FileItem(
        job_id="00000000-0000-0000-0000-000000000000",
        path=img_path,
        format=FileFormat.PNG,
        width_mm=100.0,
        height_mm=100.0,
        dpi=300,
        color_mode=ColorMode.RGB,
        preflight_status=PreflightStatus.WARNING,
        preflight_errors=[
            PreflightError(
                type=PreflightErrorType.TRANSPARENCY_DETECTED, message="Alpha", is_blocking=False
            )
        ],
    )
    result = engine.process(item)
    assert result.preflight_status == PreflightStatus.OK


def test_process_add_bleed_image(engine, tmp_path):
    engine.settings.add_bleed_mm = 5.0
    img_path = create_dummy_image(tmp_path / "test_bleed.jpg", mode="RGB", dpi=(300, 300))
    item = FileItem(
        job_id="00000000-0000-0000-0000-000000000000",
        path=img_path,
        format=FileFormat.JPEG,
        width_mm=100.0,
        height_mm=100.0,
        dpi=300,
        color_mode=ColorMode.RGB,
        preflight_status=PreflightStatus.WARNING,
        preflight_errors=[
            PreflightError(
                type=PreflightErrorType.WRONG_COLOR_MODE, message="RGB", is_blocking=False
            )
        ],
    )
    result = engine.process(item)
    assert result.width_mm == 110.0
    assert result.height_mm == 110.0


def test_process_add_bleed_pdf(engine, tmp_path):
    engine.settings.add_bleed_mm = 5.0
    pdf_path = create_dummy_pdf(tmp_path / "test_bleed.pdf")
    item = FileItem(
        job_id="00000000-0000-0000-0000-000000000000",
        path=pdf_path,
        format=FileFormat.PDF,
        width_mm=100.0,
        height_mm=100.0,
        dpi=300,
        color_mode=ColorMode.RGB,
        preflight_status=PreflightStatus.WARNING,
        preflight_errors=[
            PreflightError(
                type=PreflightErrorType.WRONG_COLOR_MODE, message="RGB", is_blocking=False
            )
        ],
    )
    result = engine.process(item)
    assert result.width_mm == 110.0
    assert result.height_mm == 110.0

