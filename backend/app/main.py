"""
Application entrypoint. Wires up FastAPI, DB init, logging, routers,
static files and the Jinja2-rendered frontend (dashboard + document detail).
"""
import os
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.database import init_db
from app.api.routes import documents as documents_routes
from app.utils.exceptions import AppError

configure_logging()
logger = get_logger(__name__)
settings = get_settings()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")

app = FastAPI(
    title=settings.APP_NAME,
    description="Document Intelligence Extraction, Validation & API Platform",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_routes.router, prefix=settings.API_V1_PREFIX, tags=["documents"])

# --- Frontend (server-rendered shell, JS calls the API above) ---
templates = Jinja2Templates(directory=os.path.join(FRONTEND_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(FRONTEND_DIR, "static")), name="static")


@app.on_event("startup")
def on_startup():
    init_db()
    logger.info("Application startup complete. DB initialized.")


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.get("/", include_in_schema=False)
def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request, "api_prefix": settings.API_V1_PREFIX})


@app.get("/document/{document_name}", include_in_schema=False)
def document_detail(request: Request, document_name: str):
    return templates.TemplateResponse(
        "document_result.html",
        {"request": request, "document_name": document_name, "api_prefix": settings.API_V1_PREFIX},
    )
