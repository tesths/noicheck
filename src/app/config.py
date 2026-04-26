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


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _is_production_environment() -> bool:
    vercel_env = os.getenv("VERCEL_ENV", "").strip().lower()
    flask_env = os.getenv("FLASK_ENV", os.getenv("APP_ENV", "")).strip().lower()
    return vercel_env == "production" or flask_env == "production"


def _build_engine_options(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"connect_args": {"timeout": 30}}
    return {
        "pool_pre_ping": True,
        "pool_recycle": int(os.getenv("SQLALCHEMY_POOL_RECYCLE", "300")),
        "pool_size": int(os.getenv("SQLALCHEMY_POOL_SIZE", "2")),
        "max_overflow": int(os.getenv("SQLALCHEMY_MAX_OVERFLOW", "1")),
    }


class Config:
    IS_PRODUCTION = _is_production_environment()
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = _normalize_database_url(os.getenv("DATABASE_URL"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = _build_engine_options(SQLALCHEMY_DATABASE_URI)

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = IS_PRODUCTION
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = IS_PRODUCTION

    WTF_CSRF_TIME_LIMIT = None

    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro").strip()
    ADMIN_INIT_USERNAME = os.getenv("ADMIN_INIT_USERNAME", "").strip()
    ADMIN_INIT_PASSWORD = os.getenv("ADMIN_INIT_PASSWORD", "")
    BOOTSTRAP_ON_STARTUP = _env_flag("BOOTSTRAP_ON_STARTUP", default=IS_PRODUCTION)
    REQUIRE_PRODUCTION_ENV = _env_flag("REQUIRE_PRODUCTION_ENV", default=IS_PRODUCTION)

    OPENJUDGE_REQUEST_TIMEOUT = float(os.getenv("OPENJUDGE_REQUEST_TIMEOUT", "10"))
    SUBMISSION_CODE_MAX_LENGTH = int(os.getenv("SUBMISSION_CODE_MAX_LENGTH", "20000"))
    RATE_LIMIT_MAX_SUBMISSIONS = int(os.getenv("RATE_LIMIT_MAX_SUBMISSIONS", "20"))
    RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "300"))
