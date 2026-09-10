"""
Financial calculation validation.

Rules: validations run ONLY against fields that are actually present in the
extracted data. If a required field is missing, the check returns
NOT_APPLICABLE (never assumes/invents a value). Status is PASS/FAIL based on
absolute variance against a configurable tolerance.
"""
import re
from typing import Dict, Optional, List, Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.extraction import ValidationCheck, ValidationResult, FieldValue

logger = get_logger(__name__)
settings = get_settings()
TOLERANCE = settings.VALIDATION_TOLERANCE

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


def _num(fields: Dict[str, FieldValue], name: str) -> Optional[float]:
    fv = fields.get(name)
    if fv is None or fv.value is None:
        return None
    try:
        return float(fv.value)
    except (TypeError, ValueError):
        return None


def _check(name: str, formula: str, operands: Dict[str, Optional[float]],
           calculated: Optional[float], reported: Optional[float]) -> ValidationCheck:
    if calculated is None or reported is None:
        return ValidationCheck(
            name=name, formula=formula, operands=operands,
            calculated_value=calculated, reported_value=reported,
            variance=None, status="NOT_APPLICABLE",
        )
    variance = round(calculated - reported, 2)
    status = "PASS" if abs(variance) <= TOLERANCE else "FAIL"
    return ValidationCheck(
        name=name, formula=formula, operands=operands,
        calculated_value=round(calculated, 2), reported_value=round(reported, 2),
        variance=variance, status=status,
    )


def _sum_line_item_key(line_items: List[Dict[str, Any]], key: str) -> Optional[float]:
    values = []
    for li in line_items:
        v = li.get(key)
        if v is None:
            continue
        try:
            values.append(float(v))
        except (TypeError, ValueError):
            continue
    return round(sum(values), 2) if values else None


def validate_invoice(fields: Dict[str, FieldValue], line_items: List[Dict[str, Any]]) -> ValidationResult:
    checks = []

    subtotal = _num(fields, "subtotal")
    tax = _num(fields, "tax_amount")
    discount = _num(fields, "discount") or 0.0
    total = _num(fields, "total_amount")

    calc_total = None
    if subtotal is not None and tax is not None:
        calc_total = subtotal + tax - discount
    checks.append(_check(
        "invoice_total_check", "subtotal + tax_amount - discount",
        {"subtotal": subtotal, "tax_amount": tax, "discount": discount},
        calc_total, total,
    ))

    if line_items:
        line_total_sum = _sum_line_item_key(line_items, "amount")
        checks.append(_check(
            "line_items_reconciliation", "sum(line_items.amount)",
            {"sum_line_items": line_total_sum}, line_total_sum, subtotal,
        ))
        # quantity * unit_price ~= amount, per line item (aggregate check)
        qty_price_total = 0.0
        any_data = False
        for li in line_items:
            q, p, a = li.get("quantity"), li.get("unit_price"), li.get("amount")
            if q is not None and p is not None:
                try:
                    qty_price_total += float(q) * float(p)
                    any_data = True
                except (TypeError, ValueError):
                    pass
        checks.append(_check(
            "quantity_unit_price_check", "sum(quantity * unit_price)",
            {"computed": qty_price_total if any_data else None},
            qty_price_total if any_data else None, line_total_sum,
        ))

    cash_paid = _num(fields, "cash_paid")
    change = _num(fields, "change")
    if cash_paid is not None and total is not None:
        checks.append(_check(
            "cash_change_check", "cash_paid - total_amount", {"cash_paid": cash_paid, "total_amount": total},
            round(cash_paid - total, 2), change,
        ))

    # GSTIN / tax-ID format check - OCR frequently corrupts these (e.g. a
    # digit misread as a letter), and a malformed ID silently passed through
    # as if valid is worse than flagging it for manual review.
    for gstin_field in ("vendor_gstin", "customer_gstin", "gstin"):
        fv = fields.get(gstin_field)
        if fv is not None and fv.value:
            raw = str(fv.value).strip().upper()
            is_valid = bool(GSTIN_RE.match(raw))
            checks.append(ValidationCheck(
                name=f"{gstin_field}_format_check",
                formula="matches GSTIN pattern ^\\d{2}[A-Z]{5}\\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$",
                operands={},
                calculated_value=None,
                reported_value=None,
                variance=None,
                status="PASS" if is_valid else "FAIL",
            ))

    overall = _overall_status(checks)
    return ValidationResult(checks=checks, overall_status=overall, issues=_issues(checks))


