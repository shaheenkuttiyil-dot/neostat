"""
Application configuration.
All secrets/config are read from environment variables (.env locally,
platform environment variables in deployment). Nothing sensitive is hardcoded.
"""
import os
from functools import lru_cache

try:
    from dotenv import load_dotenv
    # Look for .env in the project root (one level above backend/), and also
    # allow a .env placed directly inside backend/ - whichever is found first.
    _here = os.path.dirname(os.path.abspath(__file__))  # backend/app/core
    _backend_dir = os.path.dirname(os.path.dirname(_here))  # backend/
    _project_root = os.path.dirname(_backend_dir)  # project-root/
    for _candidate in (os.path.join(_backend_dir, ".env"), os.path.join(_project_root, ".env")):
        if os.path.exists(_candidate):
            load_dotenv(_candidate)
            break
except ImportError:
    # python-dotenv not installed - fall back to relying on real environment
    # variables being set directly (e.g. by the deployment platform).
    pass


class Settings:
    APP_NAME: str = "Document Intelligence Platform"
    API_V1_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./data/documents.db")

    # File / document constraints
    MAX_PAGES: int = int(os.getenv("MAX_PAGES", "3"))
    ALLOWED_CONTENT_TYPES = {
        "application/pdf": "pdf",
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
    }
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "15"))

    # LLM provider used for field/table extraction: Groq only.
    LLM_PROVIDER: str = "groq"
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "3"))

    # OCR
    TESSERACT_CMD: str = os.getenv("TESSERACT_CMD", "")  # optional override path

    # Financial validation tolerance (absolute currency-unit tolerance)
    VALIDATION_TOLERANCE: float = float(os.getenv("VALIDATION_TOLERANCE", "1.0"))
    # Relative tolerance as a fraction (0.001 = 0.1%). A fixed absolute
    # tolerance alone is meaningless for financial statements reported in
    # thousands/crores - a genuine single-digit OCR misread on a 9-figure
    # number produces a variance of a few thousand, which is proportionally
    # tiny but dwarfs an absolute tolerance of 1.0. A check passes if its
    # variance is within EITHER the absolute OR the relative tolerance.
    VALIDATION_RELATIVE_TOLERANCE: float = float(os.getenv("VALIDATION_RELATIVE_TOLERANCE", "0.001"))

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Upload storage (temp working directory for incoming files)
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./data/uploads")


@lru_cache()
def get_settings() -> Settings:
    return Settings()
