from flask import Flask
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .services.auth import ensure_admin_user

_WEAK_SECRET_KEYS = {"", "dev-secret-key", "replace-me", "change-me"}


def validate_runtime_config(app: Flask) -> None:
    if not app.config.get("REQUIRE_PRODUCTION_ENV"):
        return

    errors: list[str] = []
    secret_key = str(app.config.get("SECRET_KEY", "")).strip()
    database_uri = str(app.config.get("SQLALCHEMY_DATABASE_URI", "")).strip()

    if secret_key in _WEAK_SECRET_KEYS:
        errors.append("SECRET_KEY 必须设置为安全的随机字符串。")
    if not database_uri or database_uri.startswith("sqlite"):
        errors.append("DATABASE_URL 必须指向公网 Postgres，不能使用 SQLite。")
    if not str(app.config.get("DEEPSEEK_API_KEY", "")).strip():
        errors.append("DEEPSEEK_API_KEY 不能为空。")
    if app.config.get("BOOTSTRAP_ON_STARTUP"):
        if not str(app.config.get("ADMIN_INIT_USERNAME", "")).strip():
            errors.append("ADMIN_INIT_USERNAME 不能为空。")
        if not str(app.config.get("ADMIN_INIT_PASSWORD", "")):
            errors.append("ADMIN_INIT_PASSWORD 不能为空。")

    if errors:
        raise RuntimeError("生产环境配置不完整：" + " ".join(errors))


def bootstrap_app(app: Flask) -> None:
    if not app.config.get("BOOTSTRAP_ON_STARTUP"):
        return

    db.create_all()

    username = str(app.config.get("ADMIN_INIT_USERNAME", "")).strip()
    password = str(app.config.get("ADMIN_INIT_PASSWORD", ""))
    if not username or not password:
        return

    admin = ensure_admin_user(username=username, password=password)
    try:
        db.session.add(admin)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        admin = ensure_admin_user(username=username, password=password)
        db.session.add(admin)
        db.session.commit()