def validate_balance_sheet(fields: Dict[str, FieldValue]) -> ValidationResult:
    checks = []
    assets = _num(fields, "total_assets")
    liabilities = _num(fields, "total_liabilities")
    equity = _num(fields, "total_equity")

    calc = None
    if liabilities is not None and equity is not None:
        calc = liabilities + equity
    checks.append(_check(
        "assets_equals_liabilities_plus_equity",
        "total_liabilities + total_equity", {"total_liabilities": liabilities, "total_equity": equity},
        calc, assets,
    ))
    overall = _overall_status(checks)
    return ValidationResult(checks=checks, overall_status=overall, issues=_issues(checks))


def validate_profit_and_loss(fields: Dict[str, FieldValue]) -> ValidationResult:
    checks = []
    revenue = _num(fields, "revenue")
    cogs = _num(fields, "cost_of_sales") or _num(fields, "cogs")
    gross_profit = _num(fields, "gross_profit")
    opex = _num(fields, "operating_expenses")
    operating_profit = _num(fields, "operating_profit")
    tax = _num(fields, "tax")
    net_profit = _num(fields, "net_profit")

    calc_gross = None
    if revenue is not None and cogs is not None:
        calc_gross = revenue - cogs
    checks.append(_check(
        "gross_profit_check", "revenue - cost_of_sales",
        {"revenue": revenue, "cost_of_sales": cogs}, calc_gross, gross_profit,
    ))

    calc_operating = None
    if gross_profit is not None and opex is not None:
        calc_operating = gross_profit - opex
    checks.append(_check(
        "operating_profit_check", "gross_profit - operating_expenses",
        {"gross_profit": gross_profit, "operating_expenses": opex}, calc_operating, operating_profit,
    ))

    calc_net = None
    if operating_profit is not None and tax is not None:
        calc_net = operating_profit - tax
    checks.append(_check(
        "net_profit_check", "operating_profit - tax",
        {"operating_profit": operating_profit, "tax": tax}, calc_net, net_profit,
    ))

    overall = _overall_status(checks)
    return ValidationResult(checks=checks, overall_status=overall, issues=_issues(checks))


def validate_cash_flow(fields: Dict[str, FieldValue]) -> ValidationResult:
    checks = []
    ocf = _num(fields, "operating_cash_flow")
    icf = _num(fields, "investing_cash_flow")
    fcf = _num(fields, "financing_cash_flow")
    fx = _num(fields, "fx_translation_adjustment") or 0.0
    net_change = _num(fields, "net_change_in_cash")
    opening = _num(fields, "opening_cash")
    closing = _num(fields, "closing_cash")

    calc_net_change = None
    if ocf is not None and icf is not None and fcf is not None:
        calc_net_change = ocf + icf + fcf + fx
    checks.append(_check(
        "net_change_in_cash_check", "operating + investing + financing + fx_adjustment",
        {"operating_cash_flow": ocf, "investing_cash_flow": icf, "financing_cash_flow": fcf, "fx_adjustment": fx},
        calc_net_change, net_change,
    ))

    calc_closing = None
    if opening is not None and net_change is not None:
        calc_closing = opening + net_change
    checks.append(_check(
        "closing_cash_check", "opening_cash + net_change_in_cash",
        {"opening_cash": opening, "net_change_in_cash": net_change}, calc_closing, closing,
    ))

    overall = _overall_status(checks)
    return ValidationResult(checks=checks, overall_status=overall, issues=_issues(checks))


def _overall_status(checks: List[ValidationCheck]) -> str:
    statuses = {c.status for c in checks}
    if not checks or statuses == {"NOT_APPLICABLE"}:
        return "NOT_APPLICABLE"
    if "FAIL" in statuses:
        return "FAIL"
    return "PASS"


def _issues(checks: List[ValidationCheck]) -> List[str]:
    return [
        f"{c.name} failed: calculated={c.calculated_value}, reported={c.reported_value}, variance={c.variance}"
        for c in checks if c.status == "FAIL"
    ]


VALIDATORS = {
    "invoice": lambda fields, line_items, periods: validate_invoice(fields, line_items),
    "balance_sheet": lambda fields, line_items, periods: validate_balance_sheet(fields),
    "profit_and_loss": lambda fields, line_items, periods: validate_profit_and_loss(fields),
    "cash_flow_statement": lambda fields, line_items, periods: validate_cash_flow(fields),
}


def run_validation(document_type: str, fields: Dict[str, FieldValue],
                    line_items: List[Dict[str, Any]], periods) -> ValidationResult:
    validator = VALIDATORS.get(document_type)
    if not validator:
        return ValidationResult(checks=[], overall_status="NOT_APPLICABLE", issues=[])
    return validator(fields, line_items, periods)
