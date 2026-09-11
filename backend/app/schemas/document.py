"""
Top-level API request/response schemas for the document processing endpoints.
Matches the structured response contract required by the case study spec.
"""
from typing import Optional, Any, Dict, List
from enum import Enum
from datetime import datetime
from pydantic import BaseModel, Field

from app.schemas.extraction import ValidationResult


class DocumentType(str, Enum):
    invoice = "invoice"
    balance_sheet = "balance_sheet"
    profit_and_loss = "profit_and_loss"
    cash_flow_statement = "cash_flow_statement"


class ProcessingStatus(str, Enum):
    pass_ = "PASS"
    failed = "FAILED"


class FileValidation(BaseModel):
    file_type: Optional[str] = None
    is_supported: bool
    is_readable: bool
    page_count: Optional[int] = None
    status: str  # PASS | FAILED
    reason: Optional[str] = None  # populated on failure


class ProcessingMetadata(BaseModel):
    ocr_used: bool
    processed_at: datetime
    processing_time_ms: int


class DocumentProcessResponse(BaseModel):
    document_name: str
    document_type: str
    processing_status: str  # PASS | FAILED
    overall_confidence: Optional[float] = None
    file_validation: FileValidation
    extracted_data: Dict[str, Any] = Field(default_factory=dict)
    validation: ValidationResult
    processing_metadata: ProcessingMetadata


class DocumentListItem(BaseModel):
    document_name: str
    document_type: str
    processing_status: str
    processed_at: datetime


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
    
class DocumentListItem(BaseModel):
    document_name: str
    document_type: str
    processing_status: str
    processed_at: datetime
    overall_confidence: Optional[float] = None   # <-- NEW (needed for "Avg Confidence" card)