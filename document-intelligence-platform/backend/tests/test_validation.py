"""Tests for the file validation service (input-control layer)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import io
import pytest
from PIL import Image

from app.services.document_validation_service import validate_file
from app.utils.exceptions import UnsupportedFileTypeError, InvalidFileError


def _make_png_bytes():
    img = Image.new("RGB", (10, 10), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_rejects_empty_file():
    with pytest.raises(InvalidFileError):
        validate_file("empty.pdf", b"", "application/pdf")


def test_rejects_unsupported_type():
    with pytest.raises(UnsupportedFileTypeError):
        validate_file("notes.txt", b"hello world", "text/plain")


def test_accepts_valid_png():
    content = _make_png_bytes()
    result = validate_file("photo.png", content, "image/png")
    assert result.status == "PASS"
    assert result.page_count == 1


def test_layout_aware_ocr_reconstructs_table_columns():
    """Regression test for the table-flattening bug: a rendered invoice table
    must come back with pipe-separated columns per row, not a flattened blob
    where row/column association is lost."""
    from app.services.ocr_service import _layout_aware_ocr
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (700, 200), color="white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    except Exception:
        font = ImageFont.load_default()
    d.text((20, 20), "Description", fill="black", font=font)
    d.text((300, 20), "Qty", fill="black", font=font)
    d.text((400, 20), "Amount", fill="black", font=font)
    d.text((20, 60), "Widget A", fill="black", font=font)
    d.text((300, 60), "2", fill="black", font=font)
    d.text((400, 60), "0.90", fill="black", font=font)

    text = _layout_aware_ocr(img)
    lines = [l for l in text.split("\n") if l.strip()]
    assert any("Widget A" in l and "|" in l and "0.90" in l for l in lines), \
        f"Expected a pipe-delimited row containing the line item and amount, got: {lines}"


def test_rejects_corrupted_pdf():
    with pytest.raises(InvalidFileError):
        validate_file("bad.pdf", b"%PDF-1.4 not a real pdf structure", "application/pdf")
