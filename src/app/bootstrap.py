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

    columns = inspector.get_columns("submissions")
    existing_columns = {column["name"] for column in columns}
    dialect_name = db.engine.dialect.name
    timestamp_type = "TIMESTAMP WITH TIME ZONE" if dialect_name == "postgresql" else "DATETIME"

    column_definitions = {
        "student_name": "VARCHAR(80)",
        "student_user_id": "INTEGER",
        "request_token": "VARCHAR(64)",
        "problem_url": "VARCHAR(500)",
        "public_id": "VARCHAR(32)",
        "problem_source": "VARCHAR(32)",
        "problem_title": "VARCHAR(255)",
        "problem_path": "VARCHAR(120)",
        "language": "VARCHAR(16)",
        "code_text": "TEXT",
        "client_ip_hash": "VARCHAR(64)",
        "submission_mode": "VARCHAR(32)",
        "fetch_status": "VARCHAR(16)",
        "student_hint_status": "VARCHAR(16)",
        "diagnosis_status": "VARCHAR(16)",
        "created_at": timestamp_type,
        "deleted_at": timestamp_type,
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

        if dialect_name == "postgresql":
            _repair_postgresql_submission_id_sequence(connection, existing_columns)

        rows_with_public_id = connection.execute(
            text("SELECT id, public_id FROM submissions ORDER BY id")
        ).fetchall()
        seen_public_ids: set[str] = set()
        for row in rows_with_public_id:
            public_id = str(row.public_id or "").strip()
            if public_id and public_id not in seen_public_ids:
                seen_public_ids.add(public_id)
                continue

            while True:
                regenerated_public_id = _generate_public_id()
                if regenerated_public_id not in seen_public_ids:
                    seen_public_ids.add(regenerated_public_id)
                    break

            connection.execute(
                text("UPDATE submissions SET public_id = :public_id WHERE id = :id"),
                {"public_id": regenerated_public_id, "id": row.id},
            )

        defaults = {
            "student_name": "",
            "problem_url": "",
            "problem_source": "openjudge",
            "language": "cpp",
            "code_text": "",
            "submission_mode": "teacher_review",
            "fetch_status": "pending",
            "student_hint_status": "pending",
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
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_submissions_student_user_id ON submissions (student_user_id)")
        )
        connection.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_submissions_request_token ON submissions (request_token)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_submissions_deleted_at ON submissions (deleted_at)")
        )

    _repair_legacy_diagnosis_runs_schema(app)
    _repair_legacy_student_users_schema(app)


def _repair_legacy_diagnosis_runs_schema(app: Flask) -> None:
    inspector = inspect(db.engine)
    if "diagnosis_runs" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("diagnosis_runs")}
    if "audience" in existing_columns:
        return

    dialect_name = db.engine.dialect.name
    with db.engine.begin() as connection:
        if dialect_name == "postgresql":
            connection.execute(text("ALTER TABLE diagnosis_runs ADD COLUMN IF NOT EXISTS audience VARCHAR(16)"))
        else:
            connection.execute(text("ALTER TABLE diagnosis_runs ADD COLUMN audience VARCHAR(16)"))

        connection.execute(
            text("UPDATE diagnosis_runs SET audience = 'teacher' WHERE audience IS NULL OR audience = ''")
        )


def _repair_legacy_student_users_schema(app: Flask) -> None:
    inspector = inspect(db.engine)
    if "student_users" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("student_users")}
    if "real_name" in existing_columns:
        return

    dialect_name = db.engine.dialect.name
    with db.engine.begin() as connection:
        if dialect_name == "postgresql":
            connection.execute(text("ALTER TABLE student_users ADD COLUMN IF NOT EXISTS real_name VARCHAR(80)"))
        else:
            connection.execute(text("ALTER TABLE student_users ADD COLUMN real_name VARCHAR(80)"))

        connection.execute(
            text("UPDATE student_users SET real_name = '' WHERE real_name IS NULL OR real_name = ''")
        )


def _repair_postgresql_submission_id_sequence(connection, existing_columns: set[str]) -> None:
    if "id" not in existing_columns:
        return

    sequence_name = connection.execute(
        text("SELECT pg_get_serial_sequence('submissions', 'id')")
    ).scalar()

    if not sequence_name:
        connection.execute(text("CREATE SEQUENCE IF NOT EXISTS submissions_id_seq"))
        connection.execute(text("ALTER SEQUENCE submissions_id_seq OWNED BY submissions.id"))
        connection.execute(
            text("ALTER TABLE submissions ALTER COLUMN id SET DEFAULT nextval('submissions_id_seq')")
        )
        sequence_name = "submissions_id_seq"

    connection.execute(
        text(
            """
            WITH sequence_state AS (
                SELECT COALESCE(MAX(id), 0) AS max_id FROM submissions
            )
            SELECT setval(
                CAST(:sequence_name AS regclass),
                CASE WHEN max_id > 0 THEN max_id ELSE 1 END,
                max_id > 0
            )
            FROM sequence_state
            """
        ),
        {"sequence_name": sequence_name},
    )
