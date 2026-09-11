"""
AI-based field & table extraction (Groq).

Given OCR'd/native page text (already layout-reconstructed by ocr_service),
calls Groq's chat-completions API with a strict prompt asking for ONLY JSON
matching the ExtractionPayload contract. Includes:
  - Retry with exponential backoff on transient Groq errors (429/5xx/timeouts)
  - A deterministic regex fallback for invoice_number when the LLM misses it
    (this field is mandatory for invoices and was observed to fail on
    real-world OCR noise like "Cl/25-26/3331")
  - A lightweight heuristic confidence score per field, based on whether the
    LLM's claimed evidence text is actually found in the OCR source text
"""
import json
import re
import time
from typing import Dict, List, Optional

import requests

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.extraction import ExtractionPayload, FieldValue
from app.utils.exceptions import ExtractionError

logger = get_logger(__name__)
settings = get_settings()

# Minimum fields per document type (spec section on Documents in Scope).
# The model is instructed to extract these AT MINIMUM plus anything else visible.
MIN_FIELDS = {
    "invoice": [
        "invoice_number", "invoice_date", "vendor_name", "customer_name",
        "currency", "subtotal", "tax_amount", "discount", "total_amount",
    ],
    "balance_sheet": [
        "total_assets", "total_liabilities", "total_equity",
        "total_equity_and_liabilities", "reporting_period", "currency",
    ],
    "profit_and_loss": [
        "revenue", "cost_of_sales", "gross_profit", "operating_expenses",
        "operating_profit", "tax", "net_profit", "reporting_period", "currency",
    ],
    "cash_flow_statement": [
        "operating_cash_flow", "investing_cash_flow", "financing_cash_flow",
        "opening_cash", "net_change_in_cash", "closing_cash", "reporting_period", "currency",
    ],
}

