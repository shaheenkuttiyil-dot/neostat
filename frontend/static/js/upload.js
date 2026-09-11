const API_PREFIX = "/api/v1";

const typeGrid = document.getElementById("typeGrid");
const typeSelect = document.getElementById("document_type");

typeGrid.addEventListener("click", (e) => {
  const card = e.target.closest(".type-card");
  if (!card) return;
  typeGrid.querySelectorAll(".type-card").forEach(c => c.classList.remove("selected"));
  card.classList.add("selected");
  typeSelect.value = card.dataset.value;
});

const uploadArea = document.getElementById("uploadArea");
const submitBtn = document.getElementById("submit-btn");
let selectedFile = null;

function updateCta() {
  submitBtn.disabled = !selectedFile;
  submitBtn.classList.toggle("ready", !!selectedFile);
}

function renderFile(file) {
  selectedFile = file;
  const sizeKb = (file.size / 1024).toFixed(0);
  uploadArea.innerHTML = `
    <div class="file-chip">
      <svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>
      <div>
        <p class="file-name">${file.name}</p>
        <p class="file-meta">${sizeKb} KB</p>
      </div>
      <button type="button" class="file-remove" id="removeFile">Remove</button>
    </div>`;
  document.getElementById("removeFile").addEventListener("click", resetDropzone);
  updateCta();
}

function resetDropzone() {
  selectedFile = null;
  uploadArea.innerHTML = `
    <label class="dropzone" id="dropzone">
      <svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4"/><path d="m6 10 6-6 6 6"/><path d="M4 20h16"/></svg>
      <p class="drop-title">Drop a document here, or click to browse</p>
      <p class="drop-sub">PDF, JPG, or PNG &middot; up to 3 pages</p>
      <input type="file" id="file" accept=".pdf,.jpg,.jpeg,.png" required>
    </label>`;
  bindDropzone();
  updateCta();
}

