const API_PREFIX = "/api/v1";

async function loadDocuments() {
  const tbody = document.getElementById("doc-table-body");
  try {
    const res = await fetch(`${API_PREFIX}/documents`);
    const docs = await res.json();
    if (!docs.length) {
      tbody.innerHTML = `<tr><td colspan="4">No documents processed yet.</td></tr>`;
      return;
    }
    tbody.innerHTML = docs.map(d => `
      <tr onclick="window.location.href='/document/${encodeURIComponent(d.document_name)}'">
        <td>${d.document_name}</td>
        <td>${d.document_type}</td>
        <td><span class="status-pill status-${d.processing_status}">${d.processing_status}</span></td>
        <td>${new Date(d.processed_at).toLocaleString()}</td>
      </tr>
    `).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4">Failed to load documents.</td></tr>`;
  }
}

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
  statusDiv.innerHTML = `<div>Processing… this may take a few seconds.</div>`;

  try {
    const res = await fetch(`${API_PREFIX}/documents/process`, { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) {
      const msg = data?.error?.message || data?.detail?.error?.message || "Processing failed.";
      statusDiv.innerHTML = `<div class="error-box">${msg}</div>`;
    } else {
      statusDiv.innerHTML = `<div class="success-box">Processed: ${data.document_name} — ${data.processing_status}</div>`;
      loadDocuments();
    }
  } catch (err) {
    statusDiv.innerHTML = `<div class="error-box">Request failed: ${err}</div>`;
  } finally {
    submitBtn.disabled = false;
  }
});

loadDocuments();
