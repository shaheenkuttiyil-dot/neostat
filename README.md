# Document Intelligence Extraction, Validation & API Platform

An end-to-end service that accepts financial documents (invoices, balance sheets,
profit & loss statements, cash flow statements) as PDF/JPG/PNG, extracts all
meaningful fields and line items using OCR + an LLM, runs financial-calculation
validations, persists results, and exposes them through REST APIs and a dashboard.

## 1. Solution Overview & Architecture

```
Document Upload
      ↓
Document Validation (type / integrity / page limit ≤ 3)
      ↓
Text Extraction (native PDF text layer) / OCR (Tesseract, for scanned pages & images)
      ↓
AI-based Field & Table Extraction (LLM, strict JSON-schema prompt per document type)
      ↓
Financial Calculation Validation (PASS / FAIL / NOT_APPLICABLE)
      ↓
Persist Result (SQLite)
      ↓
Dashboard + REST API Response
```

See `docs/architecture.png` for the diagram.

Layered design (backend/app):
- `services/document_validation_service.py` — input-control layer only (file type, corruption, page count)
- `services/ocr_service.py` — native PDF text extraction with Tesseract OCR fallback for scanned pages/images
- `services/extraction_service.py` — LLM-based structured extraction via Groq's OpenAI-compatible chat-completions API
- `services/financial_validation_service.py` — per-document-type calculation checks
- `services/document_service.py` — orchestrates the full pipeline end-to-end
- `repositories/document_repository.py` — persistence, isolated from business logic
- `api/routes/documents.py` — REST endpoints
- `schemas/` — Pydantic contracts for requests/responses (structured, machine-readable)

## 2. Technology Stack & Reasoning

| Layer | Choice | Why |
|---|---|---|
| API framework | FastAPI | Free built-in Swagger/OpenAPI docs, native Pydantic validation, async support |
| OCR | Tesseract (pytesseract) + PyMuPDF | Free, open-source, no API quota risk during a timed assessment |
| Native PDF parsing | PyMuPDF (fitz) | Fast text-layer extraction + page rasterization for OCR fallback in one library |
| LLM extraction | Groq (Llama 3.3 70B) | Fast inference, generous free tier, OpenAI-compatible API |
| Database | SQLite | Zero-setup, file-based, sufficient for assessment scope; swappable via `DATABASE_URL` |
| Frontend | Plain HTML/CSS/JS + Jinja2 (served by FastAPI) | No separate frontend stack required per spec; fastest to build and deploy as one service |
| Deployment | Render (free tier) | One process serves both API and frontend |

## 3. Local Setup

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# System dependency: Tesseract OCR must be installed on the host
# Debian/Ubuntu: sudo apt-get install tesseract-ocr
# macOS: brew install tesseract

cp ../.env.example ../.env   # fill in GROQ_API_KEY
uvicorn app.main:app --reload --port 8000
```

Visit:
- Frontend dashboard: http://localhost:8000/
- Swagger/OpenAPI docs: http://localhost:8000/docs
- Health check: http://localhost:8000/api/v1/health

Run tests:
```bash
cd backend
pytest tests/ -v
```

## 4. Environment Variables

See `.env.example`. Key variables:
- `DATABASE_URL` — SQLite by default
- `GROQ_API_KEY` — required for extraction to work
- `GROQ_MODEL` — defaults to `llama-3.3-70b-versatile`; check Groq's console for current supported models
- `MAX_PAGES`, `MAX_FILE_SIZE_MB` — input constraints
- `VALIDATION_TOLERANCE` — absolute currency-unit tolerance for PASS/FAIL
- `VALIDATION_RELATIVE_TOLERANCE` — relative tolerance (fraction of reported value); a check passes if within *either* the absolute or relative tolerance, whichever is larger

No secrets are committed to source control (`.gitignore` excludes `.env`).

## 5. Deployed URLs

- Frontend: `https://neostat-shaheen.onrender.com/`
- Backend API base: `https://neostat-shaheen.onrender.com/api/v1`
- Swagger/OpenAPI: `https://neostat-shaheen.onrender.com/docs`
- Public GitHub repository: `https://github.com/shaheenkuttiyil-dot/neostat`

## 6. API Reference & Examples

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/documents/process` | Upload and process a PDF/JPG/PNG |
| GET | `/api/v1/documents/{document_name}` | Latest structured result by document name |
| GET | `/api/v1/documents` | List processed documents (dashboard) |
| GET | `/api/v1/health` | Health check |

**POST /api/v1/documents/process**
```bash
curl -X POST https://neostat-shaheen.onrender.com/api/v1/documents/process \
  -F "file=@sample_invoice.pdf" \
  -F "document_type=invoice"
