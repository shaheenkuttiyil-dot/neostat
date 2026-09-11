"""
Persistence layer for processed documents. Isolated from API/service logic
so the storage backend (SQLite now, Postgres/MySQL later) can change without
touching business logic.
"""
import json
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.document import ProcessedDocument
from app.schemas.document import DocumentProcessResponse, DocumentListItem


def save_result(db: Session, response: DocumentProcessResponse) -> ProcessedDocument:
    record = ProcessedDocument(
        document_name=response.document_name,
        document_type=response.document_type,
        processing_status=response.processing_status,
        overall_confidence=str(response.overall_confidence) if response.overall_confidence is not None else None,
        result_json=response.model_dump_json(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_latest_by_name(db: Session, document_name: str) -> Optional[ProcessedDocument]:
    return (
        db.query(ProcessedDocument)
        .filter(ProcessedDocument.document_name == document_name)
        .order_by(desc(ProcessedDocument.created_at))
        .first()
    )


def list_all(db: Session, limit: int = 200) -> List[DocumentListItem]:
    rows = (
        db.query(ProcessedDocument)
        .order_by(desc(ProcessedDocument.created_at))
        .limit(limit)
        .all()
    )
    items = []
    for r in rows:
        items.append(DocumentListItem(
            document_name=r.document_name,
            document_type=r.document_type,
            processing_status=r.processing_status,
            processed_at=r.created_at,
        ))
    return items


def parse_result_json(record: ProcessedDocument) -> dict:
    return json.loads(record.result_json)

def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

# inside list_all(), in the DocumentListItem(...) constructor add:
#     overall_confidence=_to_float(r.overall_confidence),