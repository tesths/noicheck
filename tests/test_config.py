import importlib

import pytest

from src.app import create_app
from src.app.config import _normalize_database_url


def _reload_config_module(monkeypatch, **env):
    keys = [
        "AI_API_KEY",
        "AI_BASE_URL",
        "AI_MODEL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
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
