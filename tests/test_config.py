import pytest

from src.app import create_app
from src.app.config import _normalize_database_url


def test_normalize_database_url_expands_relative_sqlite_path():
    normalized = _normalize_database_url("sqlite:///instance/dev.db")
    assert normalized.startswith("sqlite:////")
    assert normalized.endswith("/instance/dev.db")


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