```

**GET by document name**
```bash
curl https://neostat-shaheen.onrender.com/api/v1/documents/sample_invoice.pdf
```

**List processed documents**
```bash
curl https://neostat-shaheen.onrender.com/api/v1/documents
```

Sample full responses: see `sample_outputs/` (one JSON per document type —
invoice, balance sheet, profit & loss, cash flow statement).

## 7. OCR / LLM Services Used

- OCR: Tesseract (open-source, local) via `pytesseract`, with PyMuPDF for native
  PDF text-layer extraction. Scanned pages/images go through layout-aware OCR
  (word bounding boxes reconstructed into rows/columns - see section 11)
  rather than plain flattened text extraction.
- LLM: Groq (`llama-3.3-70b-versatile` by default) for field/table extraction,
  called via its OpenAI-compatible chat-completions API, with retry/backoff
  on transient failures.

## 8. Confidence Scoring

Implemented as a lightweight heuristic, not a model-native score: each
extracted field's `confidence` is set based on whether the LLM's claimed
evidence snippet is actually found verbatim in the OCR/native text it was
given (0.9 if grounded, 0.4 if the snippet doesn't match the source, 0.5 if no
evidence was supplied at all, `null` if the value itself is null). This won't
catch every extraction error, but it flags likely-hallucinated or misread
values for review rather than presenting every field as equally trustworthy.
A document-level `overall_confidence` is computed as the average of the
per-field confidence scores that were actually set; fields with no confidence
score are excluded from the average rather than counted as 0. A stronger
version would combine this with OCR-engine word-level confidence and
cross-field consistency checks (see section 12).

## 9. Financial Validation Rules & Tolerance

Implemented per document type in `services/financial_validation_service.py`:
- **Invoice**: `subtotal + tax_amount - discount ≈ total_amount`; line-item
  reconciliation against subtotal; quantity × unit price check; cash/change
  check where present; GSTIN/tax-ID format validation (flags OCR-corrupted
  tax IDs rather than silently trusting them).
- **Balance Sheet**: `total_liabilities + total_equity ≈ total_assets`.
- **Profit & Loss**: `revenue - cost_of_sales ≈ gross_profit`; `gross_profit - operating_expenses ≈ operating_profit`; `operating_profit - tax ≈ net_profit`. Note: these checks are `NOT_APPLICABLE` for bank/financial-institution-format P&L statements (e.g. "Interest Earned / Interest Expended" structured statements), which don't use a revenue/COGS/gross-profit model at all — the extractor correctly returns `null` rather than inventing values for concepts that don't exist in that document's format.
- **Cash Flow Statement**: `operating + investing + financing + fx_adjustment ≈ net_change_in_cash`; `opening_cash + net_change_in_cash ≈ closing_cash`. If `fx_translation_adjustment` isn't found in the document, it defaults to 0 rather than being skipped — but the check's `operands` include an `fx_adjustment_source` flag (`extracted` vs `assumed_zero`) so a FAIL can be distinguished from a genuine reconciliation problem versus a missing FX line.

Tolerance: a check passes if the variance is within *either* `VALIDATION_TOLERANCE`
(absolute, default 1.0 currency unit) *or* `VALIDATION_RELATIVE_TOLERANCE`
(default 0.1% of the reported value), whichever allowance is larger. An
absolute-only tolerance is meaningless for figures reported in
thousands/crores, where a genuine single-digit OCR misread produces a
variance of a few thousand that is proportionally tiny but would dwarf a
small absolute unit.
Any check where a required input is missing returns `NOT_APPLICABLE`, never an assumed value.
Note: Pydantic guarantees the *shape* of extraction output is correct; it does
not guarantee the *values* are correct. Financial validation is the layer that
actually catches wrong values, by cross-checking them against each other -
that's why it exists as a separate, deterministic step rather than trusting
the LLM's output directly.

## 10. Database / Persistence

SQLite (`data/documents.db`), one row per processing run. `GET /documents/{name}`
returns the most recent row for that document name (ordered by `created_at`);
prior versions are retained but not exposed via the API (optional per spec).

## 11. Table & Layout Reconstruction

OCR on scanned images/PDFs uses `pytesseract.image_to_data` (word-level
bounding boxes) rather than plain `image_to_string`. Words are clustered into
rows by vertical position, then a `|` column-boundary marker is inserted
wherever the horizontal gap between adjacent words exceeds a threshold. This
directly addresses the main failure mode of OCR-to-LLM pipelines: a flattened
text blob loses which amount belongs to which line item. The LLM prompt
explicitly explains this row/column convention and is instructed not to merge
or split rows. This is a heuristic (gap-threshold clustering), not true table
structure detection - see section 12 for what a more rigorous approach would use.

Identifier fields (like `invoice_number`) get an additional deterministic
regex fallback: if the LLM returns null for `invoice_number`, the raw OCR
text is scanned for a label pattern (e.g. "Invoice No:", "Invoice #") followed
by an alphanumeric token containing at least one digit. This catches cases
where OCR noise (e.g. a capital "I" misread as lowercase "l") makes the token
look unfamiliar enough that the LLM skips it, since mandatory identifier
fields shouldn't be lost to a single misread character.

## 12. Known Limitations

Extraction quality:
- Table reconstruction is gap-threshold heuristic, not true layout/structure
  detection - multi-page tables (a table continuing from page 1 to page 2) or
  documents with dense multi-column layouts can still confuse row/column
  association.
- Evidence is text-based (`source_text` + `page_number`), not bounding-box
  based - there's no coordinate showing exactly where on the page a value
  came from, which would let a UI highlight it directly on the document image.
- Confidence scoring is a grounding heuristic (see section 8), not a
  calibrated probability.
- No systematic completeness check beyond financial validation - the
  extracted JSON can look well-formed while still missing a row the LLM
  simply didn't surface.
- The financial validation formulas assume a standard commercial company's
  P&L structure (revenue → COGS → gross profit → operating profit → net
  profit). Bank/NBFC-format P&L statements (interest income/expense based)
  don't fit this model and will correctly show `NOT_APPLICABLE` for all P&L
  checks rather than a false PASS/FAIL - a production system would add a
  second validator path for that statement format.

Document handling:
- Document type is supplied by the caller/UI, not auto-classified. A
  production system would run a classification step first (invoice vs.
  balance sheet vs. P&L vs. cash flow vs. unsupported) rather than trusting
  the selection.
- Orientation correction (`image_to_osd`) is heuristic and not guaranteed for
  every scan quality/rotation combination.
- Whole-page OCR text is sent to the LLM in one prompt; very large/dense
  documents could approach context limits or add unnecessary latency and
  token cost. A production system would chunk or pre-filter to relevant
  regions before the LLM call.

Reliability & Performance:
- Retry/backoff is implemented for Groq only (exponential backoff on
  429/5xx/timeout, `LLM_MAX_RETRIES` configurable). There is no fallback to a
  second LLM provider if Groq itself is down.
- Processing is synchronous - a request blocks for the full
  validate→OCR→extract→validate-financials pipeline. Locally this takes
  ~8-12s; on the free-tier Render deployment it can take 90-140s, because
  Tesseract OCR is CPU-bound and free-tier instances are heavily
  CPU-throttled (~0.1 vCPU) - a hosting constraint, not an algorithmic one.
  Per-stage timing is logged (`TIMING ocr_ms=... llm_extraction_ms=...`) to
  make this measurable rather than anecdotal. No background job
  queue/polling.
- No idempotency - re-uploading the same file creates a new processing
  record rather than detecting and reusing an existing result.
- No caching of previously processed documents.

Security & production readiness:
- No authentication/authorization - the API is open by design for this
  assessment; a public deployment would need API keys/OAuth before going live
  for real financial documents.
- No rate limiting on the public endpoints.
- File validation covers type/size/corruption but not deeper resource-
  exhaustion protection (e.g. decompression bombs, adversarially crafted PDFs).
- SQLite is fine for this scope but not for concurrent production writes -
  would move to managed Postgres.
- No object storage - uploaded files aren't currently persisted separately
  from the extraction result; a production system would store the original
  file (e.g. S3-compatible storage) for reprocessing/audit.
- No documented data retention/deletion policy - relevant given these are
  financial documents that may contain sensitive company/customer data.

Testing:
- 12 automated tests cover file validation, extraction schema/fallback logic,
  OCR layout reconstruction, and core API flows - but there's no systematic
  OCR test matrix (rotated/skewed scans, poor-quality scans, multi-page
  documents) or financial-validation edge-case matrix (missing tax, rounding,
  negative values) beyond what's covered here. No regression dataset to catch
  a fix for one document type breaking another.

## 13. What I'd Change for Production

- Add authentication (API keys / OAuth) and per-tenant data isolation.
- Move to PostgreSQL with proper migrations (Alembic) and object storage (S3-compatible) for original files.
- Add async/background job processing (a job ID + worker + status polling) instead of synchronous request-blocking processing.
- Move OCR off CPU-constrained free-tier hosting (or offload to a cloud OCR API) to remove the throttling-driven latency seen on Render's free tier.
- Replace gap-threshold table reconstruction with a proper layout/table-structure model, and store bounding-box coordinates so evidence can be highlighted directly on the source document image in the UI.
- Add automatic document-type classification as a first pipeline stage.
- Add a second LLM provider as an automatic fallback if Groq is unavailable.
- Add rate limiting and stronger adversarial-file protections.
- Build out a systematic OCR test matrix and a financial-validation edge-case test matrix, plus a regression dataset.
- Add a bank/NBFC-format P&L validator path (Total Income − Total Expenditure ≈ Net Profit) alongside the existing commercial-company formula, selected based on which fields the document actually populates.
- Redesign the frontend around validation status first (pass/fail/needs-review at a glance) with document preview + evidence highlighting, keeping raw JSON as a secondary technical view.

## 14. AI Coding Assistants Used

This solution was built with the assistance of Claude (Anthropic), used for:
scaffolding the project structure, writing the FastAPI services (validation,
OCR, extraction, financial validation), the frontend dashboard, tests, and this
README. All generated code was reviewed and adjusted for correctness.
