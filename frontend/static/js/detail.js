const API_PREFIX = "/api/v1";

function renderFields(fields) {
  const container = document.getElementById("fields-container");
  const entries = Object.entries(fields).filter(([k]) => k !== "line_items" && k !== "periods");
  if (!entries.length) { container.innerHTML = "<p>No fields extracted.</p>"; return; }
  container.innerHTML = entries.map(([name, fv]) => {
    const isNull = fv.value === null || fv.value === undefined;
    const evidence = fv.evidence
      ? `<div class="evidence">${fv.evidence.source_text ? '"' + fv.evidence.source_text + '"' : ''} ${fv.evidence.page_number ? '— page ' + fv.evidence.page_number : ''}</div>`
      : "";
    return `<div class="field-row">
      <div class="field-name">${name}</div>
      <div class="field-value-block">
        <div class="field-value ${isNull ? 'is-null' : ''}">${isNull ? 'null (missing)' : fv.value}</div>
        ${evidence}
      </div>
    </div>`;
  }).join("");
}

function renderLineItems(fields) {
  const container = document.getElementById("line-items-container");
  const items = fields.line_items;
  if (!items || !items.length) { container.innerHTML = "<p>No line items.</p>"; return; }
  const cols = Array.from(new Set(items.flatMap(i => Object.keys(i))));
  let html = "<table><thead><tr>" + cols.map(c => `<th>${c}</th>`).join("") + "</tr></thead><tbody>";
  html += items.map(i => "<tr>" + cols.map(c => `<td>${i[c] ?? ""}</td>`).join("") + "</tr>").join("");
  html += "</tbody></table>";
  container.innerHTML = html;
}

function renderValidation(validation) {
  const container = document.getElementById("validation-container");
  if (!validation.checks.length) {
    container.innerHTML = `<span class="status-pill status-NOT_APPLICABLE">NOT_APPLICABLE</span> No validations applicable for this document.`;
    return;
  }
  container.innerHTML = `<p>Overall: <span class="status-pill status-${validation.overall_status}">${validation.overall_status}</span></p>` +
    "<table><thead><tr><th>Check</th><th>Formula</th><th>Calculated</th><th>Reported</th><th>Variance</th><th>Status</th></tr></thead><tbody>" +
    validation.checks.map(c => `<tr>
      <td>${c.name}</td><td>${c.formula}</td>
      <td>${c.calculated_value ?? "—"}</td><td>${c.reported_value ?? "—"}</td><td>${c.variance ?? "—"}</td>
      <td><span class="status-pill status-${c.status}">${c.status}</span></td>
    </tr>`).join("") + "</tbody></table>";
}

async function loadDetail() {
  const summary = document.getElementById("summary-card");
  try {
    const res = await fetch(`${API_PREFIX}/documents/${encodeURIComponent(DOCUMENT_NAME)}`);
    const data = await res.json();
    if (!res.ok) {
      summary.innerHTML = `<div class="error-box">${data?.error?.message || "Document not found."}</div>`;
      return;
    }
    summary.innerHTML = `
      <h2>${data.document_name}</h2>
      <p>Type: <strong>${data.document_type}</strong></p>
      <p>Status: <span class="status-pill status-${data.processing_status}">${data.processing_status}</span></p>
      <p>Processed at: ${new Date(data.processing_metadata.processed_at).toLocaleString()}
         (${data.processing_metadata.processing_time_ms} ms, OCR used: ${data.processing_metadata.ocr_used})</p>
    `;
    renderFields(data.extracted_data);
    renderLineItems(data.extracted_data);
    renderValidation(data.validation);
    document.getElementById("raw-json").textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    summary.innerHTML = `<div class="error-box">Failed to load document.</div>`;
  }
}

document.getElementById("toggle-json-btn").addEventListener("click", () => {
  const pre = document.getElementById("raw-json");
  pre.style.display = pre.style.display === "none" ? "block" : "none";
});

loadDetail();
