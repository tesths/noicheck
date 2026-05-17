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


def _first_env_value(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def _is_production_environment() -> bool:
    vercel_env = os.getenv("VERCEL_ENV", "").strip().lower()
    flask_env = os.getenv("FLASK_ENV", os.getenv("APP_ENV", "")).strip().lower()
    return vercel_env == "production" or flask_env == "production"


def _build_engine_options(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"connect_args": {"timeout": 30}}
    pool_size = max(int(os.getenv("SQLALCHEMY_POOL_SIZE", "5")), 5)
    max_overflow = max(int(os.getenv("SQLALCHEMY_MAX_OVERFLOW", "10")), 10)
    pool_timeout = max(int(os.getenv("SQLALCHEMY_POOL_TIMEOUT", "10")), 10)
    return {
        "pool_pre_ping": True,
        "pool_recycle": int(os.getenv("SQLALCHEMY_POOL_RECYCLE", "300")),
        "pool_size": pool_size,
        "max_overflow": max_overflow,
        "pool_timeout": pool_timeout,
    }


def _default_job_queue_backend() -> str:
    explicit = os.getenv("JOB_QUEUE_BACKEND")
    if explicit:
        return explicit.strip().lower()
    return "vercel" if _is_production_environment() else "inline"


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

    AI_API_KEY = _first_env_value("AI_API_KEY", "DEEPSEEK_API_KEY")
    AI_BASE_URL = _first_env_value("AI_BASE_URL", "DEEPSEEK_BASE_URL", default="https://api.deepseek.com")
    AI_MODEL = _first_env_value("AI_MODEL", "DEEPSEEK_MODEL", default="deepseek-v4-pro")
    AI_REQUEST_TIMEOUT_SECONDS = float(os.getenv("AI_REQUEST_TIMEOUT_SECONDS", "30"))
    AI_MAX_RETRIES = int(os.getenv("AI_MAX_RETRIES", "1"))
    AI_RETRY_BACKOFF_SECONDS = float(os.getenv("AI_RETRY_BACKOFF_SECONDS", "1"))
    AI_MAX_PROMPT_CHARS = int(os.getenv("AI_MAX_PROMPT_CHARS", "12000"))
    DEEPSEEK_API_KEY = AI_API_KEY
    DEEPSEEK_BASE_URL = AI_BASE_URL
    DEEPSEEK_MODEL = AI_MODEL
    ADMIN_INIT_USERNAME = os.getenv("ADMIN_INIT_USERNAME", "").strip()
    ADMIN_INIT_PASSWORD = os.getenv("ADMIN_INIT_PASSWORD", "")
    BOOTSTRAP_ON_STARTUP = _env_flag("BOOTSTRAP_ON_STARTUP", default=IS_PRODUCTION)
    REQUIRE_PRODUCTION_ENV = _env_flag("REQUIRE_PRODUCTION_ENV", default=IS_PRODUCTION)

    OPENJUDGE_REQUEST_TIMEOUT = float(os.getenv("OPENJUDGE_REQUEST_TIMEOUT", "10"))
    SUBMISSION_CODE_MAX_LENGTH = int(os.getenv("SUBMISSION_CODE_MAX_LENGTH", "20000"))
    RATE_LIMIT_MAX_SUBMISSIONS = int(os.getenv("RATE_LIMIT_MAX_SUBMISSIONS", "20"))
    RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "300"))
    JOB_QUEUE_BACKEND = _default_job_queue_backend()
    VERCEL_QUEUE_REGION = os.getenv("VERCEL_QUEUE_REGION", "iad1").strip()
    VERCEL_QUEUE_TOPIC = os.getenv("VERCEL_QUEUE_TOPIC", "noi_submission_jobs").strip()
    VERCEL_OIDC_TOKEN = os.getenv("VERCEL_OIDC_TOKEN", "").strip()
    JOB_QUEUE_PUBLISH_TIMEOUT_SECONDS = float(os.getenv("JOB_QUEUE_PUBLISH_TIMEOUT_SECONDS", "3"))
    INTERNAL_JOB_TOKEN = os.getenv("INTERNAL_JOB_TOKEN", "").strip()
    JOB_INTERNAL_REQUEST_TIMEOUT_SECONDS = float(os.getenv("JOB_INTERNAL_REQUEST_TIMEOUT_SECONDS", "15"))
    JOB_INTERNAL_MAX_RETRIES = int(os.getenv("JOB_INTERNAL_MAX_RETRIES", "1"))
    PROBLEM_SNAPSHOT_CACHE_ENABLED = _env_flag("PROBLEM_SNAPSHOT_CACHE_ENABLED", default=True)
    PROBLEM_SNAPSHOT_CACHE_TTL_SECONDS = int(os.getenv("PROBLEM_SNAPSHOT_CACHE_TTL_SECONDS", "86400"))
    AI_CONCURRENCY_LIMIT_STUDENT = int(os.getenv("AI_CONCURRENCY_LIMIT_STUDENT", "8"))
    AI_CONCURRENCY_LIMIT_TEACHER = int(os.getenv("AI_CONCURRENCY_LIMIT_TEACHER", "4"))
    FETCH_CONCURRENCY_LIMIT = int(os.getenv("FETCH_CONCURRENCY_LIMIT", "8"))
    ENABLE_SUBMISSION_STATUS_POLLING = _env_flag("ENABLE_SUBMISSION_STATUS_POLLING", default=True)
    APP_BASE_URL = os.getenv("APP_BASE_URL", "").rstrip("/")
