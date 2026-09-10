"""Tests for extraction payload parsing/coercion and deterministic fallbacks
(no live LLM calls)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.schemas.extraction import ExtractionPayload
from app.services.extraction_service import _regex_fallback_invoice_number


def test_extraction_payload_allows_null_values():
    payload = ExtractionPayload(**{
        "fields": {
            "invoice_number": {"value": "INV-1", "evidence": {"source_text": "INV-1", "page_number": 1}},
            "discount": {"value": None, "evidence": None},
        },
        "line_items": [{"description": "Item A", "quantity": 1, "unit_price": 100, "amount": 100}],
        "periods": None,
    })
    assert payload.fields["invoice_number"].value == "INV-1"
    assert payload.fields["discount"].value is None
    assert len(payload.line_items) == 1


def test_invoice_number_regex_fallback_handles_ocr_noise():
    """Regression test: 'INVOICE' header alone must not be mistaken for the
    invoice number, and OCR noise like 'Cl' (I misread as l) must still be
    captured from a genuine 'Invoice No:' label."""
    pages = ["INVOICE\nInvoice No: Cl/25-26/3331\nWidget A | 2 | 0.45 | 0.90"]
    result = _regex_fallback_invoice_number(pages)
    assert result is not None
    assert result["value"] == "Cl/25-26/3331"


def test_invoice_number_regex_fallback_returns_none_when_absent():
    pages = ["Some random receipt text with no invoice number field here"]
    assert _regex_fallback_invoice_number(pages) is None
