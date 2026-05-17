import importlib

import pytest

from src.app import create_app
from src.app.config import _normalize_database_url


def _reload_config_module(monkeypatch, **env):
    keys = [
        "AI_API_KEY",
        "AI_BASE_URL",
        "AI_MODEL",
        "AI_REQUEST_TIMEOUT_SECONDS",
        "AI_MAX_RETRIES",
        "AI_RETRY_BACKOFF_SECONDS",
        "AI_MAX_PROMPT_CHARS",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "JOB_INTERNAL_REQUEST_TIMEOUT_SECONDS",
        "JOB_INTERNAL_MAX_RETRIES",
        "PROBLEM_SNAPSHOT_CACHE_ENABLED",
        "PROBLEM_SNAPSHOT_CACHE_TTL_SECONDS",
        "AI_CONCURRENCY_LIMIT_STUDENT",
        "AI_CONCURRENCY_LIMIT_TEACHER",
        "FETCH_CONCURRENCY_LIMIT",
        "ENABLE_SUBMISSION_STATUS_POLLING",
        "SQLALCHEMY_POOL_SIZE",
        "SQLALCHEMY_MAX_OVERFLOW",
        "SQLALCHEMY_POOL_TIMEOUT",
        "DATABASE_URL",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    import src.app.config as config_module

    return importlib.reload(config_module)


def test_normalize_database_url_expands_relative_sqlite_path():
    normalized = _normalize_database_url("sqlite:///instance/dev.db")
    assert normalized.startswith("sqlite:////")
    assert normalized.endswith("/instance/dev.db")


def test_config_prefers_ai_env_and_keeps_legacy_aliases(monkeypatch):
    config_module = _reload_config_module(
        monkeypatch,
        AI_API_KEY="ai-key",
        AI_BASE_URL="https://api.example.com/v1",
        AI_MODEL="ai-model",
        DEEPSEEK_API_KEY="legacy-key",
        DEEPSEEK_BASE_URL="https://legacy.example.com",
        DEEPSEEK_MODEL="legacy-model",
    )

    assert config_module.Config.AI_API_KEY == "ai-key"
    assert config_module.Config.AI_BASE_URL == "https://api.example.com/v1"
    assert config_module.Config.AI_MODEL == "ai-model"
    assert config_module.Config.DEEPSEEK_API_KEY == "ai-key"
    assert config_module.Config.DEEPSEEK_BASE_URL == "https://api.example.com/v1"
    assert config_module.Config.DEEPSEEK_MODEL == "ai-model"


def test_config_falls_back_to_deepseek_env_when_ai_env_missing(monkeypatch):
    config_module = _reload_config_module(
        monkeypatch,
        DEEPSEEK_API_KEY="legacy-key",
        DEEPSEEK_BASE_URL="https://legacy.example.com",
        DEEPSEEK_MODEL="legacy-model",
    )

    assert config_module.Config.AI_API_KEY == "legacy-key"
    assert config_module.Config.AI_BASE_URL == "https://legacy.example.com"
    assert config_module.Config.AI_MODEL == "legacy-model"
    assert config_module.Config.DEEPSEEK_API_KEY == "legacy-key"
    assert config_module.Config.DEEPSEEK_BASE_URL == "https://legacy.example.com"
    assert config_module.Config.DEEPSEEK_MODEL == "legacy-model"


def test_config_exposes_new_stability_and_concurrency_defaults(monkeypatch):
    config_module = _reload_config_module(monkeypatch, DATABASE_URL="postgresql://user:pass@localhost:5432/db")

    assert config_module.Config.AI_REQUEST_TIMEOUT_SECONDS == 30.0
    assert config_module.Config.AI_MAX_RETRIES == 1
    assert config_module.Config.AI_RETRY_BACKOFF_SECONDS == 1.0
    assert config_module.Config.AI_MAX_PROMPT_CHARS == 12000
    assert config_module.Config.JOB_INTERNAL_REQUEST_TIMEOUT_SECONDS == 15.0
    assert config_module.Config.JOB_INTERNAL_MAX_RETRIES == 1
    assert config_module.Config.PROBLEM_SNAPSHOT_CACHE_ENABLED is True
    assert config_module.Config.PROBLEM_SNAPSHOT_CACHE_TTL_SECONDS == 86400
    assert config_module.Config.AI_CONCURRENCY_LIMIT_STUDENT == 8
    assert config_module.Config.AI_CONCURRENCY_LIMIT_TEACHER == 4
    assert config_module.Config.FETCH_CONCURRENCY_LIMIT == 8
    assert config_module.Config.ENABLE_SUBMISSION_STATUS_POLLING is True
    assert config_module.Config.SQLALCHEMY_ENGINE_OPTIONS["pool_size"] == 5
    assert config_module.Config.SQLALCHEMY_ENGINE_OPTIONS["max_overflow"] == 10
    assert config_module.Config.SQLALCHEMY_ENGINE_OPTIONS["pool_timeout"] == 10


def test_create_app_rejects_missing_production_settings():
    class ProductionConfig:
        TESTING = True
        SECRET_KEY = "dev-secret-key"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        SQLALCHEMY_ENGINE_OPTIONS = {}
        WTF_CSRF_ENABLED = False
        DEEPSEEK_API_KEY = ""
        DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        DEEPSEEK_MODEL = "deepseek-v4-pro"
        ADMIN_INIT_USERNAME = ""
        ADMIN_INIT_PASSWORD = ""
        BOOTSTRAP_ON_STARTUP = True
        REQUIRE_PRODUCTION_ENV = True

    with pytest.raises(RuntimeError, match="生产环境配置不完整"):
        create_app(ProductionConfig)


def test_create_app_allows_missing_admin_and_deepseek_in_production_if_core_env_is_valid():
    class ProductionConfig:
        TESTING = True
        SECRET_KEY = "very-secure-secret-key"
        SQLALCHEMY_DATABASE_URI = "postgresql+psycopg://user:pass@localhost:5432/db"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        SQLALCHEMY_ENGINE_OPTIONS = {}
        WTF_CSRF_ENABLED = False
        DEEPSEEK_API_KEY = ""
        DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        DEEPSEEK_MODEL = "deepseek-v4-pro"
        ADMIN_INIT_USERNAME = ""
        ADMIN_INIT_PASSWORD = ""
        BOOTSTRAP_ON_STARTUP = False
        REQUIRE_PRODUCTION_ENV = True

    app = create_app(ProductionConfig)
    assert app is not None


def test_create_app_does_not_create_instance_directory_on_startup(monkeypatch):
    import pathlib

    def fail_mkdir(self, *args, **kwargs):
        raise AssertionError("应用启动时不应创建 instance 目录")

    monkeypatch.setattr(pathlib.Path, "mkdir", fail_mkdir)

    class MinimalConfig:
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        SQLALCHEMY_ENGINE_OPTIONS = {}
        WTF_CSRF_ENABLED = False
        DEEPSEEK_API_KEY = "test-key"
        DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        DEEPSEEK_MODEL = "deepseek-v4-pro"
        ADMIN_INIT_USERNAME = ""
        ADMIN_INIT_PASSWORD = ""
        BOOTSTRAP_ON_STARTUP = False
        REQUIRE_PRODUCTION_ENV = False

    app = create_app(MinimalConfig)
    assert app is not None


def test_create_app_skips_bootstrap_for_flask_db_commands(monkeypatch):
    calls = []

    def fake_bootstrap(app):
        calls.append(app)

    monkeypatch.setattr("src.app.bootstrap_app", fake_bootstrap)
    monkeypatch.setattr("sys.argv", ["flask", "db", "upgrade"])

    class MinimalConfig:
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        SQLALCHEMY_ENGINE_OPTIONS = {}
        WTF_CSRF_ENABLED = False
        DEEPSEEK_API_KEY = "test-key"
        DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        DEEPSEEK_MODEL = "deepseek-v4-pro"
        ADMIN_INIT_USERNAME = ""
        ADMIN_INIT_PASSWORD = ""
        BOOTSTRAP_ON_STARTUP = False
        REQUIRE_PRODUCTION_ENV = False

    app = create_app(MinimalConfig)

    assert app is not None
    assert calls == []
