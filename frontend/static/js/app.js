const API_PREFIX = "/api/v1";

const TYPE_LABELS = {
  invoice: "Invoice",
  balance_sheet: "Balance Sheet",
  profit_and_loss: "Profit & Loss",
  cash_flow_statement: "Cash Flow Statement",
};

/* ---------- Stats cards ---------- */
async function loadStats() {
  try {
    const res = await fetch(`${API_PREFIX}/documents/stats`);
    if (!res.ok) return;
    const s = await res.json();
    document.getElementById("stat-total").textContent = s.total_documents ?? 0;
    document.getElementById("stat-passed").textContent = s.passed ?? 0;
    document.getElementById("stat-failed").textContent = s.failed ?? 0;
    document.getElementById("stat-confidence").textContent =
      s.avg_confidence != null ? `${Math.round(s.avg_confidence * 100)}%` : "—";
  } catch (e) {
    /* leave defaults on error */
  }
}

/* ---------- Documents table ---------- */
async function loadDocuments() {
  const tbody = document.getElementById("doc-table-body");
  const emptyState = document.getElementById("empty-state");
  const docsCard = document.getElementById("docs-card");
  try {
    const res = await fetch(`${API_PREFIX}/documents`);
    const docs = await res.json();
    if (!docs.length) {
      emptyState.style.display = "flex";
      docsCard.style.display = "none";
      return;
    }
    emptyState.style.display = "none";
    docsCard.style.display = "block";
    tbody.innerHTML = docs.map(d => `
      <tr>
        <td><a href="/document/${encodeURIComponent(d.document_name)}">${d.document_name}</a></td>
        <td>${TYPE_LABELS[d.document_type] || d.document_type}</td>
        <td><span class="status-pill status-${d.processing_status}">${d.processing_status}</span></td>
        <td>${new Date(d.processed_at).toLocaleString()}</td>
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4">Failed to load documents.</td></tr>`;
    emptyState.style.display = "none";
    docsCard.style.display = "block";
  }
}

/* ---------- Upload modal ---------- */
const modal = document.getElementById("upload-modal");
function openModal() { modal.style.display = "flex"; }
function closeModal() {
  modal.style.display = "none";
  document.getElementById("upload-status").innerHTML = "";
  document.getElementById("upload-form").reset();
}
document.getElementById("btn-new-document").addEventListener("click", openModal);
document.getElementById("nav-new-document").addEventListener("click", openModal);
document.getElementById("btn-cancel-upload").addEventListener("click", closeModal);
modal.addEventListener("click", e => { if (e.target === modal) closeModal(); });

document.getElementById("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fileInput = document.getElementById("file");
  const docType = document.getElementById("document_type").value;
  const statusDiv = document.getElementById("upload-status");
  const submitBtn = document.getElementById("submit-btn");

  if (!fileInput.files.length) return;

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  formData.append("document_type", docType);

  submitBtn.disabled = true;
  statusDiv.innerHTML = `<div class="info-box">Processing… this may take a few seconds.</div>`;

  try {
    const res = await fetch(`${API_PREFIX}/documents/process`, { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) {
      const msg = data?.error?.message || data?.detail?.error?.message || "Processing failed.";
      statusDiv.innerHTML = `<div class="error-box">${msg}</div>`;
    } else {
      statusDiv.innerHTML = `<div class="success-box">Processed: ${data.document_name} — ${data.processing_status}</div>`;
      loadDocuments();
      loadStats();
      setTimeout(closeModal, 1500);
    }
  } catch (err) {
    statusDiv.innerHTML = `<div class="error-box">Request failed: ${err}</div>`;
  } finally {
    submitBtn.disabled = false;
  }
});

loadDocuments();
loadStats();