SYSTEM_PROMPT = """You are a precise financial document data extraction engine.
You extract structured data from OCR/text-layer output of financial documents.
The input text has been layout-reconstructed: words on the same visual row are
on the same line, and "|" marks a likely column boundary (e.g. between a line
item description and its amount). Use this structure to correctly associate
each value with its row and column - do not let unrelated rows bleed together.

Rules you MUST follow:
1. Return ONLY valid JSON. No markdown fences, no commentary, no preamble.
2. Extract EVERY meaningful field, label, date, party name, currency, total, and
   line item visible in the document text - not only the minimum fields listed.
3. For tables (e.g. invoice line items): each row in the source text is one
   line item. Do not merge two rows into one, and do not split one row across
   two line items. Every row with a numeric amount should produce a line item.
   Extract EVERY individual item row, even if there are many (10+) - do not
   summarize, truncate, or sample the list.
3b. NEVER include a summary/rollup/total row as a line item (e.g. any row
   labeled "Total", "Subtotal", "Aggregate", "Aggregated Items", "Grand Total").
   Line items must be individual purchasable items only. If the table has both
   itemized rows and a summary row at the bottom, extract only the itemized
   rows into "line_items" - the summary row's value belongs in the "subtotal"
   or "total_amount" field instead, not in "line_items".
3c. Indian tax invoices commonly have an HSN/SAC code column (a 4-8 digit
   product classification code, e.g. "34029011") between the item description
   and the quantity/rate columns. An HSN/SAC code is NOT a quantity - it does
   not represent how many units were purchased. Put it in an optional
   "hsn_code" key on the line item, never in "quantity". A real quantity for
   a retail/wholesale line item is almost always a small number (typically
   under 1000); if a number in the quantity position is much larger than that
   and looks like a product code, it is an HSN/SAC code, not a quantity.
   Sanity-check every row: quantity * unit_price should approximately equal
   amount - if it doesn't, you likely have a column misaligned; re-examine
   which value is the code, which is the quantity, and which is the rate.
   If you cannot confidently assign quantity/unit_price for a row, leave
   those two fields null rather than guessing - but still include the row
   with its description and amount.
3e. Financial statement line items (balance sheet, P&L, cash flow) often show
   a small "Schedule" or "Note" reference number (e.g. "13", "14", "15", "16")
   immediately between the row label and its actual monetary value - e.g.
   "Interest earned | 13 | 128,552.40" where "13" is just a cross-reference to
   a supporting schedule elsewhere in the report, NOT the field's value. Never
   extract this reference number as the field's value. The real value is the
   monetary amount that follows it (usually a much larger number, often with
   decimals/commas). If a "value" you are about to assign to a financial
   field is a small bare integer (roughly 1-99) with no decimals or comma
   formatting, and a properly-formatted monetary number appears right after
   it on the same row, use that larger monetary number instead - the small
   integer was a schedule/note reference, not the amount.
4. If a value is not present or not legible, set it to null. NEVER invent,
   guess, or infer a value that is not directly supported by the text.
5. Identifiers such as invoice numbers may contain OCR noise (e.g. a capital
   "I" misread as lowercase "l" or "1"). Extract the field's raw value as best
   found in the text - do not silently normalize or correct it. If a token
   that looks like it could be an identifier (mixed letters/digits/slashes
   near a label like "Invoice No", "Invoice #", "Bill No") appears anywhere in
   the text, prefer extracting it over returning null.
6. For each scalar field, provide an evidence object with the exact short
   source text snippet it came from (copy it verbatim from the input) and the
   page number it appeared on.
7. Comparative-period tables: many financial statements show TWO adjacent
   numeric columns for the same row - e.g. "Year ended 31-Mar-20" and
   "Year ended 31-Mar-19", or "As at March 31, 2020" and the prior year. The
   "fields" object must ALWAYS contain the CURRENT/MOST RECENT reporting
   period's column (normally the first/leftmost numeric column, and the one
   matching the period stated in the document header/"reporting_period"),
   never the prior-year comparative column. This is a common source of error:
   do not mix columns - pick ONE column (the current period) and read every
   field from that same column consistently.
   Self-check before finalizing: for any row you extracted labeled "Total"
   (e.g. total income, total expenditure), verify it equals the sum of the
   individual component rows above it, using values from the SAME column. If
   your extracted "Total" does not equal the sum of the components you
   extracted for that same row group, you have likely picked mismatched
   columns for different rows - go back and re-read every value in that
   section from the single correct (current-period) column.
   If the document shows multiple periods, still list the period labels in
   "periods", but "fields" itself must only reflect the current period.
7b. Consolidated financial statements with a minority (non-controlling)
   interest typically show a waterfall of THREE distinct profit figures in
   this order - do not conflate them:
   (a) the profit figure BEFORE any minority interest deduction (often
       labeled just "Net profit for the year"),
   (b) the minority interest amount being deducted (labeled "Less: Minority
       interest" or similar), and
   (c) the final consolidated profit AFTER that deduction, i.e. (a) minus (b)
       (often labeled "Consolidated profit for the year" or "...attributable
       to the group"/"...attributable to owners").
   If you extract a field intended to represent "before minority interest",
   it must hold the SAME value as the plain "net profit" figure (a) - never
   the post-deduction figure (c). If you extract a field intended to
   represent the profit "attributable to the group"/"after minority
   interest", it must hold value (c), and must equal (a) minus (b) - verify
   this arithmetic before finalizing.
8. Numbers must be plain numbers (no currency symbols, no thousand separators)
   in "value". A number in parentheses, e.g. "(1,200)", means -1200.
9. Output must match this exact JSON shape:
{
  "fields": {
    "<field_name>": {"value": <value or null>, "evidence": {"source_text": "...", "page_number": <int or null>}}
  },
  "line_items": [ { <object with whatever columns are visible, e.g. description, quantity, unit_price, amount> } ],
  "periods": [ "<period label>", ... ] or null
}
"""

# Fallback pattern for invoice-number-like tokens near a label, tolerant of
# common OCR confusions ("I" <-> "l"/"1", "O" <-> "0"). Used only when the LLM
# itself returns null for invoice_number, as a deterministic safety net.
INVOICE_NUMBER_LABEL_RE = re.compile(
    r"(?:invoice|inv|bill|ci)\s*(?:no\.?|number|#)\s*[:\-]?\s*"
    r"([A-Za-z0-9][A-Za-z0-9/\-]{3,})",
    re.IGNORECASE,
)


def _build_user_prompt(document_type: str, pages_text: List[str]) -> str:
    min_fields = MIN_FIELDS.get(document_type, [])
    pages_block = "\n\n".join(
        f"--- PAGE {i + 1} ---\n{text}" for i, text in enumerate(pages_text)
    )
    return f"""Document type: {document_type}
At minimum, look for these fields (extract ALL other visible fields too): {', '.join(min_fields)}

Document text (layout-reconstructed via OCR/native parsing; "|" = likely column boundary,
may contain minor OCR noise):

{pages_block}

Return the JSON object now."""


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    return text


