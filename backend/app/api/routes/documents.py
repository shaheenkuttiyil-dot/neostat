"""
REST API routes for document processing, per spec:
  POST /api/v1/documents/process
  GET  /api/v1/documents/{document_name}
  GET  /api/v1/documents
  GET  /api/v1/health
"""
import json
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.logging import get_logger
from app.schemas.document import DocumentProcessResponse, DocumentListItem, DocumentType
from app.services import document_service
from app.repositories import document_repository
from app.utils.exceptions import AppError, DocumentNotFoundError

logger = get_logger(__name__)
router = APIRouter()


@router.get("/health")
def health_check():
    return {"status": "ok"}


@router.post("/documents/process", response_model=DocumentProcessResponse)
async def process_document(
    file: UploadFile = File(...),
    document_type: DocumentType = Form(...),
    db: Session = Depends(get_db),
):
    content = await file.read()
    try:
        result = document_service.process_document(
            db=db,
            filename=file.filename,
            content=content,
            content_type=file.content_type,
            document_type=document_type.value,
        )
        return result
    except AppError:
        # Handled globally by the app_error_handler exception handler in main.py,
        # which returns the {"error": {"code", "message"}} shape directly.
        raise
    except Exception:
        logger.exception("Unexpected error while processing document")
        raise HTTPException(
            status_code=500,
            detail={"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred while processing the document."}},
        )


@router.get("/documents/{document_name}")
def get_document_by_name(document_name: str, db: Session = Depends(get_db)):
    record = document_repository.get_latest_by_name(db, document_name)
    if not record:
        raise DocumentNotFoundError(f"No processed result found for '{document_name}'.")
    return json.loads(record.result_json)


@router.get("/documents", response_model=list[DocumentListItem])
def list_documents(db: Session = Depends(get_db)):
    return document_repository.list_all(db)
