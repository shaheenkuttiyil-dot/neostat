"""
SQLAlchemy ORM model for persisted processing results.

Design note: we store the full structured response as JSON text alongside a
handful of indexed columns (document_name, document_type, status, timestamp)
so the dashboard list/detail views are fast without needing to re-parse JSON,
while GET-by-name always returns the latest row for that document name.
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime

from app.core.database import Base


class ProcessedDocument(Base):
    __tablename__ = "processed_documents"

    id = Column(Integer, primary_key=True, index=True)
    document_name = Column(String(500), index=True, nullable=False)
    document_type = Column(String(100), index=True, nullable=False)
    processing_status = Column(String(20), index=True, nullable=False)  # PASS / FAILED
    overall_confidence = Column(String(20), nullable=True)  # stored as string, optional
    result_json = Column(Text, nullable=False)  # full structured response (source of truth)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
