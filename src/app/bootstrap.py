from flask import Flask
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

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

    if errors:
        raise RuntimeError("生产环境配置不完整：" + " ".join(errors))


def bootstrap_app(app: Flask) -> None:
    if not app.config.get("BOOTSTRAP_ON_STARTUP"):
        return

    try:
        db.create_all()
    except SQLAlchemyError as exc:
        db.session.rollback()
        app.logger.exception("启动 bootstrap 建表失败")
        app.config["BOOTSTRAP_LAST_ERROR"] = f"建表失败：{exc}"
        return

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
    except SQLAlchemyError as exc:
        db.session.rollback()
        app.logger.exception("启动 bootstrap 初始化管理员失败")
        app.config["BOOTSTRAP_LAST_ERROR"] = f"初始化管理员失败：{exc}"
