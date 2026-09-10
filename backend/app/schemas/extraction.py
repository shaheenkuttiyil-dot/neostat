"""
Pydantic schemas describing the shape of extracted field data, financial
validation checks, and evidence/grounding — shared across all 4 document
types. Field *sets* differ by document type (see extraction_service prompts);
this schema intentionally keeps extracted_data flexible (Dict[str, FieldValue])
rather than hardcoding a rigid per-type model, because the requirement is to
capture ALL meaningful visible fields, not a fixed minimal list.
"""
from typing import Optional, Any, Dict, List
from pydantic import BaseModel, Field


class Evidence(BaseModel):
    source_text: Optional[str] = None
    page_number: Optional[int] = None


class FieldValue(BaseModel):
    """A single extracted field. `value` is null when not present in the document."""
    value: Optional[Any] = None
    confidence: Optional[float] = None  # OPTIONAL per spec
    evidence: Optional[Evidence] = None


class LineItem(BaseModel):
    """Generic invoice/statement line item. Extra keys are allowed since
    line item columns vary across documents (e.g. tax rate, HSN code)."""
    model_config = {"extra": "allow"}

    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None


class ValidationCheck(BaseModel):
    name: str
    formula: str
    operands: Dict[str, Optional[float]] = Field(default_factory=dict)
    calculated_value: Optional[float] = None
    reported_value: Optional[float] = None
    variance: Optional[float] = None
    status: str  # PASS | FAIL | NOT_APPLICABLE


class ValidationResult(BaseModel):
    checks: List[ValidationCheck] = Field(default_factory=list)
    overall_status: str = "NOT_APPLICABLE"  # PASS | FAIL | NOT_APPLICABLE
    issues: List[str] = Field(default_factory=list)


class ExtractionPayload(BaseModel):
    """Raw output contract expected back from the LLM extraction step,
    per document/period. Kept generic; validated & coerced before persistence."""
    fields: Dict[str, FieldValue] = Field(default_factory=dict)
    line_items: List[Dict[str, Any]] = Field(default_factory=list)
    periods: Optional[List[str]] = None  # comparative periods found, if any
