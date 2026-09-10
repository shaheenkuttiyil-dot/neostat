"""Custom application exceptions -> mapped to controlled HTTP responses in main.py."""


class AppError(Exception):
    """Base application error. code maps to a stable machine-readable error code,
    status_code to the HTTP status returned to the client."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class UnsupportedFileTypeError(AppError):
    def __init__(self, message="Only PDF / JPG / PNG documents are supported."):
        super().__init__("UNSUPPORTED_FILE_TYPE", message, 415)


class InvalidFileError(AppError):
    def __init__(self, message="File is empty, corrupted or unreadable."):
        super().__init__("INVALID_FILE", message, 400)


class PageLimitExceededError(AppError):
    def __init__(self, message="Document exceeds the maximum allowed page count."):
        super().__init__("PAGE_LIMIT_EXCEEDED", message, 400)


class OCRProcessingError(AppError):
    def __init__(self, message="Text extraction / OCR failed for this document."):
        super().__init__("OCR_FAILED", message, 502)


class ExtractionError(AppError):
    def __init__(self, message="AI-based field extraction failed for this document."):
        super().__init__("EXTRACTION_FAILED", message, 502)


class DocumentNotFoundError(AppError):
    def __init__(self, message="No processed result found for this document name."):
        super().__init__("DOCUMENT_NOT_FOUND", message, 404)
