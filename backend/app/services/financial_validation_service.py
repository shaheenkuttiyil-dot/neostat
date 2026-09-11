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
RELATIVE_TOLERANCE = settings.VALIDATION_RELATIVE_TOLERANCE

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")

# Summary/rollup rows that sometimes slip through extraction as if they were
# individual line items (e.g. "Aggregated Items", "Total", "Subtotal") - these
# must be excluded before reconciling line items against the subtotal, or
# they double-count and produce a false FAIL.
SUMMARY_ROW_RE = re.compile(
    r"\b(total|subtotal|sub-total|aggregate|aggregated|grand total|net amount)\b",
    re.IGNORECASE,
)


def _filter_summary_rows(line_items):
    """Drops any line item whose description looks like a summary/rollup row
    rather than an actual purchased item, as a safety net independent of
    whether the LLM followed the prompt instruction to exclude these."""
    filtered = []
    for li in line_items:
        desc = str(li.get("description") or "")
        if SUMMARY_ROW_RE.search(desc):
            logger.info("Excluding likely summary row from line items: %r", desc)
            continue
        filtered.append(li)
    return filtered

def _drop_rows_matching_subtotal(line_items, subtotal):
    """A line item whose amount equals the invoice's overall subtotal is
    almost certainly a duplicate rollup row (e.g. a category total mislabeled
    as a product name), not a genuine distinct item - a real line item is a
    fraction of the subtotal, not the whole thing. Guarded to never empty out
    a single-item invoice where this would legitimately be true."""
    if subtotal is None or len(line_items) <= 1:
        return line_items
    tolerance = max(1.0, abs(subtotal) * 0.02)
    filtered = []
    for li in line_items:
        try:
            amt = float(li.get("amount"))
        except (TypeError, ValueError):
            filtered.append(li)
            continue
        if abs(amt - subtotal) <= tolerance:
            logger.info("Excluding line item matching subtotal (likely duplicate rollup): %r amount=%s",
                        li.get("description"), amt)
            continue
        filtered.append(li)
    return filtered if filtered else line_items

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
    allowed = max(TOLERANCE, abs(reported) * RELATIVE_TOLERANCE)
    status = "PASS" if abs(variance) <= allowed else "FAIL"
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
    line_items = _filter_summary_rows(line_items)
    subtotal = _num(fields, "subtotal")
    line_items = _drop_rows_matching_subtotal(line_items, subtotal)
    tax = _num(fields, "tax_amount")
    discount = _num(fields, "discount")
    total = _num(fields, "total_amount")

    calc_total = None
    if subtotal is not None and tax is not None:
        calc_total = subtotal + tax

        if discount is not None:
            calc_total -= discount
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
        # quantity * unit_price ~= amount, per line item (aggregate check).
        # Guard: only include a row if its own qty*unit_price is reasonably
        # close to its own reported amount - this stops a single garbled row
        # (e.g. an HSN/SAC code misread as quantity) from poisoning the whole
        # aggregate with an absurd number, while still surfacing genuinely
        # inconsistent rows as a real FAIL rather than silently hiding them.
        qty_price_total = 0.0
        any_data = False
        excluded_rows = 0
        for li in line_items:
            q, p, a = li.get("quantity"), li.get("unit_price"), li.get("amount")
            if q is None or p is None:
                continue
            try:
                row_calc = float(q) * float(p)
            except (TypeError, ValueError):
                continue
            if a is not None:
                try:
                    row_reported = float(a)
                    if row_reported != 0 and abs(row_calc - row_reported) / abs(row_reported) > 0.5:
                        excluded_rows += 1
                        logger.info(
                            "Excluding implausible line item from quantity_unit_price_check: %r "
                            "(qty*price=%.2f vs row amount=%.2f)", li.get("description"), row_calc, row_reported,
                        )
                        continue
                except (TypeError, ValueError):
                    pass
            qty_price_total += row_calc
            any_data = True
        checks.append(_check(
            "quantity_unit_price_check", "sum(quantity * unit_price)",
            {"computed": qty_price_total if any_data else None, "rows_excluded_as_implausible": excluded_rows},
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
    combined = _num(fields, "total_equity_and_liabilities")

    # Primary accounting equation:
    # Assets = Liabilities + Equity
    if liabilities is not None and equity is not None:
        calc = liabilities + equity

        checks.append(_check(
            "assets_equals_liabilities_plus_equity",
            "total_liabilities + total_equity",
            {
                "total_liabilities": liabilities,
                "total_equity": equity,
            },
            calc,
            assets,
        ))

    # Some balance sheets report a combined
    # "Total Equity and Liabilities" figure.
    if combined is not None:
        checks.append(_check(
            "assets_equals_total_equity_and_liabilities",
            "total_equity_and_liabilities",
            {
                "total_equity_and_liabilities": combined,
            },
            combined,
            assets,
        ))

    overall = _overall_status(checks)

    return ValidationResult(
        checks=checks,
        overall_status=overall,
        issues=_issues(checks),
    )

def validate_profit_and_loss(fields: Dict[str, FieldValue]) -> ValidationResult:
    checks = []

    interest_earned = _num(fields, "interest_earned")
    other_income = _num(fields, "other_income")
    total_income = _num(fields, "total_income")

    interest_expended = _num(fields, "interest_expended")
    operating_expenses = _num(fields, "operating_expenses")
    provisions = _num(fields, "provisions_and_contingencies")
    total_expenditure = _num(fields, "total_expenditure")

    consolidated_profit_before_minority = _num(
        fields, "consolidated_net_profit_before_minority_interest"
    )
    minority_interest = _num(fields, "minority_interest")
    consolidated_profit_attributable = _num(
        fields, "consolidated_net_profit_attributable_to_group"
    )

    current_profit = _num(fields, "current_profit") or consolidated_profit_attributable
    brought_forward_profit = _num(fields, "brought_forward_profit")
    total_available = _num(fields, "total_available_for_appropriation")

    # 1. Total Income
    calc_total_income = None
    if interest_earned is not None and other_income is not None:
        calc_total_income = interest_earned + other_income

    checks.append(_check(
        "total_income_check",
        "interest_earned + other_income",
        {
            "interest_earned": interest_earned,
            "other_income": other_income,
        },
        calc_total_income,
        total_income,
    ))

    # 2. Total Expenditure
    calc_total_expenditure = None
    if (
        interest_expended is not None
        and operating_expenses is not None
        and provisions is not None
    ):
        calc_total_expenditure = (
            interest_expended
            + operating_expenses
            + provisions
        )

    checks.append(_check(
        "total_expenditure_check",
        "interest_expended + operating_expenses + provisions_and_contingencies",
        {
            "interest_expended": interest_expended,
            "operating_expenses": operating_expenses,
            "provisions_and_contingencies": provisions,
        },
        calc_total_expenditure,
        total_expenditure,
    ))

    # 3. Consolidated Net Profit before Minority Interest
    calc_profit_before_minority = None
    if total_income is not None and total_expenditure is not None:
        calc_profit_before_minority = total_income - total_expenditure

    checks.append(_check(
        "consolidated_profit_before_minority_check",
        "total_income - total_expenditure",
        {
            "total_income": total_income,
            "total_expenditure": total_expenditure,
        },
        calc_profit_before_minority,
        consolidated_profit_before_minority,
    ))

    # 4. Consolidated Net Profit attributable to Group
    calc_profit_attributable = None
    if (
        consolidated_profit_before_minority is not None
        and minority_interest is not None
    ):
        calc_profit_attributable = (
            consolidated_profit_before_minority - minority_interest
        )

    checks.append(_check(
        "consolidated_profit_attributable_check",
        "consolidated_net_profit_before_minority_interest - minority_interest",
        {
            "consolidated_net_profit_before_minority_interest":
                consolidated_profit_before_minority,
            "minority_interest": minority_interest,
        },
        calc_profit_attributable,
        consolidated_profit_attributable,
    ))

    # 5. Total Available for Appropriation
    calc_total_available = None
    if current_profit is not None and brought_forward_profit is not None:
        calc_total_available = current_profit + brought_forward_profit

    checks.append(_check(
        "appropriation_check",
        "current_profit + brought_forward_profit",
        {
            "current_profit": current_profit,
            "brought_forward_profit": brought_forward_profit,
        },
        calc_total_available,
        total_available,
    ))

    # Keep the existing basic P&L checks as additional consistency checks.
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
        "gross_profit_check",
        "revenue - cost_of_sales",
        {
            "revenue": revenue,
            "cost_of_sales": cogs,
        },
        calc_gross,
        gross_profit,
    ))

    calc_operating = None
    if gross_profit is not None and opex is not None:
        calc_operating = gross_profit - opex

    checks.append(_check(
        "operating_profit_check",
        "gross_profit - operating_expenses",
        {
            "gross_profit": gross_profit,
            "operating_expenses": opex,
        },
        calc_operating,
        operating_profit,
    ))

    calc_net = None
    if operating_profit is not None and tax is not None:
        calc_net = operating_profit - tax

    checks.append(_check(
        "net_profit_check",
        "operating_profit - tax",
        {
            "operating_profit": operating_profit,
            "tax": tax,
        },
        calc_net,
        net_profit,
    ))

    overall = _overall_status(checks)
    return ValidationResult(
        checks=checks,
        overall_status=overall,
        issues=_issues(checks),
    )
