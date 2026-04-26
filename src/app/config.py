import os
from pathlib import Path


def _default_sqlite_uri() -> str:
    instance_dir = Path(__file__).resolve().parents[2] / "instance"
    return f"sqlite:///{instance_dir / 'dev.db'}"


def _normalize_database_url(url: str | None) -> str:
    if not url:
        return _default_sqlite_uri()
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////") and url != "sqlite:///:memory:":
        relative_path = url.removeprefix("sqlite:///")
        absolute_path = (Path(__file__).resolve().parents[2] / relative_path).resolve()
        return f"sqlite:///{absolute_path}"
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = _normalize_database_url(os.getenv("DATABASE_URL"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"timeout": 30}} if SQLALCHEMY_DATABASE_URI.startswith("sqlite") else {}

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("FLASK_ENV") == "production"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = os.getenv("FLASK_ENV") == "production"

    WTF_CSRF_TIME_LIMIT = None

    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro").strip()

    OPENJUDGE_REQUEST_TIMEOUT = float(os.getenv("OPENJUDGE_REQUEST_TIMEOUT", "10"))
    SUBMISSION_CODE_MAX_LENGTH = int(os.getenv("SUBMISSION_CODE_MAX_LENGTH", "20000"))
    RATE_LIMIT_MAX_SUBMISSIONS = int(os.getenv("RATE_LIMIT_MAX_SUBMISSIONS", "20"))
    RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "300"))
