"""Basic API flow test: health check + unsupported file type rejection."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import io
from fastapi.testclient import TestClient
from app.main import app

# Using a context manager ensures FastAPI's startup event (DB init) actually
# runs before the tests hit the API - TestClient() alone does not trigger it.
client = TestClient(app)
with TestClient(app) as _startup_client:
    pass


def test_health_endpoint():
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_process_rejects_unsupported_file_type():
    resp = client.post(
        "/api/v1/documents/process",
        files={"file": ("notes.txt", io.BytesIO(b"hello world"), "text/plain")},
        data={"document_type": "invoice"},
    )
    assert resp.status_code == 415
    body = resp.json()
    assert body["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_get_unknown_document_returns_404():
    resp = client.get("/api/v1/documents/does-not-exist.pdf")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_list_documents_endpoint():
    resp = client.get("/api/v1/documents")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
