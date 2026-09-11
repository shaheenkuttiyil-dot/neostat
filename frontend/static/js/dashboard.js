const API_PREFIX = "/api/v1";

/* Re-uploading the same file creates new DB rows; stats should reflect
   the latest run per document name. */
function latestPerName(docs) {
  const map = new Map();
  for (const d of docs) {
    const prev = map.get(d.document_name);
    if (!prev || new Date(d.processed_at) > new Date(prev.processed_at)) {
      map.set(d.document_name, d);
    }
  }
  return [...map.values()];
}

function confidencePct(c) {
  return c === null || c === undefined ? "—" : Math.round(c * 100) + "%";
}

async function loadDashboard() {
  const tbody = document.getElementById("doc-table-body");
  const emptyState = document.getElementById("empty-state");
  const docsCard = document.getElementById("docs-card");
  try {
    const res = await fetch(`${API_PREFIX}/documents`);
    const docs = await res.json();
    const latest = latestPerName(Array.isArray(docs) ? docs : []);

    // ---- stat cards ----
    document.getElementById("stat-total").textContent = latest.length;
    document.getElementById("stat-passed").textContent =
      latest.filter(d => d.processing_status === "PASS").length;
    document.getElementById("stat-failed").textContent =
      latest.filter(d => d.processing_status === "FAILED").length;

    // ---- table or empty state ----
    if (!latest.length) {
      emptyState.style.display = "block";
      docsCard.style.display = "none";
      return;
    }
    emptyState.style.display = "none";
    docsCard.style.display = "block";
    tbody.innerHTML = latest.map(d => `
      <tr onclick="window.location.href='/document/${encodeURIComponent(d.document_name)}'">
        <td>${d.document_name}</td>
        <td>${d.document_type}</td>
        <td><span class="status-pill status-${d.processing_status}">${d.processing_status}</span></td>
        <td class="mono">${confidencePct(d.overall_confidence)}</td>
        <td>${new Date(d.processed_at).toLocaleString()}</td>
      </tr>`).join("");
  } catch (e) {
    emptyState.style.display = "block";
    emptyState.querySelector(".empty-title").textContent = "Failed to load documents";
    emptyState.querySelector(".empty-sub").textContent = "Check that the API is running.";
    docsCard.style.display = "none";
  }
}

loadDashboard();