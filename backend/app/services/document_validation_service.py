"""
Input-control layer. Validates uploaded files BEFORE any OCR/AI extraction:
file type, size sanity, corruption/readability, and page count.

This is deliberately NOT document-type classification -- document_type is
supplied by the caller as request metadata (per spec section 3).
"""
import io
from typing import Optional
from typing import Tuple

import fitz  # PyMuPDF
from PIL import Image, UnidentifiedImageError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.document import FileValidation
from app.utils.exceptions import (
    UnsupportedFileTypeError,
    InvalidFileError,
    PageLimitExceededError,
)

logger = get_logger(__name__)
settings = get_settings()


def _detect_content_type(filename: str, content_type: Optional[str] = None) -> str:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    ext_map = {"pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}
    if content_type in settings.ALLOWED_CONTENT_TYPES:
        return content_type
    if ext in ext_map:
        return ext_map[ext]
    return content_type or "application/octet-stream"


def validate_file(filename: str, content: bytes, content_type: Optional[str]) -> FileValidation:
    """
    Runs the full validation pipeline. Raises AppError subclasses on failure
    (caller/route converts these into controlled error responses); returns a
    FileValidation object with page_count on success.
    """
    logger.info("Validating upload: name=%s declared_content_type=%s size=%d bytes",
                filename, content_type, len(content))

    if not content or len(content) == 0:
        raise InvalidFileError("Uploaded file is empty.")

    size_mb = len(content) / (1024 * 1024)
    if size_mb > settings.MAX_FILE_SIZE_MB:
        raise InvalidFileError(f"File exceeds maximum allowed size of {settings.MAX_FILE_SIZE_MB}MB.")

    resolved_type = _detect_content_type(filename, content_type)
    if resolved_type not in settings.ALLOWED_CONTENT_TYPES:
        raise UnsupportedFileTypeError()

    page_count = 1
    is_readable = True

    if resolved_type == "application/pdf":
        try:
            doc = fitz.open(stream=content, filetype="pdf")
            page_count = doc.page_count
            if page_count == 0:
                raise InvalidFileError("PDF contains no pages.")
            # touch first page to confirm it's actually parseable
            _ = doc.load_page(0)
            doc.close()
        except InvalidFileError:
            raise
        except Exception as exc:
            logger.warning("PDF failed to open/parse: %s", exc)
            raise InvalidFileError("PDF is corrupted or unreadable.") from exc
    else:
        try:
            img = Image.open(io.BytesIO(content))
            img.verify()
            page_count = 1
        except (UnidentifiedImageError, Exception) as exc:
            logger.warning("Image failed to open/verify: %s", exc)
            raise InvalidFileError("Image is corrupted or unreadable.") from exc

    if page_count > settings.MAX_PAGES:
        raise PageLimitExceededError(
            f"Document has {page_count} pages; maximum allowed is {settings.MAX_PAGES}."
        )

    return FileValidation(
        file_type=resolved_type,
        is_supported=True,
        is_readable=is_readable,
        page_count=page_count,
        status="PASS",
    )
