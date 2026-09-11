"""
Orchestrator: ties together validation -> OCR -> extraction -> financial
validation -> persistence, and assembles the final structured response.
This is the single place that knows the end-to-end flow; each stage's logic
lives in its own service so responsibilities stay separated.
"""
import time
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.schemas.document import (
    DocumentProcessResponse, FileValidation, ProcessingMetadata,
)
from app.schemas.extraction import ValidationResult
from app.services import document_validation_service, ocr_service, extraction_service
from app.services import financial_validation_service
from app.repositories import document_repository
from app.utils.exceptions import AppError

logger = get_logger(__name__)


def process_document(db: Session, filename: str, content: bytes,
                      content_type: Optional[str], document_type: str) -> DocumentProcessResponse:
    start = time.monotonic()
    ocr_used = False

    try:
        file_validation = document_validation_service.validate_file(filename, content, content_type)

        pages_text, ocr_used = ocr_service.extract_text(content, file_validation.file_type)

        extraction = extraction_service.extract_fields(document_type, pages_text)

        validation_result = financial_validation_service.run_validation(
            document_type, extraction.fields, extraction.line_items, extraction.periods
        )

        extracted_data = {
            name: fv.model_dump() for name, fv in extraction.fields.items()
        }
        if extraction.line_items:
            extracted_data["line_items"] = extraction.line_items
        if extraction.periods:
            extracted_data["periods"] = extraction.periods

        processing_status = "PASS" if validation_result.overall_status == "PASS" else "FAILED"

        response = DocumentProcessResponse(
            document_name=filename,
            document_type=document_type,
            processing_status=processing_status,
            overall_confidence=None,
            file_validation=file_validation,
            extracted_data=extracted_data,
            validation=validation_result,
            processing_metadata=ProcessingMetadata(
                ocr_used=ocr_used,
                processed_at=datetime.now(timezone.utc),
                processing_time_ms=int((time.monotonic() - start) * 1000),
            ),
        )

        document_repository.save_result(db, response)
        logger.info("Processed document=%s type=%s status=%s in %dms",
                    filename, document_type, processing_status, response.processing_metadata.processing_time_ms)
        return response

    except AppError as exc:
        # Controlled failure - still return a valid structured response, persisted
        # as FAILED, rather than raising a raw error, so the dashboard reflects it.
        logger.warning("Processing failed for %s: %s", filename, exc.message)
        response = DocumentProcessResponse(
            document_name=filename,
            document_type=document_type,
            processing_status="FAILED",
            overall_confidence=None,
            file_validation=FileValidation(
                file_type=content_type, is_supported=False, is_readable=False,
                page_count=None, status="FAILED", reason=exc.message,
            ),
            extracted_data={},
            validation=ValidationResult(
                checks=[], overall_status="NOT_APPLICABLE", issues=[exc.message]
            ),
            processing_metadata=ProcessingMetadata(
                ocr_used=ocr_used, processed_at=datetime.now(timezone.utc),
                processing_time_ms=int((time.monotonic() - start) * 1000),
            ),
        )
        document_repository.save_result(db, response)
        raise
