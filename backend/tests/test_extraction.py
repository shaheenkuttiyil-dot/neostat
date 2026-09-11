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


def test_summary_rows_excluded_from_line_item_reconciliation():
    """Regression test: a rollup row like 'Aggregated Items' extracted
    alongside individual line items must not be double-counted against the
    subtotal during financial validation."""
    from app.services.financial_validation_service import validate_invoice
    from app.schemas.extraction import FieldValue

    fields = {
        "subtotal": FieldValue(value=5815.0),
        "tax_amount": FieldValue(value=1046.72),
        "discount": FieldValue(value=0.0),
        "total_amount": FieldValue(value=6862.0),
    }
    line_items = [
        {"description": "WHITE DP 140GM", "amount": 892.8},
        {"description": "SPARKLE 200GM BATI 48PCS", "amount": 356.88},
        {"description": "Aggregated Items", "amount": 5815.17},
    ]
    result = validate_invoice(fields, line_items)
    recon = next(c for c in result.checks if c.name == "line_items_reconciliation")
    # Only the two genuine items should be summed, not the rollup row.
    assert recon.calculated_value == 1249.68


def test_garbled_hsn_code_row_excluded_from_quantity_price_check():
    """Regression test: a row where an HSN/SAC code got misread into the
    quantity position produces a wildly wrong quantity*unit_price for that
    row alone - it must be excluded from the aggregate check rather than
    poisoning the whole sum with an absurd number, while clean rows still
    contribute normally."""
    from app.services.financial_validation_service import validate_invoice
    from app.schemas.extraction import FieldValue

    fields = {
        "subtotal": FieldValue(value=1249.68),
        "total_amount": FieldValue(value=1249.68),
    }
    line_items = [
        # Garbled row: HSN code (34029011) misread as unit_price, blows up qty*price
        {"description": "WHITE DP 140GM", "quantity": 61.45, "unit_price": 34029011, "amount": 892.8},
        # Clean row: qty * unit_price matches amount closely
        {"description": "SPARKLE 200GM BATI 48PCS", "quantity": 48, "unit_price": 7.44, "amount": 356.88},
    ]
    result = validate_invoice(fields, line_items)
    check = next(c for c in result.checks if c.name == "quantity_unit_price_check")
    # Only the clean row (48 * 7.44 = 357.12) should be in the computed total -
    # the garbled row's ~2 billion result must not appear.
    assert check.calculated_value < 1000
    assert check.operands["rows_excluded_as_implausible"] == 1