def _call_groq(system_prompt: str, user_prompt: str) -> str:
    """Groq's API is OpenAI-compatible (chat/completions shape). Retries with
    exponential backoff on 429/5xx/timeouts so a transient Groq blip doesn't
    fail the whole document."""
    if not settings.GROQ_API_KEY:
        raise ExtractionError("GROQ_API_KEY is not configured on the server.")

    last_exc: Optional[Exception] = None
    for attempt in range(settings.LLM_MAX_RETRIES):
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                    "content-type": "application/json",
                },
                json={
                    "model": settings.GROQ_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0,
                    "max_completion_tokens": 3000,
                    "reasoning_effort": "low",
                    "include_reasoning": False,
                    "response_format": {
                        "type": "json_object"
                    },
                },
                timeout=90,
            )
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.HTTPError(f"Retryable Groq error: {resp.status_code} {resp.text[:200]}")
            if resp.status_code != 200:
                logger.error("Groq API error %s: %s", resp.status_code, resp.text[:500])
                raise ExtractionError(f"LLM provider returned an error ({resp.status_code}).")
            data = resp.json()
            choice = data["choices"][0]
            content = choice["message"]["content"]
            if not content:
                finish_reason = choice.get("finish_reason", "unknown")
                logger.error(
                    "Groq returned empty content (finish_reason=%s). Full response: %s",
                    finish_reason, json.dumps(data)[:1000],
                )
                raise ExtractionError(
                    f"LLM returned an empty response (finish_reason={finish_reason}). "
                    "This usually means the token limit was hit before the model finished."
                )
            return content

        except ExtractionError:
            raise
        except (requests.HTTPError, requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc
            wait = 2 ** attempt
            logger.warning("Groq call failed (attempt %d/%d): %s - retrying in %ds",
                            attempt + 1, settings.LLM_MAX_RETRIES, exc, wait)
            time.sleep(wait)

    logger.error("Groq call failed after %d attempts: %s", settings.LLM_MAX_RETRIES, last_exc)
    raise ExtractionError("LLM provider (Groq) was unavailable after multiple retries.")


def _regex_fallback_invoice_number(pages_text: List[str]) -> Optional[Dict]:
    for page_num, text in enumerate(pages_text, start=1):
        for match in INVOICE_NUMBER_LABEL_RE.finditer(text):
            candidate = match.group(1)
            if any(ch.isdigit() for ch in candidate):
                return {
                    "value": candidate,
                    "evidence": {"source_text": match.group(0).strip(), "page_number": page_num},
                }
    return None


def _apply_heuristic_confidence(payload: ExtractionPayload, pages_text: List[str]) -> None:
    """Confidence isn't mandatory, but a null-only confidence field is weaker
    than a simple grounding check: does the evidence snippet the LLM claimed
    actually appear in the OCR text it was given? This won't catch every
    error, but it flags likely-hallucinated or misread values for review."""
    full_text = "\n".join(pages_text)
    for field in payload.fields.values():
        if field.value is None:
            field.confidence = None
            continue
        if field.evidence and field.evidence.source_text:
            field.confidence = 0.9 if field.evidence.source_text.strip() in full_text else 0.4
        else:
            field.confidence = 0.5  # value present but no grounding evidence supplied


def extract_fields(document_type: str, pages_text: List[str]) -> ExtractionPayload:
    user_prompt = _build_user_prompt(document_type, pages_text)

    logger.info("Calling Groq for extraction (document_type=%s, pages=%d)",
                document_type, len(pages_text))

    raw = _call_groq(SYSTEM_PROMPT, user_prompt)
    cleaned = _strip_json_fences(raw)

    try:
        parsed: Dict = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse LLM JSON output: %s | raw=%s", exc, cleaned[:500])
        raise ExtractionError("LLM returned malformed JSON during extraction.") from exc

    try:
        payload = ExtractionPayload(**parsed)
    except Exception as exc:
        logger.error("LLM output did not match extraction schema: %s", exc)
        raise ExtractionError("LLM output did not match the expected extraction schema.") from exc

    # Deterministic safety net: invoice_number is mandatory and was observed
    # to be missed by the LLM on noisy OCR text.
    if document_type == "invoice":
        existing = payload.fields.get("invoice_number")
        if existing is None or existing.value in (None, ""):
            fallback = _regex_fallback_invoice_number(pages_text)
            if fallback:
                logger.info("invoice_number recovered via regex fallback: %s", fallback["value"])
                payload.fields["invoice_number"] = FieldValue(**fallback)

    if document_type == "invoice" and payload.line_items:
        from app.services.financial_validation_service import _filter_summary_rows
        payload.line_items = _filter_summary_rows(payload.line_items)

    _apply_heuristic_confidence(payload, pages_text)

    return payload