function bindDropzone() {
  const dz = document.getElementById("dropzone");
  const input = document.getElementById("file");
  input.addEventListener("change", (e) => { if (e.target.files[0]) renderFile(e.target.files[0]); });
  dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("drag"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
  dz.addEventListener("drop", (e) => {
    e.preventDefault(); dz.classList.remove("drag");
    if (e.dataTransfer.files[0]) renderFile(e.dataTransfer.files[0]);
  });
}
bindDropzone();
updateCta();

document.getElementById("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!selectedFile) return;
  const statusDiv = document.getElementById("upload-status");
  const formData = new FormData();
  formData.append("file", selectedFile);
  formData.append("document_type", typeSelect.value);

  submitBtn.disabled = true;
  submitBtn.textContent = "Processing…";
  statusDiv.innerHTML = `<div>Processing… this may take a few seconds.</div>`;

  try {
    const res = await fetch(`${API_PREFIX}/documents/process`, { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) {
      const msg = data?.error?.message || data?.detail?.error?.message || "Processing failed.";
      statusDiv.innerHTML = `<div class="error-box">${msg}</div>`;
    } else {
      showResultPanel(data);
      resetDropzone();
    }
  } catch (err) {
    statusDiv.innerHTML = `<div class="error-box">Request failed: ${err}</div>`;
  }
  submitBtn.disabled = !selectedFile;
  submitBtn.textContent = "Extract & Validate";
});

/* ---------- Upload result panel ---------- */
function confidencePct(c) {
  return c === null || c === undefined ? "—" : Math.round(c * 100) + "%";
}

function showResultPanel(data) {
  const statusDiv = document.getElementById("upload-status");
  const ok = data.processing_status === "PASS";
  statusDiv.innerHTML = `
    <div class="result-card ${ok ? "result-pass" : "result-fail"}">
      <div class="result-main">
        <span class="status-pill status-${data.processing_status}">${data.processing_status}</span>
        <div class="result-info">
          <p class="result-name">${data.document_name}</p>
          <p class="result-sub">${TYPE_LABELS[typeSelect.value] || typeSelect.value} &middot; Confidence ${confidencePct(data.overall_confidence)}</p>
        </div>
      </div>
      <button type="button" class="ghost-btn" id="btn-view-details">Details</button>
    </div>`;
  document.getElementById("btn-view-details").addEventListener("click", () => openDetailsModal(data.document_name));
}

/* ---------- Details modal ---------- */
const TYPE_LABELS = {
  invoice: "Invoice",
  balance_sheet: "Balance Sheet",
  profit_and_loss: "Profit & Loss",
  cash_flow_statement: "Cash Flow Statement",
};

function closeDetailsModal() {
  const overlay = document.getElementById("details-modal");
  if (overlay) overlay.style.display = "none";
}

function modalFieldsHtml(fields) {
  const entries = Object.entries(fields).filter(([k]) => k !== "line_items" && k !== "periods");
  if (!entries.length) return "<p>No fields extracted.</p>";
  return entries.map(([name, fv]) => {
    const isNull = fv.value === null || fv.value === undefined;
    return `<div class="field-row">
      <div class="field-name">${name}</div>
      <div class="field-value ${isNull ? "is-null" : ""}">${isNull ? "null (missing)" : fv.value}</div>
    </div>`;
  }).join("");
}

function modalLineItemsHtml(fields) {
  const items = fields.line_items;
  if (!items || !items.length) return "<p>No line items.</p>";
  const cols = Array.from(new Set(items.flatMap(i => Object.keys(i))));
  let html = "<table><thead><tr>" + cols.map(c => `<th>${c}</th>`).join("") + "</tr></thead><tbody>";
  html += items.map(i => "<tr>" + cols.map(c => `<td>${i[c] ?? ""}</td>`).join("") + "</tr>").join("");
  return html + "</tbody></table>";
}

function modalValidationHtml(validation) {
  if (!validation.checks || !validation.checks.length) {
    return `<span class="status-pill status-NOT_APPLICABLE">NOT_APPLICABLE</span> No validations applicable for this document.`;
  }
  return `<p>Overall: <span class="status-pill status-${validation.overall_status}">${validation.overall_status}</span></p>` +
    "<table><thead><tr><th>Check</th><th>Formula</th><th>Calculated</th><th>Reported</th><th>Variance</th><th>Status</th></tr></thead><tbody>" +
    validation.checks.map(c => `<tr>
      <td>${c.name}</td><td>${c.formula}</td>
      <td>${c.calculated_value ?? "—"}</td><td>${c.reported_value ?? "—"}</td><td>${c.variance ?? "—"}</td>
      <td><span class="status-pill status-${c.status}">${c.status}</span></td>
    </tr>`).join("") + "</tbody></table>";
}

async function openDetailsModal(name) {
  let overlay = document.getElementById("details-modal");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "details-modal";
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal-card">
        <div class="modal-head">
          <h2>Document details</h2>
          <button type="button" class="modal-close" aria-label="Close">&times;</button>
        </div>
        <div class="modal-body">Loading…</div>
        <div class="modal-foot">
          <a class="ghost-btn" id="modal-full-page" href="#" target="_blank" rel="noopener">Open full page</a>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    overlay.addEventListener("click", e => { if (e.target === overlay) closeDetailsModal(); });
    overlay.querySelector(".modal-close").addEventListener("click", closeDetailsModal);
  }
  overlay.style.display = "flex";
  overlay.querySelector(".modal-body").textContent = "Loading…";
  overlay.querySelector(".modal-head h2").textContent = "Document details";
  overlay.querySelector("#modal-full-page").href = `/document/${encodeURIComponent(name)}`;

  try {
    const res = await fetch(`${API_PREFIX}/documents/${encodeURIComponent(name)}`);
    const data = await res.json();
    if (!res.ok) {
      overlay.querySelector(".modal-body").innerHTML =
        `<div class="error-box">${data?.error?.message || "Document not found."}</div>`;
      return;
    }
    overlay.querySelector(".modal-head h2").textContent = data.document_name;
    const meta = data.processing_metadata || {};
    overlay.querySelector(".modal-body").innerHTML = `
      <div class="modal-summary">
        <p>Type: <strong>${data.document_type}</strong></p>
        <p>Status: <span class="status-pill status-${data.processing_status}">${data.processing_status}</span></p>
        <p>Processed at: ${meta.processed_at ? new Date(meta.processed_at).toLocaleString() : "—"}
           ${meta.processing_time_ms ? `(${meta.processing_time_ms} ms)` : ""}</p>
      </div>
      <h3>Extracted fields</h3>${modalFieldsHtml(data.extracted_data || {})}
      <h3>Line items</h3>${modalLineItemsHtml(data.extracted_data || {})}
      <h3>Financial validation</h3>${modalValidationHtml(data.validation || { checks: [] })}`;
  } catch (e) {
    overlay.querySelector(".modal-body").innerHTML = `<div class="error-box">Failed to load document.</div>`;
  }
}

document.addEventListener("keydown", e => { if (e.key === "Escape") closeDetailsModal(); });
