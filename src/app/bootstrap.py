from datetime import datetime, timezone

from flask import Flask
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .extensions import db
from .models.submission import _generate_public_id
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
    try:
        ensure_database_schema(app, force=True)
    except SQLAlchemyError:
        return

    if not app.config.get("BOOTSTRAP_ON_STARTUP"):
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


def ensure_database_schema(app: Flask, force: bool = False) -> None:
    state = app.extensions.setdefault("schema_repair_state", {"checked": False})
    if state["checked"] and not force:
        return

    try:
        db.create_all()
        _repair_legacy_schema(app)
    except SQLAlchemyError as exc:
        db.session.rollback()
        state["checked"] = False
        app.logger.exception("启动或请求阶段建表/修复旧表失败")
        app.config["BOOTSTRAP_LAST_ERROR"] = f"建表或修复旧表失败：{exc}"
        raise

    state["checked"] = True
    app.config.pop("BOOTSTRAP_LAST_ERROR", None)


def _repair_legacy_schema(app: Flask) -> None:
    inspector = inspect(db.engine)
    if "submissions" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("submissions")}
    dialect_name = db.engine.dialect.name
    timestamp_type = "TIMESTAMP WITH TIME ZONE" if dialect_name == "postgresql" else "DATETIME"

    column_definitions = {
        "student_name": "VARCHAR(80)",
        "problem_url": "VARCHAR(500)",
        "public_id": "VARCHAR(32)",
        "problem_source": "VARCHAR(32)",
        "problem_title": "VARCHAR(255)",
        "problem_path": "VARCHAR(120)",
        "language": "VARCHAR(16)",
        "code_text": "TEXT",
        "client_ip_hash": "VARCHAR(64)",
        "fetch_status": "VARCHAR(16)",
        "diagnosis_status": "VARCHAR(16)",
        "created_at": timestamp_type,
    }

    with db.engine.begin() as connection:
        for column_name, column_type in column_definitions.items():
            if column_name in existing_columns:
                continue
            if dialect_name == "postgresql":
                connection.execute(
                    text(f"ALTER TABLE submissions ADD COLUMN IF NOT EXISTS {column_name} {column_type}")
                )
            else:
                connection.execute(text(f"ALTER TABLE submissions ADD COLUMN {column_name} {column_type}"))

        rows_missing_public_id = connection.execute(
            text("SELECT id FROM submissions WHERE public_id IS NULL OR public_id = ''")
        ).fetchall()
        for row in rows_missing_public_id:
            connection.execute(
                text("UPDATE submissions SET public_id = :public_id WHERE id = :id"),
                {"public_id": _generate_public_id(), "id": row.id},
            )

        defaults = {
            "student_name": "",
            "problem_url": "",
            "problem_source": "openjudge",
            "language": "cpp",
            "code_text": "",
            "fetch_status": "pending",
            "diagnosis_status": "pending",
        }
        for column_name, default_value in defaults.items():
            connection.execute(
                text(
                    f"UPDATE submissions SET {column_name} = :default_value "
                    f"WHERE {column_name} IS NULL OR {column_name} = ''"
                ),
                {"default_value": default_value},
            )

        connection.execute(
            text("UPDATE submissions SET created_at = :created_at WHERE created_at IS NULL"),
            {"created_at": datetime.now(timezone.utc)},
        )
        connection.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_submissions_public_id ON submissions (public_id)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_submissions_problem_path ON submissions (problem_path)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_submissions_created_at ON submissions (created_at)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_submissions_client_ip_hash ON submissions (client_ip_hash)")
        )
