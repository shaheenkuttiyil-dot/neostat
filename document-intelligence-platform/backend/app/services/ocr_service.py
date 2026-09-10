"""
Text extraction / OCR service.

Strategy:
  - Native PDFs: extract embedded text layer directly (PyMuPDF) - fast, no OCR needed.
  - Scanned PDFs (no/very little embedded text): rasterize each page and run
    LAYOUT-AWARE Tesseract OCR (word bounding boxes reconstructed into rows/columns).
  - JPG/PNG: run layout-aware Tesseract OCR directly.

Why layout-aware OCR: plain `image_to_string` flattens tables into a single
text stream, which loses column alignment and causes the LLM to misread which
amount belongs to which line item. `image_to_data` gives per-word bounding
boxes; we cluster words into lines by vertical position, then insert explicit
column separators ("|") wherever the horizontal gap between adjacent words is
large enough to indicate a column boundary, before handing the result to the
LLM. This is a heuristic, not true table structure detection - see README
"Known Limitations" for the more rigorous approaches (e.g. layout models,
bounding-box-grounded evidence) that a production system would use instead.
"""
import io
from typing import List, Tuple

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

from app.core.config import get_settings
from app.core.logging import get_logger
from app.utils.exceptions import OCRProcessingError

logger = get_logger(__name__)
settings = get_settings()

if settings.TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD

# Below this many characters of native text per page, we treat the page as
# scanned/image-based and fall back to OCR.
MIN_NATIVE_TEXT_CHARS = 20

# Layout reconstruction tuning
LINE_Y_TOLERANCE_PX = 10     # words within this many px of vertical top => same line
COLUMN_GAP_THRESHOLD_PX = 35  # horizontal gap larger than this => treat as a column boundary
MIN_WORD_CONFIDENCE = 20     # discard very low-confidence OCR noise tokens


def extract_text(content: bytes, file_type: str) -> Tuple[List[str], bool]:
    """
    Returns (pages_text, ocr_used) where pages_text[i] is the text for page i+1.
    """
    try:
        if file_type == "application/pdf":
            return _extract_from_pdf(content)
        else:
            return _extract_from_image(content)
    except OCRProcessingError:
        raise
    except Exception as exc:
        logger.exception("OCR/text extraction failed")
        raise OCRProcessingError(f"Text extraction failed: {exc}") from exc


def _extract_from_pdf(content: bytes) -> Tuple[List[str], bool]:
    doc = fitz.open(stream=content, filetype="pdf")
    pages_text: List[str] = []
    ocr_used = False

    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        native_text = page.get_text("text").strip()

        if len(native_text) >= MIN_NATIVE_TEXT_CHARS:
            pages_text.append(native_text)
        else:
            # Likely a scanned page - rasterize and run layout-aware OCR.
            ocr_used = True
            pix = page.get_pixmap(dpi=300)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            pages_text.append(_layout_aware_ocr(img))

    doc.close()
    return pages_text, ocr_used


def _extract_from_image(content: bytes) -> Tuple[List[str], bool]:
    img = Image.open(io.BytesIO(content))
    img = _auto_orient(img)
    return [_layout_aware_ocr(img)], True


def _auto_orient(img: Image.Image) -> Image.Image:
    """Best-effort orientation correction using Tesseract's OSD. Falls back to
    the original image if OSD can't determine orientation confidently (e.g.
    very sparse or low-quality scans) - heuristic, not guaranteed for every
    document (see README Known Limitations)."""
    try:
        osd = pytesseract.image_to_osd(img)
        rotate = 0
        for line in osd.splitlines():
            if line.lower().startswith("rotate:"):
                rotate = int(line.split(":")[1].strip())
        if rotate in (90, 180, 270):
            img = img.rotate(-rotate, expand=True)
    except Exception:
        pass
    return img


def _layout_aware_ocr(img: Image.Image) -> str:
    """Reconstructs rows/columns from word-level bounding boxes instead of
    returning a flattened text blob."""
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

    words = []
    n = len(data["text"])
    for i in range(n):
        text = data["text"][i].strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except (ValueError, TypeError):
            conf = -1
        if conf != -1 and conf < MIN_WORD_CONFIDENCE:
            continue
        words.append({
            "text": text,
            "left": data["left"][i],
            "top": data["top"][i],
            "width": data["width"][i],
        })

    if not words:
        # Nothing usable from layout parsing - fall back to plain OCR text.
        return pytesseract.image_to_string(img).strip()

    words.sort(key=lambda w: (w["top"], w["left"]))

    lines = []
    current_line = [words[0]]
    current_top = words[0]["top"]

    for w in words[1:]:
        if abs(w["top"] - current_top) <= LINE_Y_TOLERANCE_PX:
            current_line.append(w)
        else:
            lines.append(current_line)
            current_line = [w]
            current_top = w["top"]
    lines.append(current_line)

    rendered_lines = []
    for line in lines:
        line.sort(key=lambda w: w["left"])
        parts = [line[0]["text"]]
        for prev, curr in zip(line, line[1:]):
            gap = curr["left"] - (prev["left"] + prev["width"])
            separator = " | " if gap > COLUMN_GAP_THRESHOLD_PX else " "
            parts.append(separator + curr["text"])
        rendered_lines.append("".join(parts))

    return "\n".join(rendered_lines)
