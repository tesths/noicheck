from pathlib import Path

from src.app import create_app
from src.app.extensions import db
from src.app.models import AdminUser
from src.app.services.auth import authenticate_admin, hash_client_ip, hash_password, verify_password


def test_authenticate_admin_returns_user(app):
    with app.app_context():
        admin = AdminUser(username="teacher", password_hash=hash_password("pass123"))
        db.session.add(admin)
        db.session.commit()

        authenticated = authenticate_admin("teacher", "pass123")

        assert authenticated is not None
        assert authenticated.username == "teacher"


def test_hash_client_ip_is_stable():
    assert hash_client_ip("127.0.0.1") == hash_client_ip("127.0.0.1")


def test_bootstrap_creates_tables_and_admin(tmp_path):
    database_path = tmp_path / "bootstrap.db"

    class BootstrapConfig:
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        SQLALCHEMY_ENGINE_OPTIONS = {}
        WTF_CSRF_ENABLED = False
        DEEPSEEK_API_KEY = "test-key"
        DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        DEEPSEEK_MODEL = "deepseek-v4-pro"
        ADMIN_INIT_USERNAME = "bootstrap-admin"
        ADMIN_INIT_PASSWORD = "bootstrap-pass"
        BOOTSTRAP_ON_STARTUP = True
        REQUIRE_PRODUCTION_ENV = False
        SESSION_COOKIE_SECURE = False
        REMEMBER_COOKIE_SECURE = False

    app = create_app(BootstrapConfig)
    with app.app_context():
        admin = AdminUser.query.filter_by(username="bootstrap-admin").one()
        assert verify_password(admin.password_hash, "bootstrap-pass")
        assert Path(database_path).exists()
        db.session.remove()


def test_bootstrap_updates_existing_admin_password(tmp_path):
    database_path = tmp_path / "bootstrap-update.db"

    class FirstBootstrapConfig:
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        SQLALCHEMY_ENGINE_OPTIONS = {}
        WTF_CSRF_ENABLED = False
        DEEPSEEK_API_KEY = "test-key"
        DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        DEEPSEEK_MODEL = "deepseek-v4-pro"
        ADMIN_INIT_USERNAME = "bootstrap-admin"
        ADMIN_INIT_PASSWORD = "first-pass"
        BOOTSTRAP_ON_STARTUP = True
        REQUIRE_PRODUCTION_ENV = False
        SESSION_COOKIE_SECURE = False
        REMEMBER_COOKIE_SECURE = False

    class SecondBootstrapConfig(FirstBootstrapConfig):
        ADMIN_INIT_PASSWORD = "second-pass"

    first_app = create_app(FirstBootstrapConfig)
    with first_app.app_context():
        first_admin = AdminUser.query.filter_by(username="bootstrap-admin").one()
        assert verify_password(first_admin.password_hash, "first-pass")
        db.session.remove()

    second_app = create_app(SecondBootstrapConfig)
    with second_app.app_context():
        second_admin = AdminUser.query.filter_by(username="bootstrap-admin").one()
        assert verify_password(second_admin.password_hash, "second-pass")
        db.session.remove()