def validate_cash_flow(fields: Dict[str, FieldValue]) -> ValidationResult:
    checks = []
    ocf = _num(fields, "operating_cash_flow")
    icf = _num(fields, "investing_cash_flow")
    fcf = _num(fields, "financing_cash_flow")
    fx = _num(fields, "fx_translation_adjustment")
    net_change = _num(fields, "net_change_in_cash")
    opening = _num(fields, "opening_cash")
    closing = _num(fields, "closing_cash")
    cash_acquired = _num(fields, "cash_acquired")
    amalgamation_adjustment = _num(fields, "amalgamation_adjustment")
    other_cash_adjustments = _num(fields, "other_cash_adjustments")

    calc_net_change = None
    if (
        ocf is not None
        and icf is not None
        and fcf is not None
        and fx is not None
    ):
        calc_net_change = ocf + icf + fcf + fx
    checks.append(_check(
        "net_change_in_cash_check", "operating + investing + financing + fx_adjustment",
        {"operating_cash_flow": ocf, "investing_cash_flow": icf, "financing_cash_flow": fcf, "fx_adjustment": fx},
        calc_net_change, net_change,
    ))

    calc_closing = None

    adjustments = [
        value for value in (
            cash_acquired,
            amalgamation_adjustment,
            other_cash_adjustments,
        )
        if value is not None
    ]

    if opening is not None and net_change is not None:
        calc_closing = opening + net_change + sum(adjustments)
    checks.append(_check(
        "closing_cash_check",
        "opening_cash + net_change_in_cash + applicable_cash_adjustments",
        {
            "opening_cash": opening,
            "net_change_in_cash": net_change,
            "cash_acquired": cash_acquired,
            "amalgamation_adjustment": amalgamation_adjustment,
            "other_cash_adjustments": other_cash_adjustments,
        },
        calc_closing,
        closing,
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
