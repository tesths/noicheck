import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app import create_app  # noqa: E402
from src.app.extensions import db  # noqa: E402


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {}
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    DEEPSEEK_API_KEY = "test-key"
    DEEPSEEK_BASE_URL = "https://api.deepseek.com"
    DEEPSEEK_MODEL = "deepseek-chat"
    ADMIN_INIT_USERNAME = ""
    ADMIN_INIT_PASSWORD = ""
    BOOTSTRAP_ON_STARTUP = False
    REQUIRE_PRODUCTION_ENV = False
    OPENJUDGE_REQUEST_TIMEOUT = 1
    SUBMISSION_CODE_MAX_LENGTH = 20000
    RATE_LIMIT_MAX_SUBMISSIONS = 20
    RATE_LIMIT_WINDOW_SECONDS = 300


@pytest.fixture()
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()
